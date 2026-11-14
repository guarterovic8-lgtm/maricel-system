from flask import Blueprint, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.navigation import visible_navigation
from app.routes.helpers import form_action, page
from app.services.dashboard import get_dashboard_data
from app.utils.access import audit_event, permission_required
from app.utils.formatting import clean

main_bp = Blueprint("main", __name__)


@main_bp.app_context_processor
def inject_navigation():
    if current_user.is_authenticated:
        return {"nav_sections": visible_navigation(current_user)}
    return {"nav_sections": []}


@main_bp.get("/")
@login_required
@permission_required("dashboard.view")
def dashboard():
    return page("dashboard.html", "dashboard", title="Dashboard", data=get_dashboard_data(current_user))


@main_bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        with form_action("Your password has been changed."):
            current = request.form.get("current_password", "")
            new = request.form.get("new_password", "")
            confirm = request.form.get("confirm_password", "")
            if not current_user.check_password(current):
                raise ValueError("Your current password is incorrect.")
            if len(new) < 12:
                raise ValueError("The new password must be at least 12 characters.")
            if new != confirm:
                raise ValueError("The new passwords do not match.")
            if new == current:
                raise ValueError("Choose a password different from your current one.")
            current_user.set_password(new)
            audit_event("user.password_changed", "User", current_user.id)
        return redirect(url_for("main.account"))
    return page("account.html", None, title="My account")


@main_bp.post("/account/profile")
@login_required
def account_profile():
    with form_action("Your contact details have been updated.", "That email address is already in use."):
        email = clean(request.form.get("email"), 254)
        current_user.email = email
        if current_user.employee:
            current_user.employee.phone = clean(request.form.get("phone"), 40)
        audit_event("user.profile_updated", "User", current_user.id)
    return redirect(url_for("main.account"))


@main_bp.get("/health")
def health():
    db.session.execute(db.select(func.now()))
    return {"status": "ok", "database": "connected"}
