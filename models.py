from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, nullable=False)
    employees = db.relationship('Employee', backref='department', lazy=True)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=False)
    # Only used for "Spec Ops" (1..4); nullable for other departments
    group_num = db.Column(db.Integer, nullable=True)

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    override = db.Column(db.Boolean, default=False)

    department = db.relationship('Department')
    employee = db.relationship('Employee')

class Holiday(db.Model):
    date = db.Column(db.Date, primary_key=True)
    note = db.Column(db.String, nullable=True)
