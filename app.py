import os
from io import BytesIO
from collections import defaultdict, deque
from datetime import date, timedelta
from flask import Flask, request, jsonify, render_template, send_file
from models import db, Department, Employee, Schedule, Holiday

app = Flask(__name__)

# DB config (Render friendly)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    "DATABASE_URL", "sqlite:///local.db"
).replace("postgres://", "postgresql://")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# ----- constants -----
DEPT_DISPATCH = "Dispatch (MOD)"
DEPT_CSR = "CSR"
DEPT_SPEC_OPS_OFFICE = "Spec Ops office"
DEPT_AUTO = "Auto"
DEPT_SHOP = "Shop"
DEPT_DAL = "DAL"
DEPT_CAR = "CAR"
DEPT_ARL = "ARL"
DEPT_COLDEN = "COL/DEN"
DEPT_SPEC_OPS = "Spec Ops"

WEEKLY_ONE = {DEPT_DISPATCH, DEPT_CSR, DEPT_SPEC_OPS_OFFICE, DEPT_ARL, DEPT_SHOP}

# ----- helpers -----
def coming_saturday(from_day: date) -> date:
    # Monday=0..Sunday=6 ; Saturday=5
    return from_day + timedelta(days=(5 - from_day.weekday()) % 7)

def last_saturday_of_year(year: int) -> date:
    last_day = date(year, 12, 31)
    return last_day - timedelta(days=(last_day.weekday() - 5) % 7)

def saturdays_between(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=7)

def build_month_saturdays(sats: list[date]) -> dict[tuple[int,int], list[date]]:
    months = defaultdict(list)
    for d in sats:
        months[(d.year, d.month)].append(d)
    return months

def next_from_deque(q: deque):
    if not q:
        return None
    x = q[0]
    q.rotate(-1)
    return x

@app.before_request
def create_tables_once():
    if not hasattr(app, 'tables_created'):
        db.create_all()
        app.tables_created = True

@app.route("/")
def home():
    return "✅ Flask Scheduler is running!"

# ---------- Departments ----------
@app.route("/departments", methods=["POST"])
def add_department():
    name = request.json["name"].strip()
    if not name:
        return jsonify({"error": "Department name required"}), 400
    dept = Department(name=name)
    db.session.add(dept)
    db.session.commit()
    return jsonify({"id": dept.id, "name": dept.name})

@app.route("/departments", methods=["GET"])
def list_departments():
    depts = Department.query.order_by(Department.id).all()
    return jsonify([{"id": d.id, "name": d.name} for d in depts])

@app.route("/employees", methods=["POST"])
def add_employee():
    body = request.get_json(force=True)
    name = body.get("name", "").strip()
    dept_id = body.get("department_id")
    group_num = body.get("group_num")

    if not name or not dept_id:
        return jsonify({"error": "name and department_id are required"}), 400

    dept = Department.query.get(dept_id)
    if not dept:
        return jsonify({"error": f"Department ID {dept_id} not found"}), 404

    if dept.name == "Spec Ops":
        group_num = int(group_num) if group_num else None
        if group_num and group_num not in (1,2,3,4):
            return jsonify({"error": "group_num must be 1..4 for Spec Ops"}), 400
    else:
        group_num = None

    emp = Employee(name=name, department_id=dept.id, group_num=group_num)
    db.session.add(emp)
    db.session.commit()

    return jsonify({
        "id": emp.id,
        "name": emp.name,
        "department": dept.name,
        "group_num": emp.group_num
    }), 201


# ---------- Employees ----------
@app.route("/employees/add_by_name", methods=["POST"])
def add_employee_by_name():
    body = request.get_json(force=True)
    name = body.get("name", "").strip()
    dept_name = body.get("department_name", "").strip()
    group_num = body.get("group_num")

    if not name or not dept_name:
        return jsonify({"error": "name and department_name are required"}), 400

    dept = Department.query.filter(Department.name.ilike(dept_name)).first()
    if not dept:
        return jsonify({"error": f"Department '{dept_name}' not found"}), 404

    if dept.name == "Spec Ops":
        group_num = int(group_num) if group_num else None
        if group_num and group_num not in (1,2,3,4):
            return jsonify({"error": "group_num must be 1..4 for Spec Ops"}), 400
    else:
        group_num = None

    emp = Employee(name=name, department_id=dept.id, group_num=group_num)
    db.session.add(emp)
    db.session.commit()
    return jsonify({
        "id": emp.id, "name": emp.name,
        "department": dept.name, "group_num": emp.group_num
    }), 201

