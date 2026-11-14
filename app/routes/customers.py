from flask import Blueprint, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Customer, Sale
from app.routes.helpers import back, form_action, get_or_404, page, page_number
from app.utils.access import audit_event, permission_required
from app.utils.formatting import clean

customers_bp = Blueprint("customers", __name__, url_prefix="/modules/customers")

DUPLICATE_CUSTOMER = "Another customer already uses that phone number or email."


def _apply_customer_form(customer, form):
    name = clean(form.get("name"), 180)
    if not name:
        raise ValueError("Customer name is required.")
    customer.name = name
    customer.phone = clean(form.get("phone"), 40)
    customer.email = clean(form.get("email"), 254)
    customer.notes = clean(form.get("notes"))


@customers_bp.route("", methods=["GET", "POST"])
@login_required
@permission_required("customers.view")
def index():
    if request.method == "POST":
        with form_action("Customer added.", DUPLICATE_CUSTOMER):
            customer = Customer(is_active=True)
            _apply_customer_form(customer, request.form)
            db.session.add(customer)
            db.session.flush()
            audit_event("customer.created", "Customer", customer.id, {"name": customer.name})
        return back(url_for("customers.index"))

    search = request.args.get("q", "").strip()
    status = request.args.get("status", "active")
    query = Customer.query
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Customer.name.ilike(like), Customer.phone.ilike(like), Customer.email.ilike(like)))
    if status == "active":
        query = query.filter(Customer.is_active.is_(True))
    elif status == "inactive":
        query = query.filter(Customer.is_active.is_(False))
    pager = query.order_by(Customer.name.asc()).paginate(page=page_number(), per_page=30, error_out=False)
    ids = [customer.id for customer in pager.items]
    stats = {}
    if ids:
        stats = {
            customer_id: (count, total, last)
            for customer_id, count, total, last in db.session.query(
                Sale.customer_id,
                func.count(Sale.id),
                func.coalesce(func.sum(Sale.total_amount), 0),
                func.max(Sale.sold_at),
            )
            .filter(Sale.customer_id.in_(ids), Sale.status == "completed")
            .group_by(Sale.customer_id)
            .all()
        }
    return page(
        "modules/customers.html",
        "customers",
        title="Customers",
        pager=pager,
        stats=stats,
        filters={"q": search, "status": status},
    )


@customers_bp.get("/<int:customer_id>")
@login_required
@permission_required("customers.view")
def detail(customer_id):
    customer = get_or_404(Customer, customer_id)
    query = customer.sales.options(joinedload(Sale.cashier), selectinload(Sale.payments))
    if not current_user.has_permission("sales.manage"):
        visible = query.filter(Sale.cashier_id == current_user.id)
    else:
        visible = query
    completed = customer.sales.filter(Sale.status == "completed")
    return page(
        "modules/customer_detail.html",
        "customers",
        title=customer.name,
        customer=customer,
        sales=visible.order_by(Sale.sold_at.desc()).limit(50).all(),
        visit_count=completed.count(),
        lifetime_total=db.session.query(func.coalesce(func.sum(Sale.total_amount), 0))
        .filter(Sale.customer_id == customer.id, Sale.status == "completed")
        .scalar(),
    )


@customers_bp.post("/<int:customer_id>/edit")
@login_required
@permission_required("customers.view")
def edit(customer_id):
    customer = get_or_404(Customer, customer_id)
    with form_action("Customer updated.", DUPLICATE_CUSTOMER):
        _apply_customer_form(customer, request.form)
        audit_event("customer.updated", "Customer", customer.id, {"name": customer.name})
    return back(url_for("customers.index"))


@customers_bp.post("/<int:customer_id>/toggle")
@login_required
@permission_required("customers.view")
def toggle(customer_id):
    customer = get_or_404(Customer, customer_id)
    with form_action() as result:
        customer.is_active = not customer.is_active
        state = "activated" if customer.is_active else "deactivated"
        audit_event(f"customer.{state}", "Customer", customer.id)
        result.message = f"{customer.name} {state}."
    return back(url_for("customers.index"))
