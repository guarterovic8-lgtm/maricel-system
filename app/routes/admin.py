from flask import Blueprint, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import AuditLog, Employee, Role, User
from app.routes.helpers import checkbox, form_action, get_or_404, page, page_number
from app.services.settings import SETTING_DEFINITIONS, get_settings, save_settings
from app.utils.access import audit_event, permission_required
from app.utils.formatting import clean

admin_bp = Blueprint("admin", __name__, url_prefix="/modules")

DUPLICATE_EMPLOYEE = "That employee number, email or username is already in use."
MIN_PASSWORD = 12


def _role(role_id):
    role = db.session.get(Role, role_id) if role_id else None
    if role is None:
        raise ValueError("Select a role for the login account.")
    return role


def _apply_employee_form(employee, form):
    number = clean(form.get("employee_number"), 40)
    first = clean(form.get("first_name"), 80)
    last = clean(form.get("last_name"), 80)
    if not number or not first or not last:
        raise ValueError("Employee number, first name and last name are required.")
    employee.employee_number = number
    employee.first_name = first
    employee.last_name = last
    employee.email = clean(form.get("email"), 254)
    employee.phone = clean(form.get("phone"), 40)
    employee.position = clean(form.get("position"), 100)


def _next_employee_number():
    count = Employee.query.count() + 1
    while Employee.query.filter_by(employee_number=f"EMP-{count:03d}").first():
        count += 1
    return f"EMP-{count:03d}"


def _create_login(employee, form):
    username = clean(form.get("username"), 80)
    password = form.get("password", "")
    if not username:
        raise ValueError("Username is required to allow sign-in.")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"The password must be at least {MIN_PASSWORD} characters.")
    user = User(
        username=username,
        email=employee.email,
        role=_role(form.get("role_id", type=int)),
        employee=employee,
        is_active=employee.status == "active",
    )
    user.set_password(password)
    db.session.add(user)
    return user


@admin_bp.route("/employees", methods=["GET", "POST"])
@login_required
@permission_required("employees.manage")
def employees():
    if request.method == "POST":
        with form_action("Employee added.", DUPLICATE_EMPLOYEE):
            employee = Employee(status="active")
            _apply_employee_form(employee, request.form)
            db.session.add(employee)
            db.session.flush()
            if checkbox("login_enabled"):
                _create_login(employee, request.form)
            audit_event(
                "employee.created",
                "Employee",
                employee.id,
                {"number": employee.employee_number, "login": checkbox("login_enabled")},
            )
        return redirect(url_for("admin.employees"))

    rows = Employee.query.order_by(Employee.status.asc(), Employee.last_name.asc()).all()
    orphan_users = User.query.filter(User.employee_id.is_(None)).order_by(User.username.asc()).all()
    return page(
        "modules/employees.html",
        "employees",
        title="Employees",
        rows=rows,
        orphan_users=orphan_users,
        roles=Role.query.order_by(Role.name.desc()).all(),
        next_number=_next_employee_number(),
        min_password=MIN_PASSWORD,
    )


@admin_bp.post("/employees/<int:employee_id>/edit")
@login_required
@permission_required("employees.manage")
def employee_edit(employee_id):
    employee = get_or_404(Employee, employee_id)
    with form_action("Employee updated.", DUPLICATE_EMPLOYEE):
        _apply_employee_form(employee, request.form)
        user = employee.user
        enabled = checkbox("login_enabled")
        if user is not None:
            is_self = user.id == current_user.id
            username = clean(request.form.get("username"), 80)
            if username:
                user.username = username
            role = _role(request.form.get("role_id", type=int) or user.role_id)
            if is_self and (role.name != "OWNER" or not enabled):
                raise ValueError("You cannot remove your own owner access or disable your own sign-in.")
            user.role = role
            user.email = employee.email
            user.is_active = enabled and employee.status == "active"
            password = request.form.get("password", "")
            if password:
                if len(password) < MIN_PASSWORD:
                    raise ValueError(f"The password must be at least {MIN_PASSWORD} characters.")
                user.set_password(password)
        elif enabled:
            _create_login(employee, request.form)
        audit_event("employee.updated", "Employee", employee.id, {"number": employee.employee_number})
    return redirect(url_for("admin.employees"))


@admin_bp.post("/employees/<int:employee_id>/toggle")
@login_required
@permission_required("employees.manage")
def employee_toggle(employee_id):
    employee = get_or_404(Employee, employee_id)
    with form_action() as result:
        if employee.user is not None and employee.user.id == current_user.id:
            raise ValueError("You cannot deactivate your own account.")
        employee.status = "inactive" if employee.status == "active" else "active"
        if employee.user is not None:
            employee.user.is_active = employee.status == "active"
        audit_event(f"employee.{employee.status}", "Employee", employee.id)
        result.message = f"{employee.first_name} {employee.last_name} is now {employee.status}."
    return redirect(url_for("admin.employees"))


@admin_bp.post("/users/<int:user_id>/reset-password")
@login_required
@permission_required("employees.manage")
def reset_password(user_id):
    user = get_or_404(User, user_id)
    with form_action(f"Password reset for {user.username}."):
        password = request.form.get("password", "")
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"The password must be at least {MIN_PASSWORD} characters.")
        user.set_password(password)
        audit_event("user.password_reset", "User", user.id, {"username": user.username})
    return redirect(url_for("admin.employees"))


@admin_bp.get("/audit-logs")
@login_required
@permission_required("audit.view")
def audit_logs():
    search = request.args.get("q", "").strip()
    user_id = request.args.get("user", type=int)
    query = AuditLog.query.options(joinedload(AuditLog.user))
    if search:
        like = f"%{search}%"
        query = query.filter(or_(AuditLog.action.ilike(like), AuditLog.entity_type.ilike(like)))
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    pager = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).paginate(
        page=page_number(), per_page=40, error_out=False
    )
    return page(
        "modules/audit_logs.html",
        "audit-logs",
        title="Audit Logs",
        pager=pager,
        users=User.query.order_by(User.username.asc()).all(),
        filters={"q": search, "user": user_id},
    )


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@permission_required("settings.manage")
def settings():
    if request.method == "POST":
        with form_action("Settings saved."):
            changed = save_settings(request.form)
            audit_event("settings.updated", "SystemSetting", None, {"changed": sorted(changed)})
        return redirect(url_for("admin.settings"))
    return page(
        "modules/settings.html",
        "settings",
        title="Settings",
        values=get_settings(refresh=True),
        definitions=SETTING_DEFINITIONS,
    )