@app.route("/employees/remove_by_name", methods=["POST"])
def remove_employee_by_name():
    """
    Remove employee by name (case-insensitive).
    Accepts JSON or form: { "name": "Aayush" } OR name=Aayush
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}

    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    # find employee
    emp = Employee.query.filter(
        db.func.lower(Employee.name) == name.lower()
    ).first()

    if not emp:
        return jsonify({"error": f"No employee found with name {name}"}), 404

    # delete employee + related schedules
    Schedule.query.filter_by(employee_id=emp.id).delete()
    db.session.delete(emp)
    db.session.commit()

    return jsonify({"message": f"Removed {name} successfully"})




@app.route("/employees", methods=["GET"])
def list_employees():
    emps = Employee.query.order_by(Employee.id).all()
    return jsonify([
        {"id": e.id, "name": e.name, "department_id": e.department_id, "group_num": e.group_num}
        for e in emps
    ])

# ---------- Holidays ----------
@app.route("/holidays", methods=["POST"])
def add_holiday():
    body = request.get_json(force=True) or {}
    hdate = date.fromisoformat(body["date"])
    note = body.get("note", None)

    hol = Holiday.query.get(hdate)
    if hol:
        hol.note = note
    else:
        db.session.add(Holiday(date=hdate, note=note))

    # Remove any schedule on that date
    Schedule.query.filter(Schedule.date == hdate).delete()
    db.session.commit()
    return jsonify({"date": hdate.isoformat(), "note": note})

@app.route("/holidays", methods=["GET"])
def list_holidays():
    hols = Holiday.query.order_by(Holiday.date).all()
    return jsonify([{"date": h.date.isoformat(), "note": h.note} for h in hols])

@app.route("/schedule/generate", methods=["POST"])
def generate_schedule():
    """
    Generate or repair schedule:
      - Repairs only missing or new employee schedules.
      - Regenerates only future dates (from coming Saturday).
      - Removes duplicate future entries before regenerating.
      - Skips past weeks.
      - Respects department-specific rules (Spec Ops groups, Auto/DAL/COL-DEN custom cycles, Corey rule, Tommy–Edwin pairing, etc.)
      - Ensures rotation continues based on who worked last.
    """
    import json
    from datetime import date
    from collections import deque
    from pathlib import Path

    body = request.get_json(silent=True) or {}

    # --- Safe year parsing ---
    try:
        year = int(body.get("year", date.today().year))
        if year < 1:
            raise ValueError
    except Exception:
        year = date.today().year

    start = coming_saturday(date.today())
    end = last_saturday_of_year(year)
    if start > end:
        return jsonify({"message": f"No Saturdays remaining in {year}."})

    # --- Collect holidays and Saturdays ---
    holiday_set = {h.date for h in Holiday.query.all()}
    all_sats = [d for d in saturdays_between(start, end) if d not in holiday_set]
    by_month = build_month_saturdays(all_sats)

    departments = {d.name: d for d in Department.query.all()}

    # --- Helper: prepare rotation deque ---
    def dept_employees(dept_name: str):
        d = departments.get(dept_name)
        if not d:
            return deque()
        return deque(sorted(list(d.employees), key=lambda e: e.id))

    rot = {name: dept_employees(name) for name in departments.keys()}

    # --- Spec Ops groups ---
    spec_ops_groups = {
        g: sorted(
            [e for e in departments.get(DEPT_SPEC_OPS, Department(name="")).employees if e.group_num == g],
            key=lambda e: e.id
        ) for g in (1, 2, 3, 4)
    }

    # --- CAR: Corey always works ---
    corey_emp = None
    if DEPT_CAR in departments:
        car_emps_all = list(departments[DEPT_CAR].employees)
        for e in car_emps_all:
            if e.name.strip().lower().startswith("corey"):
                corey_emp = e
                break
        rot[DEPT_CAR] = deque(sorted(
            [e for e in car_emps_all if not (corey_emp and e.id == corey_emp.id)],
            key=lambda e: e.id
        ))

    # --- Detect missing coverage or new employees ---
    missing_by_dept = {}
    today = date.today()

    for dept_name, dept in departments.items():
        all_schedules = Schedule.query.filter_by(department_id=dept.id).all()
        scheduled_dates = {s.date for s in all_schedules}
        missing_dates = [d for d in all_sats if d not in scheduled_dates and d >= today]

        # Detect employees who exist in DB but have no future assignments
        all_emp_ids = {e.id for e in dept.employees}
        future_scheduled_emp_ids = {
            s.employee_id for s in all_schedules if s.date >= today
        }
        unscheduled_emps = all_emp_ids - future_scheduled_emp_ids

        # Case 1: Missing Saturdays → repair as usual
        # Case 2: New employees with no future shifts → schedule from today onwards
        if missing_dates or unscheduled_emps:
            if missing_dates:
                missing_by_dept[dept_name] = missing_dates
            else:
                # If all dates filled but new people added, regenerate future dates for that dept
                future_sats = [d for d in all_sats if d >= today]
                missing_by_dept[dept_name] = future_sats

    if not missing_by_dept:
        return jsonify({"message": "✅ Schedule is complete. No repair needed."})

    # --- MAIN LOOP (only for missing departments) ---
    for dept_name, missing_dates in missing_by_dept.items():
        dept = departments[dept_name]
        q = rot[dept_name]
        coming_sat = coming_saturday(date.today())

        # 🧭 Align rotation with whoever worked last
        last_saturday_row = (
            Schedule.query.filter(
                Schedule.department_id == dept.id,
                Schedule.date < coming_sat
            ).order_by(Schedule.date.desc()).first()
        )
        if last_saturday_row:
            last_saturday = last_saturday_row.date
            last_emp_rows = Schedule.query.filter_by(
                department_id=dept.id, date=last_saturday
            ).all()
            if last_emp_rows:
                # For single-employee-per-week departments: skip the last person
                if len(last_emp_rows) == 1:
                    last_emp_id = last_emp_rows[0].employee_id
                    if q and any(e.id == last_emp_id for e in q):
                        while q[0].id != last_emp_id:
                            q.rotate(-1)
                        q.rotate(-1)  # move past last person

        # 🧹 Clean up future schedules for this department
        Schedule.query.filter(
            Schedule.department_id == dept.id,
            Schedule.date >= coming_sat,
            Schedule.override == False
        ).delete()

        # 🧱 Rebuild the schedule for missing/future dates
        for sat in missing_dates:
            month_sats = by_month[(sat.year, sat.month)]
            idx_in_month = month_sats.index(sat) + 1
            week_num = all_sats.index(sat) + 1
            group_for_week = ((week_num - 1) % 4) + 1

            # === DEPARTMENT RULES ===
            if dept_name == DEPT_SPEC_OPS:
                group = spec_ops_groups.get(group_for_week, [])
                for emp in group:
                    db.session.add(Schedule(date=sat, department_id=dept.id, employee_id=emp.id, override=False))

            elif dept_name == DEPT_CAR:
                used_ids = set()
                if corey_emp:
                    db.session.add(Schedule(date=sat, department_id=dept.id, employee_id=corey_emp.id, override=False))
                    used_ids.add(corey_emp.id)
                cand = next_from_deque(q)
                if cand and cand.id not in used_ids:
                    db.session.add(Schedule(date=sat, department_id=dept.id, employee_id=cand.id, override=False))

            elif dept_name == DEPT_AUTO:
                emps = sorted(departments[DEPT_AUTO].employees, key=lambda e: e.id)
                if not emps:
                    continue
                cycle_len = 2  # ON, OFF
                pos = (week_num - 1) % cycle_len
                if pos == 0:
                    on_index = ((week_num - 1) // 2) % len(emps)
                    emp = emps[on_index]
                    db.session.add(Schedule(date=sat, department_id=dept.id, employee_id=emp.id, override=False))

            elif dept_name == DEPT_DAL:
                emps = sorted(departments[DEPT_DAL].employees, key=lambda e: e.id)
                if not emps:
                    continue
                cycle_len = 4  # ON, ON, OFF, OFF
                pos = (week_num - 1) % cycle_len
                if pos in (0, 1):
                    emp = emps[pos % len(emps)]
                    db.session.add(Schedule(date=sat, department_id=dept.id, employee_id=emp.id, override=False))

            elif dept_name == DEPT_COLDEN:
                emps = sorted(departments[DEPT_COLDEN].employees, key=lambda e: e.id)
                if not emps:
                    continue
                cycle_len = 4  # ON, ON, ON, OFF
                pos = (week_num - 1) % cycle_len
                if pos in (0, 1, 2):
                    emp = emps[pos % len(emps)]
                    db.session.add(Schedule(date=sat, department_id=dept.id, employee_id=emp.id, override=False))

            elif dept_name == DEPT_SHOP:
                edwin_exact = next((e for e in departments[DEPT_SHOP].employees if e.name.strip() == "Edwin"), None)
                tommy = next((e for e in departments[DEPT_SHOP].employees if e.name.lower().startswith("tommy")), None)
                emp = next_from_deque(q)
                if emp:
                    db.session.add(Schedule(date=sat, department_id=dept.id, employee_id=emp.id, override=False))
                    if emp.name.strip() == "Edwin" and tommy:
                        exists = Schedule.query.filter_by(
                            date=sat, department_id=dept.id, employee_id=tommy.id
                        ).first()
                        if not exists:
                            db.session.add(Schedule(date=sat, department_id=dept.id, employee_id=tommy.id, override=False))

            else:
                emp = next_from_deque(q)
                if emp:
                    db.session.add(Schedule(date=sat, department_id=dept.id, employee_id=emp.id, override=False))

    db.session.commit()
    return jsonify({
        "message": "🛠️ Schedule repaired and regenerated for future dates.",
        "fixed_departments": list(missing_by_dept.keys()),
        "details": {k: [d.isoformat() for d in v] for k, v in missing_by_dept.items()}
    })





import csv
from werkzeug.utils import secure_filename

@app.route("/schedule/import", methods=["POST"])
def import_schedule():
    """
    Import schedule from uploaded CSV file.
    Expected columns: date, department, employee

    Rules:
      - Accepts MM/DD/YYYY, MM-DD-YYYY, or YYYY-MM-DD
      - Allows multiple employees per (department, date) for Spec Ops, CAR, COL/DEN
      - For all other departments, only one employee per (department, date)
      - Replaces only non-override rows
    """
    import csv
    from werkzeug.utils import secure_filename
    from dateutil import parser

    if "file" not in request.files:
        return jsonify({"error": "CSV file is required"}), 400

    file = request.files["file"]
    filename = secure_filename(file.filename)
    if not filename.lower().endswith(".csv"):
        return jsonify({"error": "File must be a .csv"}), 400

    reader = csv.DictReader(file.stream.read().decode("utf-8").splitlines())
    imported, skipped = 0, []

    multi_allowed = {DEPT_SPEC_OPS, DEPT_CAR, DEPT_COLDEN}  # ✅ these can have multiple employees per date

    for row in reader:
        try:
            raw_date = row["date"].strip()
            dept_name = row["department"].strip()
            emp_name = row["employee"].strip()

            # Parse flexible date
            try:
                d = parser.parse(raw_date, dayfirst=False).date()
            except Exception:
                skipped.append(f"Invalid date format: {raw_date}")
                continue

            dept = Department.query.filter(Department.name.ilike(dept_name)).first()
            if not dept:
                skipped.append(f"Dept not found: {dept_name} ({d})")
                continue

            emp = Employee.query.filter(
                Employee.department_id == dept.id,
                db.func.lower(Employee.name) == emp_name.lower()
            ).first()
            if not emp:
                skipped.append(f"Emp not found: {emp_name} ({d}, {dept_name})")
                continue

            # For single-employee departments, replace any existing one
            if dept.name not in multi_allowed:
                Schedule.query.filter_by(date=d, department_id=dept.id, override=False).delete()

            # For multi-employee departments, avoid duplicates of same person
            else:
                exists = Schedule.query.filter_by(date=d, department_id=dept.id, employee_id=emp.id).first()
                if exists:
                    continue

            db.session.add(Schedule(
                date=d,
                department_id=dept.id,
                employee_id=emp.id,
                override=False
            ))
            imported += 1

        except Exception as e:
            skipped.append(f"Error row {row}: {str(e)}")

    db.session.commit()
    return jsonify({
        "message": f"Imported {imported} rows",
        "skipped": skipped
    })





# ---------- Schedule read / swap / delete ----------
@app.route("/schedule", methods=["GET"])
def get_schedule():
    result = []
    for s in Schedule.query.order_by(Schedule.date, Schedule.department_id, Schedule.id).all():
        result.append({
            "date": s.date.isoformat(),
            "department": s.department.name,
            "employee": s.employee.name,
            "override": s.override
        })
    return jsonify(result)

from flask import Flask, request, jsonify
from models import db, Schedule
from dateutil import parser
import difflib



@app.route("/swap", methods=["POST"])
def swap_shift():
    """
    Swap shifts between two employees on given dates.
    Expects JSON payload:
    {
        "employee1": "Houston",
        "employee2": "Daniel",
        "original_date": "2025-10-11",
        "new_date": "2025-10-25"
    }
    """

    data = request.get_json(silent=True) or request.form.to_dict()

    emp1 = data.get("employee1", "").strip()
    emp2 = data.get("employee2", "").strip()
    orig_date = data.get("original_date", "").strip()
    new_date = data.get("new_date", "").strip()

    if not emp1 or not emp2 or not orig_date or not new_date:
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    # Parse flexible date formats (Zapier often sends MM-DD-YYYY)
    from dateutil import parser
    try:
        orig_date = parser.parse(orig_date).date()
        new_date = parser.parse(new_date).date()
    except Exception:
        return jsonify({"success": False, "message": f"Invalid date format: {orig_date}, {new_date}"}), 400

    orig_schedules = Schedule.query.filter_by(date=orig_date).all()
    new_schedules = Schedule.query.filter_by(date=new_date).all()

    if not orig_schedules or not new_schedules:
        return jsonify({"success": False, "message": "No schedule found for given dates"}), 404

    # --- fuzzy match by employee name ---
    import difflib
    def find_schedule_by_employee(schedules, name):
        names = [s.employee.name for s in schedules]   # ✅ use .name string
        match = difflib.get_close_matches(name, names, n=1, cutoff=0.6)
        if match:
            return next((s for s in schedules if s.employee.name == match[0]), None)
        return None

    sched1 = find_schedule_by_employee(orig_schedules, emp1)
    sched2 = find_schedule_by_employee(new_schedules, emp2)

    if not sched1 or not sched2:
        return jsonify({"success": False, "message": "Could not find employees in given schedules"}), 404

    # --- swap employee assignments ---
    sched1.employee_id, sched2.employee_id = sched2.employee_id, sched1.employee_id
    sched1.override, sched2.override = True, True
    db.session.commit()

    return jsonify({
        "success": True,
        "message": f"Swapped {sched1.employee.name} and {sched2.employee.name} "
                   f"between {orig_date} and {new_date}"
    })




@app.route("/schedule", methods=["DELETE"])
def delete_schedule():
    body = request.get_json(force=True) or {}
    if "all" in body and body["all"]:
        deleted = Schedule.query.delete()
        db.session.commit()
        return jsonify({"message": f"Deleted ALL schedules ({deleted} rows)."}), 200
    if "year" in body:
        y = int(body["year"])
        deleted = Schedule.query.filter(
            Schedule.date >= date(y,1,1),
            Schedule.date <= date(y,12,31)
        ).delete()
        db.session.commit()
        return jsonify({"message": f"Deleted {deleted} schedules from year {y}."}), 200
    if "date" in body:
        d = date.fromisoformat(body["date"])
        deleted = Schedule.query.filter(Schedule.date == d).delete()
        db.session.commit()
        return jsonify({"message": f"Deleted {deleted} schedules on {d}."}), 200
    return jsonify({"error": "Provide 'all', 'year', or 'date'."}), 400

# ---------- Export Excel ----------
@app.route("/schedule/export", methods=["GET"])
def export_excel():
    """
    Excel format:
    - Columns: Department, Employee, then one column per Saturday date
    - Rows: employees
    - Cell = "x" if scheduled that date
    """
    rows = Schedule.query.order_by(Schedule.date, Schedule.department_id, Schedule.id).all()
    dates = sorted({r.date for r in rows})
    depts = Department.query.order_by(Department.id).all()

    # Build matrix: (emp_id, date) → x
    schedmap = defaultdict(set)
    for r in rows:
        schedmap[r.employee_id].add(r.date)

    table = []
    for d in depts:
        for e in sorted(d.employees, key=lambda x: x.id):
            row = {"Department": d.name, "Employee": e.name}
            for dt in dates:
                row[dt.isoformat()] = "x" if dt in schedmap.get(e.id, set()) else ""
            table.append(row)

    # Export with pandas
    import pandas as pd
    df = pd.DataFrame(table, columns=["Department", "Employee"] + [dt.isoformat() for dt in dates])

    from io import BytesIO
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Saturday Schedule")
        ws = writer.sheets["Saturday Schedule"]
        for i, col in enumerate(df.columns):
            width = max(12, min(20, df[col].astype(str).map(len).max() + 2))
            ws.set_column(i, i, width)

    bio.seek(0)
    return send_file(
        bio,
        as_attachment=True,
        download_name=f"Saturday_Schedule_{date.today().year}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ---------- UI ----------
@app.route("/ui")
def ui():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)
