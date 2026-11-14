import uuid
from collections import OrderedDict
from decimal import Decimal

from app.extensions import db
from app.models import Customer, InventoryLog, Payment, Product, Sale, SaleItem
from app.models.core import utcnow
from app.services.inventory import allocate_fefo, get_inventory
from app.services.settings import setting_decimal
from app.utils.access import audit_event
from app.utils.formatting import MILLI, money, to_local

PAYMENT_METHODS = OrderedDict([("cash", "Cash"), ("gcash", "GCash"), ("maya", "Maya"), ("card", "Debit/Credit card")])
DISCOUNT_TYPES = OrderedDict(
    [("", "No discount"), ("senior", "Senior citizen"), ("pwd", "PWD"), ("custom", "Custom amount")]
)


def create_sale(
    *,
    cashier,
    lines,
    customer_id=None,
    discount_type="",
    discount_value=None,
    payment_method="cash",
    amount_tendered=None,
    payment_reference=None,
    sold_at=None,
):
    """Record a completed sale, deducting stock from the earliest-expiring batches.

    ``lines`` is an iterable of (product_id, quantity). Raises ValueError with a
    message suitable for the cashier when the sale cannot be completed. The caller commits.
    """
    sold_at = sold_at or utcnow()
    sale_date = to_local(sold_at).date()

    merged = OrderedDict()
    for product_id, quantity in lines:
        try:
            product_id = int(product_id)
            quantity = Decimal(str(quantity)).quantize(MILLI)
        except Exception:
            raise ValueError("The cart contains an invalid item.") from None
        if quantity <= 0:
            raise ValueError("Item quantities must be greater than zero.")
        merged[product_id] = merged.get(product_id, Decimal("0")) + quantity
    if not merged:
        raise ValueError("Add at least one product to the cart.")

    products = {p.id: p for p in Product.query.filter(Product.id.in_(list(merged))).all()}
    subtotal = Decimal("0")
    for product_id in merged:
        product = products.get(product_id)
        if product is None or not product.is_active:
            raise ValueError("A product in the cart is no longer available.")
        if Decimal(product.selling_price or 0) <= 0:
            raise ValueError(f"{product.name} has no selling price yet.")
        subtotal += money(Decimal(product.selling_price) * merged[product_id])
    subtotal = money(subtotal)

    discount_type = discount_type or ""
    if discount_type not in DISCOUNT_TYPES:
        raise ValueError("Choose a valid discount type.")
    if discount_type in {"senior", "pwd"}:
        discount = money(subtotal * setting_decimal("senior_discount_rate") / 100)
    elif discount_type == "custom":
        discount = money(discount_value or 0)
        if discount < 0 or discount > subtotal:
            raise ValueError("The discount must be between ₱0.00 and the subtotal.")
    else:
        discount = Decimal("0.00")
    if discount_type in {"senior", "pwd"} and not customer_id:
        raise ValueError("Select the senior citizen / PWD customer to apply this discount.")

    tax = money((subtotal - discount) * setting_decimal("tax_rate") / 100)
    total = money(subtotal - discount + tax)

    if payment_method not in PAYMENT_METHODS:
        raise ValueError("Choose a valid payment method.")
    if payment_method == "cash":
        tendered = money(amount_tendered or 0)
        if tendered < total:
            raise ValueError("Cash received is less than the amount due.")
    else:
        tendered = total
    change = money(tendered - total)

    customer = None
    if customer_id:
        customer = db.session.get(Customer, int(customer_id))
        if customer is None or not customer.is_active:
            raise ValueError("The selected customer is not available.")

    sale = Sale(
        receipt_number=f"TMP-{uuid.uuid4().hex[:20]}",
        cashier_id=cashier.id if cashier else None,
        customer_id=customer.id if customer else None,
        status="completed",
        sold_at=sold_at,
        subtotal=subtotal,
        discount_amount=discount,
        discount_type=discount_type or None,
        tax_amount=tax,
        total_amount=total,
        amount_tendered=tendered,
        change_amount=change,
    )
    db.session.add(sale)
    db.session.flush()
    sale.receipt_number = f"OR-{sale_date:%Y%m%d}-{sale.id:05d}"

    for product_id, quantity in merged.items():
        product = products[product_id]
        allocations = allocate_fefo(product_id, quantity, sale_date)
        if allocations is None:
            raise ValueError(f"Not enough unexpired stock for {product.name}.")
        inventory = get_inventory(product_id)
        price = Decimal(product.selling_price)
        for batch, taken in allocations:
            db.session.add(
                SaleItem(
                    sale=sale,
                    product_id=product_id,
                    batch_id=batch.id,
                    quantity=taken,
                    unit_price=price,
                    line_total=money(price * taken),
                )
            )
            batch.quantity = Decimal(batch.quantity) - taken
            inventory.quantity = Decimal(inventory.quantity) - taken
            db.session.add(
                InventoryLog(
                    product_id=product_id,
                    batch_id=batch.id,
                    user_id=sale.cashier_id,
                    action="sale",
                    quantity_change=-taken,
                    note=sale.receipt_number,
                    created_at=sold_at,
                )
            )

    db.session.add(
        Payment(
            sale=sale,
            amount=total,
            method=payment_method,
            reference=(payment_reference or "").strip()[:100] or None,
            paid_at=sold_at,
        )
    )
    audit_event(
        "sale.completed",
        "Sale",
        sale.id,
        {"receipt": sale.receipt_number, "total": str(total), "method": payment_method},
        user_id=sale.cashier_id,
        created_at=sold_at,
    )
    return sale


def void_sale(sale, *, user, reason, when=None):
    if sale.status != "completed":
        raise ValueError("Only completed sales can be voided.")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A reason is required to void a sale.")
    when = when or utcnow()
    for item in sale.items:
        inventory = get_inventory(item.product_id)
        inventory.quantity = Decimal(inventory.quantity) + Decimal(item.quantity)
        if item.batch is not None:
            item.batch.quantity = Decimal(item.batch.quantity) + Decimal(item.quantity)
        db.session.add(
            InventoryLog(
                product_id=item.product_id,
                batch_id=item.batch_id,
                user_id=user.id,
                action="sale_void",
                quantity_change=item.quantity,
                note=f"Void {sale.receipt_number}",
                created_at=when,
            )
        )
    sale.status = "voided"
    sale.voided_at = when
    sale.void_reason = reason[:255]
    audit_event(
        "sale.voided",
        "Sale",
        sale.id,
        {"receipt": sale.receipt_number, "reason": reason[:255]},
        user_id=user.id,
        created_at=when,
    )


def payment_method_label(sale):
    if sale.payments:
        return PAYMENT_METHODS.get(sale.payments[0].method, sale.payments[0].method.title())
    return "—"
