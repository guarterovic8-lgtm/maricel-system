import json

from flask import Blueprint, abort, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Category, Customer, Product, Sale, User
from app.routes.helpers import form_action, get_or_404, page, page_number
from app.services.reports import RANGE_PRESETS, resolve_range
from app.services.sales import DISCOUNT_TYPES, PAYMENT_METHODS, create_sale, void_sale
from app.services.inventory import sellable_stock_map
from app.services.settings import get_settings
from app.utils.access import permission_required
from app.utils.formatting import local_day_bounds, parse_decimal

sales_bp = Blueprint("sales", __name__, url_prefix="/modules")


def _pos_catalog():
    stock = sellable_stock_map()
    products = (
        Product.query.options(joinedload(Product.category))
        .filter(Product.is_active.is_(True))
        .order_by(Product.name.asc())
        .all()
    )
    return [
        {
            "id": product.id,
            "name": product.name,
            "generic": product.generic_name or "",
            "sku": product.sku,
            "unit": product.unit,
            "category": product.category.name if product.category else "Uncategorized",
            "categoryId": product.category_id or 0,
            "price": float(product.selling_price or 0),
            "stock": float(stock.get(product.id, 0)),
            "rx": bool(product.requires_prescription),
        }
        for product in products
    ]


@sales_bp.route("/pos", methods=["GET", "POST"])
@login_required
@permission_required("sales.process")
def pos():
    if request.method == "POST":
        with form_action() as result:
            try:
                cart = json.loads(request.form.get("cart") or "[]")
                lines = [(int(item["id"]), item["qty"]) for item in cart]
            except (TypeError, ValueError, KeyError):
                raise ValueError("The cart could not be read. Please try again.") from None
            discount_type = request.form.get("discount_type", "")
            sale = create_sale(
                cashier=current_user,
                lines=lines,
                customer_id=request.form.get("customer_id", type=int),
                discount_type=discount_type,
                discount_value=parse_decimal(request.form.get("discount_value"), "Discount", required=False)
                if discount_type == "custom"
                else None,
                payment_method=request.form.get("payment_method", "cash"),
                amount_tendered=parse_decimal(request.form.get("amount_tendered"), "Cash received", required=False),
                payment_reference=request.form.get("payment_reference"),
            )
            result.message = f"Sale {sale.receipt_number} completed."
        if result.ok:
            return redirect(url_for("sales.receipt", sale_id=sale.id, new=1))
        return redirect(url_for("sales.pos"))

    settings = get_settings()
    return page(
        "modules/pos.html",
        "pos",
        title="Point of Sale",
        catalog=_pos_catalog(),
        categories=Category.query.filter_by(is_active=True).order_by(Category.name.asc()).all(),
        customers=Customer.query.filter_by(is_active=True).order_by(Customer.name.asc()).all(),
        payment_methods=PAYMENT_METHODS,
        discount_types=DISCOUNT_TYPES,
        pos_config={
            "taxRate": float(settings.get("tax_rate") or 0),
            "seniorRate": float(settings.get("senior_discount_rate") or 0),
        },
    )


@sales_bp.get("/sales")
@login_required
@permission_required("sales.process")
def history():
    can_manage = current_user.has_permission("sales.manage")
    preset, start, end = resolve_range(
        request.args.get("range", "30d"), request.args.get("start"), request.args.get("end")
    )
    status = request.args.get("status", "")
    method = request.args.get("method", "")
    cashier_id = request.args.get("cashier", type=int)
    search = request.args.get("q", "").strip()

    start_utc, end_utc = local_day_bounds(start, end)
    query = Sale.query.options(
        joinedload(Sale.cashier), joinedload(Sale.customer), selectinload(Sale.payments)
    ).filter(Sale.sold_at >= start_utc, Sale.sold_at < end_utc)
    if not can_manage:
        query = query.filter(Sale.cashier_id == current_user.id)
    elif cashier_id:
        query = query.filter(Sale.cashier_id == cashier_id)
    if status in {"completed", "voided"}:
        query = query.filter(Sale.status == status)
    if method in PAYMENT_METHODS:
        from app.models import Payment

        query = query.filter(Sale.payments.any(Payment.method == method))
    if search:
        like = f"%{search}%"
        query = query.outerjoin(Customer, Customer.id == Sale.customer_id).filter(
            or_(Sale.receipt_number.ilike(like), Customer.name.ilike(like))
        )

    completed = [s for s in query.with_entities(Sale.total_amount, Sale.status).all() if s.status == "completed"]
    summary = {
        "count": len(completed),
        "total": sum((s.total_amount for s in completed), 0),
    }
    pager = query.order_by(Sale.sold_at.desc(), Sale.id.desc()).paginate(
        page=page_number(), per_page=25, error_out=False
    )
    cashiers = User.query.order_by(User.username.asc()).all() if can_manage else []
    return page(
        "modules/sales.html",
        "sales",
        title="Sales History",
        pager=pager,
        summary=summary,
        can_manage=can_manage,
        cashiers=cashiers,
        presets=RANGE_PRESETS,
        payment_methods=PAYMENT_METHODS,
        filters={
            "range": preset,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "status": status,
            "method": method,
            "cashier": cashier_id,
            "q": search,
        },
    )


def _sale_for_user(sale_id):
    sale = get_or_404(Sale, sale_id)
    if not current_user.has_permission("sales.manage") and sale.cashier_id != current_user.id:
        abort(403)
    return sale


@sales_bp.get("/sales/<int:sale_id>")
@login_required
@permission_required("sales.process")
def receipt(sale_id):
    sale = _sale_for_user(sale_id)
    return page(
        "modules/receipt.html",
        "sales",
        title=f"Receipt {sale.receipt_number}",
        sale=sale,
        settings=get_settings(),
        payment_methods=PAYMENT_METHODS,
        discount_types=DISCOUNT_TYPES,
        is_new=request.args.get("new") == "1",
    )


@sales_bp.post("/sales/<int:sale_id>/void")
@login_required
@permission_required("sales.manage")
def void(sale_id):
    sale = get_or_404(Sale, sale_id)
    with form_action(f"Sale {sale.receipt_number} voided and stock restored."):
        void_sale(sale, user=current_user, reason=request.form.get("reason"))
    return redirect(url_for("sales.receipt", sale_id=sale.id))
