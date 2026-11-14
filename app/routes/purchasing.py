from datetime import datetime, time, timezone

from flask import Blueprint, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Product, Purchase, Supplier
from app.routes.helpers import form_action, get_or_404, page, page_number
from app.services.purchases import PURCHASE_STATUSES, cancel_purchase, create_purchase, receive_purchase
from app.utils.access import audit_event, permission_required
from app.utils.formatting import MILLI, business_tz, clean, local_today, parse_date, parse_decimal

purchasing_bp = Blueprint("purchasing", __name__, url_prefix="/modules")

DUPLICATE_SUPPLIER = "A supplier with that name already exists."


def _apply_supplier_form(supplier, form):
    name = clean(form.get("name"), 180)
    if not name:
        raise ValueError("Supplier name is required.")
    supplier.name = name
    supplier.contact_person = clean(form.get("contact_person"), 120)
    supplier.email = clean(form.get("email"), 254)
    supplier.phone = clean(form.get("phone"), 40)
    supplier.address = clean(form.get("address"))


@purchasing_bp.route("/suppliers", methods=["GET", "POST"])
@login_required
@permission_required("suppliers.manage")
def suppliers():
    if request.method == "POST":
        with form_action("Supplier added.", DUPLICATE_SUPPLIER):
            supplier = Supplier(status="active")
            _apply_supplier_form(supplier, request.form)
            db.session.add(supplier)
            db.session.flush()
            audit_event("supplier.created", "Supplier", supplier.id, {"name": supplier.name})
        return redirect(url_for("purchasing.suppliers"))

    stats = {
        supplier_id: (count, total)
        for supplier_id, count, total in db.session.query(
            Purchase.supplier_id, func.count(Purchase.id), func.coalesce(func.sum(Purchase.total_amount), 0)
        )
        .filter(Purchase.status == "received")
        .group_by(Purchase.supplier_id)
        .all()
    }
    rows = Supplier.query.order_by(Supplier.status.asc(), Supplier.name.asc()).all()
    return page(
        "modules/suppliers.html",
        "suppliers",
        title="Suppliers",
        rows=[(supplier, *stats.get(supplier.id, (0, 0))) for supplier in rows],
    )


@purchasing_bp.post("/suppliers/<int:supplier_id>/edit")
@login_required
@permission_required("suppliers.manage")
def supplier_edit(supplier_id):
    supplier = get_or_404(Supplier, supplier_id)
    with form_action("Supplier updated.", DUPLICATE_SUPPLIER):
        _apply_supplier_form(supplier, request.form)
        audit_event("supplier.updated", "Supplier", supplier.id, {"name": supplier.name})
    return redirect(url_for("purchasing.suppliers"))


@purchasing_bp.post("/suppliers/<int:supplier_id>/toggle")
@login_required
@permission_required("suppliers.manage")
def supplier_toggle(supplier_id):
    supplier = get_or_404(Supplier, supplier_id)
    with form_action() as result:
        supplier.status = "inactive" if supplier.status == "active" else "active"
        audit_event(f"supplier.{supplier.status}", "Supplier", supplier.id, {"name": supplier.name})
        result.message = f"{supplier.name} marked {supplier.status}."
    return redirect(url_for("purchasing.suppliers"))


@purchasing_bp.get("/purchases")
@login_required
@permission_required("purchases.manage")
def purchases():
    status = request.args.get("status", "")
    search = request.args.get("q", "").strip()
    query = Purchase.query.options(joinedload(Purchase.supplier), joinedload(Purchase.created_by))
    if status in PURCHASE_STATUSES:
        query = query.filter(Purchase.status == status)
    if search:
        like = f"%{search}%"
        query = query.join(Supplier).filter(or_(Purchase.reference.ilike(like), Supplier.name.ilike(like)))
    pager = query.order_by(Purchase.purchased_at.desc(), Purchase.id.desc()).paginate(
        page=page_number(), per_page=30, error_out=False
    )
    totals = dict(
        db.session.query(Purchase.status, func.count(Purchase.id)).group_by(Purchase.status).all()
    )
    return page(
        "modules/purchases.html",
        "purchases",
        title="Purchases",
        pager=pager,
        status=status,
        search=search,
        statuses=PURCHASE_STATUSES,
        totals=totals,
    )


