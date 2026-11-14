from flask import Blueprint, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import InventoryLog, MedicineBatch, Product
from app.routes.helpers import back, form_action, get_or_404, page, page_number
from app.services.inventory import (
    ADJUSTMENT_REASONS,
    adjust_batch,
    batch_expiry_status,
    receive_stock,
    stock_overview,
)
from app.services.settings import setting_int
from app.utils.access import audit_event, permission_required
from app.utils.formatting import MILLI, local_today, parse_date, parse_decimal

inventory_bp = Blueprint("inventory", __name__, url_prefix="/modules/inventory")

TABS = ("stock", "batches", "movements")


@inventory_bp.get("")
@login_required
@permission_required("inventory.view")
def index():
    tab = request.args.get("tab", "stock")
    tab = tab if tab in TABS else "stock"
    status = request.args.get("status", "all")
    search = request.args.get("q", "").strip().lower()
    today = local_today()
    window = setting_int("expiring_within_days")

    overview = stock_overview()
    summary = {
        "products": len(overview),
        "low": sum(1 for row in overview if row["status"] == "low"),
        "out": sum(1 for row in overview if row["status"] == "out"),
    }
    context = {"tab": tab, "status": status, "search": search, "summary": summary, "window": window}

    batch_rows = [
        (batch, *batch_expiry_status(batch, today, window))
        for batch in MedicineBatch.query.options(joinedload(MedicineBatch.product))
        .filter(MedicineBatch.quantity > 0)
        .order_by(MedicineBatch.expiration_date.asc())
        .all()
    ]
    summary["expiring"] = sum(1 for _, state, _ in batch_rows if state == "expiring")
    summary["expired"] = sum(1 for _, state, _ in batch_rows if state == "expired")

    if tab == "stock":
        rows = overview
        if status in {"low", "out"}:
            rows = [row for row in rows if row["status"] == status]
        if search:
            rows = [
                row
                for row in rows
                if search in row["product"].name.lower()
                or search in row["product"].sku.lower()
                or search in (row["product"].generic_name or "").lower()
            ]
        context["rows"] = rows
    elif tab == "batches":
        rows = batch_rows
        if status in {"expiring", "expired"}:
            rows = [row for row in rows if row[1] == status]
        if search:
            rows = [
                row
                for row in rows
                if search in row[0].product.name.lower() or search in row[0].batch_number.lower()
            ]
        context["rows"] = rows
    else:
        query = InventoryLog.query.options(joinedload(InventoryLog.product), joinedload(InventoryLog.user))
        if status == "in":
            query = query.filter(InventoryLog.quantity_change > 0)
        elif status == "out":
            query = query.filter(InventoryLog.quantity_change < 0)
        if search:
            like = f"%{search}%"
            query = query.outerjoin(Product, Product.id == InventoryLog.product_id).filter(
                or_(Product.name.ilike(like), InventoryLog.note.ilike(like), InventoryLog.action.ilike(like))
            )
        context["pager"] = query.order_by(InventoryLog.created_at.desc(), InventoryLog.id.desc()).paginate(
            page=page_number(), per_page=50, error_out=False
        )

    if current_user.has_permission("inventory.manage"):
        context["products"] = Product.query.filter_by(is_active=True).order_by(Product.name.asc()).all()
        context["reasons"] = ADJUSTMENT_REASONS
    return page("modules/inventory.html", "inventory", title="Stock & Batches", **context)


@inventory_bp.post("/stock-in")
@login_required
@permission_required("inventory.manage")
def stock_in():
    with form_action("Stock received and added to inventory."):
        product = db.session.get(Product, request.form.get("product_id", type=int) or 0)
        if product is None:
            raise ValueError("Select a product.")
        quantity = parse_decimal(request.form.get("quantity"), "Quantity", places=MILLI)
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        expiration = parse_date(request.form.get("expiration_date"), "Expiration date")
        if expiration < local_today():
            raise ValueError("You cannot receive stock that has already expired.")
        batch = receive_stock(
            product,
            quantity,
            batch_number=request.form.get("batch_number"),
            expiration_date=expiration,
            purchase_cost=parse_decimal(request.form.get("purchase_cost"), "Unit cost"),
            selling_price=parse_decimal(request.form.get("selling_price"), "Selling price", required=False),
            user_id=current_user.id,
            note=(request.form.get("note") or "Direct stock-in").strip()[:255],
        )
        audit_event(
            "inventory.stock_in",
            "MedicineBatch",
            batch.id,
            {"product": product.name, "batch": batch.batch_number, "quantity": str(quantity)},
        )
    return redirect(url_for("inventory.index", tab="batches"))


@inventory_bp.post("/batches/<int:batch_id>/adjust")
@login_required
@permission_required("inventory.manage")
def adjust(batch_id):
    batch = get_or_404(MedicineBatch, batch_id)
    with form_action("Batch quantity adjusted."):
        new_quantity = parse_decimal(request.form.get("new_quantity"), "New quantity", places=MILLI)
        reason = request.form.get("reason", "")
        delta = adjust_batch(
            batch, new_quantity, reason=reason, note=(request.form.get("note") or "").strip(), user_id=current_user.id
        )
        audit_event(
            "inventory.adjusted",
            "MedicineBatch",
            batch.id,
            {"product": batch.product.name, "batch": batch.batch_number, "change": str(delta), "reason": reason},
        )
    return back(url_for("inventory.index", tab="batches"))
