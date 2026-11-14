from functools import wraps

from flask import abort, has_request_context, redirect, request, url_for
from flask_login import current_user


def permission_required(permission):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.full_path))
            if not current_user.has_permission(permission):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def audit_event(action, entity_type=None, entity_id=None, details=None, *, user_id=None, created_at=None):
    """Stage an audit-log row in the current transaction.

    The caller owns the transaction and commits it, so the audit entry is saved
    atomically with the change it describes (or rolled back together with it).
    """
    from app.extensions import db
    from app.models import AuditLog
    from app.models.core import utcnow

    in_request = has_request_context()
    if user_id is None and in_request and current_user.is_authenticated:
        user_id = current_user.id
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
        ip_address=request.remote_addr if in_request else None,
        created_at=created_at or utcnow(),
    )
    db.session.add(entry)
    return entry
