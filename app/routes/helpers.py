from contextlib import contextmanager
from decimal import InvalidOperation
from urllib.parse import urljoin, urlparse

from flask import abort, current_app, flash, redirect, render_template, request
from sqlalchemy.exc import IntegrityError

from app.extensions import db


def page(template, nav, **context):
    return render_template(template, nav=nav, **context)


class ActionResult:
    def __init__(self, message):
        self.message = message
        self.ok = False


@contextmanager
def form_action(success_message=None, duplicate_message=None):
    """Run a form handler in one transaction: commit and flash success, or roll back and flash the error."""
    result = ActionResult(success_message)
    try:
        yield result
        db.session.commit()
        result.ok = True
        if result.message:
            flash(result.message, "success")
    except (ValueError, InvalidOperation) as error:
        db.session.rollback()
        flash(str(error) or "The form contains invalid values.", "error")
    except IntegrityError:
        db.session.rollback()
        current_app.logger.info("Integrity error on %s", request.path, exc_info=True)
        flash(duplicate_message or "A record with the same unique value already exists.", "error")


def get_or_404(model, record_id):
    record = db.session.get(model, record_id)
    if record is None:
        abort(404)
    return record


def page_number():
    page_value = request.args.get("page", 1, type=int) or 1
    return max(page_value, 1)


def query_args(**overrides):
    args = {key: value for key, value in request.args.items() if value not in (None, "")}
    args.update({key: value for key, value in overrides.items()})
    return {key: value for key, value in args.items() if value not in (None, "")}


def checkbox(name):
    return request.form.get(name) in {"on", "1", "true", "yes"}


def _same_site(target):
    if not target:
        return False
    host = urlparse(request.host_url)
    resolved = urlparse(urljoin(request.host_url, target))
    return resolved.scheme in {"http", "https"} and resolved.netloc == host.netloc


def back(default):
    """Redirect to a same-site ``next`` field or the referring page, else ``default``."""
    for target in (request.form.get("next"), request.referrer):
        if _same_site(target):
            return redirect(target)
    return redirect(default)
