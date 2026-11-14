from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import or_

from app.extensions import db
from app.models import AuditLog, User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _is_safe_redirect(target):
    if not target:
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in {"http", "https"} and host_url.netloc == redirect_url.netloc


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        identity = request.form.get("identity", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter(or_(User.username == identity, User.email == identity)).first()
        if user and user.is_active and user.check_password(password):
            login_user(user, remember=False, fresh=True)
            user.last_login_at = datetime.now(timezone.utc)
            db.session.add(
                AuditLog(
                    user_id=user.id,
                    action="auth.login",
                    ip_address=request.remote_addr,
                )
            )
            db.session.commit()
            next_url = request.args.get("next")
            return redirect(next_url if _is_safe_redirect(next_url) else url_for("main.dashboard"))
        current_app.logger.warning("Rejected sign-in attempt for identity %s", identity[:80])
        flash("The username/email or password is incorrect.", "error")
    return render_template("auth/login.html")


@auth_bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        db.session.add(
            AuditLog(
                user_id=current_user.id,
                action="auth.logout",
                ip_address=request.remote_addr,
            )
        )
        db.session.commit()
        logout_user()
    return redirect(url_for("auth.login"))