def _purchase_lines(form):
    product_ids = form.getlist("product_id")
    quantities = form.getlist("quantity")
    costs = form.getlist("unit_cost")
    prices = form.getlist("selling_price")
    batches = form.getlist("batch_number")
    expiries = form.getlist("expiration_date")
    lines = []
    for index, raw_product in enumerate(product_ids):
        if not raw_product:
            continue
        product = db.session.get(Product, int(raw_product))
        if product is None:
            raise ValueError("Select a valid product on every line.")
        label = product.name

        def value(values):
            return values[index] if index < len(values) else ""

        lines.append(
            {
                "product_id": product.id,
                "quantity": parse_decimal(value(quantities), f"Quantity for {label}", places=MILLI),
                "unit_cost": parse_decimal(value(costs), f"Unit cost for {label}"),
                "selling_price": parse_decimal(value(prices), f"Selling price for {label}", required=False),
                "batch_number": clean(value(batches), 80),
                "expiration_date": parse_date(value(expiries), f"Expiration date for {label}", required=False),
            }
        )
    if not lines:
        raise ValueError("Add at least one product line.")
    return lines


@purchasing_bp.route("/purchases/new", methods=["GET", "POST"])
@login_required
@permission_required("purchases.manage")
def purchase_new():
    if request.method == "POST":
        receive_now = request.form.get("action") == "receive"
        with form_action(
            "Purchase recorded and stock received." if receive_now else "Purchase order saved."
        ) as result:
            purchase_date = parse_date(request.form.get("purchased_at"), "Purchase date")
            if purchase_date > local_today():
                raise ValueError("The purchase date cannot be in the future.")
            purchased_at = datetime.combine(purchase_date, time(hour=9), tzinfo=business_tz()).astimezone(
                timezone.utc
            )
            purchase = create_purchase(
                supplier_id=request.form.get("supplier_id", type=int),
                lines=_purchase_lines(request.form),
                user=current_user,
                purchased_at=purchased_at,
                notes=request.form.get("notes"),
                receive=receive_now,
                received_at=datetime.now(timezone.utc) if receive_now else None,
            )
        if result.ok:
            return redirect(url_for("purchasing.purchase_detail", purchase_id=purchase.id))
        return redirect(url_for("purchasing.purchase_new"))

    return page(
        "modules/purchase_form.html",
        "purchases",
        title="New purchase",
        suppliers=Supplier.query.filter_by(status="active").order_by(Supplier.name.asc()).all(),
        products=Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all(),
        today_date=local_today(),
    )


@purchasing_bp.get("/purchases/<int:purchase_id>")
@login_required
@permission_required("purchases.manage")
def purchase_detail(purchase_id):
    purchase = get_or_404(Purchase, purchase_id)
    return page(
        "modules/purchase_detail.html",
        "purchases",
        title=f"Purchase {purchase.reference}",
        purchase=purchase,
        statuses=PURCHASE_STATUSES,
    )


@purchasing_bp.post("/purchases/<int:purchase_id>/receive")
@login_required
@permission_required("purchases.manage")
def purchase_receive(purchase_id):
    purchase = get_or_404(Purchase, purchase_id)
    with form_action("Delivery received. Stock levels are updated."):
        updates = {}
        for item in purchase.items:
            updates[item.id] = {
                "batch_number": clean(request.form.get(f"batch_number_{item.id}"), 80),
                "expiration_date": parse_date(
                    request.form.get(f"expiration_date_{item.id}"), f"Expiration date for {item.product.name}"
                ),
                "selling_price": parse_decimal(
                    request.form.get(f"selling_price_{item.id}"), f"Selling price for {item.product.name}",
                    required=False,
                ),
            }
        receive_purchase(purchase, user=current_user, updates=updates)
    return redirect(url_for("purchasing.purchase_detail", purchase_id=purchase.id))


@purchasing_bp.post("/purchases/<int:purchase_id>/cancel")
@login_required
@permission_required("purchases.manage")
def purchase_cancel(purchase_id):
    purchase = get_or_404(Purchase, purchase_id)
    with form_action("Purchase order cancelled."):
        cancel_purchase(purchase, user=current_user)
    return redirect(url_for("purchasing.purchase_detail", purchase_id=purchase.id))
