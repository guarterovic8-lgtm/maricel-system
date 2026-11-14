from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models import Inventory, InventoryLog, MedicineBatch, Product
from app.models.core import utcnow
from app.services.settings import setting_decimal, setting_int
from app.utils.formatting import local_today

ADJUSTMENT_REASONS = {
    "count_correction": "Physical count correction",
    "damaged": "Damaged / broken",
    "expired": "Expired stock disposal",
    "returned": "Returned to supplier",
    "found": "Found / recovered stock",
}

ZERO = Decimal("0")


def get_inventory(product_id):
    inventory = Inventory.query.filter_by(product_id=product_id).first()
    if inventory is None:
        inventory = Inventory(product_id=product_id, quantity=0)
        db.session.add(inventory)
        db.session.flush()
    return inventory


def low_stock_level(product, threshold=None):
    level = Decimal(product.reorder_level or 0)
    if level > 0:
        return level
    return threshold if threshold is not None else setting_decimal("low_stock_threshold")


def stock_status(quantity, level):
    quantity = Decimal(quantity or 0)
    if quantity <= 0:
        return "out"
    if quantity <= level:
        return "low"
    return "ok"


def sellable_stock_map(on_date=None):
    """Quantity in unexpired batches per product (what the POS may sell)."""
    on_date = on_date or local_today()
    rows = (
        db.session.query(MedicineBatch.product_id, func.coalesce(func.sum(MedicineBatch.quantity), 0))
        .filter(MedicineBatch.quantity > 0, MedicineBatch.expiration_date >= on_date)
        .group_by(MedicineBatch.product_id)
        .all()
    )
    return {product_id: Decimal(quantity) for product_id, quantity in rows}


def expired_stock_map(on_date=None):
    on_date = on_date or local_today()
    rows = (
        db.session.query(MedicineBatch.product_id, func.coalesce(func.sum(MedicineBatch.quantity), 0))
        .filter(MedicineBatch.quantity > 0, MedicineBatch.expiration_date < on_date)
        .group_by(MedicineBatch.product_id)
        .all()
    )
    return {product_id: Decimal(quantity) for product_id, quantity in rows}


def stock_overview(include_inactive=False):
    """Rows for the inventory page: one per product with on-hand, sellable and expired quantities."""
    today = local_today()
    threshold = setting_decimal("low_stock_threshold")
    sellable = sellable_stock_map(today)
    expired = expired_stock_map(today)
    on_hand = {row.product_id: Decimal(row.quantity) for row in Inventory.query.all()}
    query = Product.query
    if not include_inactive:
        query = query.filter(Product.is_active.is_(True))
    rows = []
    for product in query.order_by(Product.name.asc()).all():
        level = low_stock_level(product, threshold)
        available = sellable.get(product.id, ZERO)
        rows.append(
            {
                "product": product,
                "on_hand": on_hand.get(product.id, ZERO),
                "sellable": available,
                "expired": expired.get(product.id, ZERO),
                "level": level,
                "status": stock_status(available, level),
            }
        )
    return rows


def batch_expiry_status(batch, today=None, window=None):
    today = today or local_today()
    window = window if window is not None else setting_int("expiring_within_days")
    days_left = (batch.expiration_date - today).days
    if days_left < 0:
        return "expired", days_left
    if days_left <= window:
        return "expiring", days_left
    return "ok", days_left


def expiring_batches_query(today=None, window=None):
    today = today or local_today()
    window = window if window is not None else setting_int("expiring_within_days")
    return (
        MedicineBatch.query.join(Product)
        .filter(
            MedicineBatch.quantity > 0,
            MedicineBatch.expiration_date >= today,
            MedicineBatch.expiration_date <= today + timedelta(days=window),
            Product.is_active.is_(True),
        )
        .order_by(MedicineBatch.expiration_date.asc())
    )


def receive_stock(
    product,
    quantity,
    *,
    batch_number,
    expiration_date,
    purchase_cost,
    selling_price=None,
    user_id=None,
    note=None,
    action="stock_in",
    purchase_item=None,
    when=None,
):
    """Add stock to a (new or existing) batch, update on-hand inventory and log the movement."""
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise ValueError("Quantity received must be greater than zero.")
    batch_number = (batch_number or "").strip()
    if not batch_number:
        raise ValueError("Batch number is required.")
    if expiration_date is None:
        raise ValueError("Expiration date is required.")
    batch = MedicineBatch.query.filter_by(product_id=product.id, batch_number=batch_number).first()
    price = Decimal(selling_price) if selling_price not in (None, "") else Decimal(product.selling_price or 0)
    if batch:
        if batch.expiration_date != expiration_date:
            raise ValueError(
                f"Batch {batch_number} of {product.name} already exists with a different expiration date."
            )
        batch.quantity = Decimal(batch.quantity) + quantity
        batch.purchase_cost = purchase_cost
        batch.selling_price = price
    else:
        batch = MedicineBatch(
            product_id=product.id,
            purchase_item=purchase_item,
            batch_number=batch_number,
            quantity=quantity,
            expiration_date=expiration_date,
            purchase_cost=purchase_cost,
            selling_price=price,
        )
        db.session.add(batch)
    if when is not None:
        batch.created_at = batch.created_at or when
    if selling_price not in (None, "") and Decimal(selling_price) > 0:
        product.selling_price = Decimal(selling_price)
    inventory = get_inventory(product.id)
    inventory.quantity = Decimal(inventory.quantity) + quantity
    db.session.flush()
    db.session.add(
        InventoryLog(
            product_id=product.id,
            batch_id=batch.id,
            user_id=user_id,
            action=action,
            quantity_change=quantity,
            note=note,
            created_at=when or utcnow(),
        )
    )
    return batch


def adjust_batch(batch, new_quantity, *, reason, note=None, user_id=None, when=None):
    if reason not in ADJUSTMENT_REASONS:
        raise ValueError("Choose a valid adjustment reason.")
    new_quantity = Decimal(new_quantity)
    if new_quantity < 0:
        raise ValueError("Quantity cannot be negative.")
    delta = new_quantity - Decimal(batch.quantity)
    if delta == 0:
        raise ValueError("The new quantity is the same as the current quantity.")
    batch.quantity = new_quantity
    inventory = get_inventory(batch.product_id)
    inventory.quantity = max(ZERO, Decimal(inventory.quantity) + delta)
    db.session.add(
        InventoryLog(
            product_id=batch.product_id,
            batch_id=batch.id,
            user_id=user_id,
            action=f"adjust_{reason}",
            quantity_change=delta,
            note=(note or ADJUSTMENT_REASONS[reason])[:255],
            created_at=when or utcnow(),
        )
    )
    return delta


def allocate_fefo(product_id, quantity, on_date=None):
    """Pick unexpired batches, earliest expiry first, locking them for update on MySQL."""
    on_date = on_date or local_today()
    remaining = Decimal(quantity)
    batches = (
        MedicineBatch.query.filter(
            MedicineBatch.product_id == product_id,
            MedicineBatch.quantity > 0,
            MedicineBatch.expiration_date >= on_date,
        )
        .order_by(MedicineBatch.expiration_date.asc(), MedicineBatch.id.asc())
        .with_for_update()
        .all()
    )
    allocations = []
    for batch in batches:
        if remaining <= 0:
            break
        take = min(Decimal(batch.quantity), remaining)
        allocations.append((batch, take))
        remaining -= take
    if remaining > 0:
        return None
    return allocations
