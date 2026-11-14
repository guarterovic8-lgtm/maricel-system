import uuid
from decimal import Decimal

from app.extensions import db
from app.models import Product, Purchase, PurchaseItem, Supplier
from app.models.core import utcnow
from app.services.inventory import receive_stock
from app.utils.access import audit_event
from app.utils.formatting import money, to_local

PURCHASE_STATUSES = {"ordered": "Ordered", "received": "Received", "cancelled": "Cancelled"}


def create_purchase(*, supplier_id, lines, user, purchased_at=None, notes=None, receive=False, received_at=None):
    """Create a purchase order. ``lines`` are dicts with product_id, quantity, unit_cost and optional
    selling_price, batch_number and expiration_date. When ``receive`` is true the stock is received
    immediately. The caller commits."""
    supplier = db.session.get(Supplier, int(supplier_id)) if supplier_id else None
    if supplier is None:
        raise ValueError("Select a supplier.")
    if supplier.status != "active":
        raise ValueError("The selected supplier is inactive.")
    if not lines:
        raise ValueError("Add at least one item to the purchase.")
    purchased_at = purchased_at or utcnow()

    purchase = Purchase(
        reference=f"TMP-{uuid.uuid4().hex[:20]}",
        supplier_id=supplier.id,
        created_by_id=user.id if user else None,
        status="ordered",
        purchased_at=purchased_at,
        notes=(notes or "").strip() or None,
        total_amount=0,
    )
    db.session.add(purchase)
    db.session.flush()
    purchase.reference = f"PO-{to_local(purchased_at):%Y%m%d}-{purchase.id:04d}"

    total = Decimal("0")
    for line in lines:
        product = db.session.get(Product, int(line["product_id"]))
        if product is None:
            raise ValueError("A purchase line refers to an unknown product.")
        quantity = Decimal(line["quantity"])
        unit_cost = money(line["unit_cost"])
        if quantity <= 0:
            raise ValueError(f"Quantity for {product.name} must be greater than zero.")
        if unit_cost < 0:
            raise ValueError(f"Unit cost for {product.name} cannot be negative.")
        line_total = money(quantity * unit_cost)
        total += line_total
        db.session.add(
            PurchaseItem(
                purchase=purchase,
                product_id=product.id,
                quantity=quantity,
                unit_cost=unit_cost,
                line_total=line_total,
                selling_price=money(line["selling_price"]) if line.get("selling_price") not in (None, "") else None,
                batch_number=(line.get("batch_number") or "").strip() or None,
                expiration_date=line.get("expiration_date"),
            )
        )
    purchase.total_amount = money(total)
    db.session.flush()
    audit_event(
        "purchase.created",
        "Purchase",
        purchase.id,
        {"reference": purchase.reference, "supplier": supplier.name, "total": str(purchase.total_amount)},
        user_id=user.id if user else None,
        created_at=purchased_at,
    )
    if receive:
        receive_purchase(purchase, user=user, when=received_at or purchased_at)
    return purchase


def receive_purchase(purchase, *, user, updates=None, when=None):
    """Receive every line of an ordered purchase into stock. ``updates`` maps item id to a dict of
    batch_number / expiration_date / selling_price captured at delivery time."""
    if purchase.status != "ordered":
        raise ValueError("Only ordered purchases can be received.")
    when = when or utcnow()
    updates = updates or {}
    for item in purchase.items:
        change = updates.get(item.id, {})
        if change.get("batch_number"):
            item.batch_number = change["batch_number"].strip()
        if change.get("expiration_date"):
            item.expiration_date = change["expiration_date"]
        if change.get("selling_price") not in (None, ""):
            item.selling_price = money(change["selling_price"])
        if item.expiration_date is None:
            raise ValueError(f"Enter the expiration date for {item.product.name}.")
        if not item.batch_number:
            item.batch_number = f"{purchase.reference}-{item.id}"
        receive_stock(
            item.product,
            item.quantity,
            batch_number=item.batch_number,
            expiration_date=item.expiration_date,
            purchase_cost=item.unit_cost,
            selling_price=item.selling_price,
            user_id=user.id if user else None,
            note=purchase.reference,
            action="purchase_receive",
            purchase_item=item,
            when=when,
        )
    purchase.status = "received"
    purchase.received_at = when
    audit_event(
        "purchase.received",
        "Purchase",
        purchase.id,
        {"reference": purchase.reference, "items": len(purchase.items)},
        user_id=user.id if user else None,
        created_at=when,
    )


def cancel_purchase(purchase, *, user):
    if purchase.status != "ordered":
        raise ValueError("Only ordered purchases can be cancelled.")
    purchase.status = "cancelled"
    audit_event("purchase.cancelled", "Purchase", purchase.id, {"reference": purchase.reference}, user_id=user.id)
