from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import joinedload, selectinload

from app.models import Expense, Purchase, Sale, SaleItem
from app.services.sales import PAYMENT_METHODS
from app.utils.formatting import local_day_bounds, local_today, money, to_local

ZERO = Decimal("0")

RANGE_PRESETS = {
    "today": "Today",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "month": "This month",
    "last_month": "Last month",
    "custom": "Custom range",
}


def resolve_range(preset, start_raw=None, end_raw=None):
    today = local_today()
    preset = preset if preset in RANGE_PRESETS else "month"
    if preset == "today":
        start, end = today, today
    elif preset == "7d":
        start, end = today - timedelta(days=6), today
    elif preset == "30d":
        start, end = today - timedelta(days=29), today
    elif preset == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif preset == "custom":
        try:
            start = date.fromisoformat(start_raw or "")
            end = date.fromisoformat(end_raw or "")
        except ValueError:
            start, end = today.replace(day=1), today
        if start > end:
            start, end = end, start
        if (end - start).days > 366:
            start = end - timedelta(days=366)
    else:
        start, end = today.replace(day=1), today
    return preset, start, end


def sales_in_range(start_date, end_date):
    start, end = local_day_bounds(start_date, end_date)
    return (
        Sale.query.options(
            joinedload(Sale.cashier),
            joinedload(Sale.customer),
            selectinload(Sale.payments),
            selectinload(Sale.items).joinedload(SaleItem.batch),
            selectinload(Sale.items).joinedload(SaleItem.product),
        )
        .filter(Sale.sold_at >= start, Sale.sold_at < end)
        .order_by(Sale.sold_at.asc())
        .all()
    )


def build_report(start_date, end_date):
    start, end = local_day_bounds(start_date, end_date)
    sales = sales_in_range(start_date, end_date)
    completed = [sale for sale in sales if sale.status == "completed"]

    gross_sales = sum((Decimal(s.subtotal) for s in completed), ZERO)
    discounts = sum((Decimal(s.discount_amount) for s in completed), ZERO)
    tax = sum((Decimal(s.tax_amount) for s in completed), ZERO)
    net_sales = gross_sales - discounts
    cogs = ZERO

    products = {}
    daily = defaultdict(lambda: [ZERO, 0])
    methods = defaultdict(lambda: [ZERO, 0])
    cashiers = defaultdict(lambda: [ZERO, 0])
    for sale in completed:
        day = to_local(sale.sold_at).date()
        daily[day][0] += Decimal(sale.total_amount) - Decimal(sale.tax_amount)
        daily[day][1] += 1
        method = sale.payments[0].method if sale.payments else "cash"
        methods[method][0] += Decimal(sale.total_amount)
        methods[method][1] += 1
        name = sale.cashier.display_name if sale.cashier else "Unassigned"
        cashiers[name][0] += Decimal(sale.total_amount)
        cashiers[name][1] += 1
        for item in sale.items:
            cost = Decimal(item.quantity) * Decimal(item.batch.purchase_cost) if item.batch else ZERO
            cogs += cost
            row = products.setdefault(
                item.product_id,
                {"name": item.product.name, "quantity": ZERO, "revenue": ZERO, "cost": ZERO},
            )
            row["quantity"] += Decimal(item.quantity)
            row["revenue"] += Decimal(item.line_total)
            row["cost"] += cost

    expenses = Expense.query.filter(Expense.incurred_at >= start, Expense.incurred_at < end).all()
    expense_total = sum((Decimal(e.amount) for e in expenses), ZERO)
    expense_categories = defaultdict(lambda: ZERO)
    for expense in expenses:
        expense_categories[expense.category] += Decimal(expense.amount)

    purchases = Purchase.query.filter(
        Purchase.status == "received", Purchase.purchased_at >= start, Purchase.purchased_at < end
    ).all()

    gross_profit = net_sales - cogs
    days = []
    cursor = start_date
    while cursor <= end_date:
        total, count = daily.get(cursor, [ZERO, 0])
        days.append(
            {
                "date": cursor.isoformat(),
                "label": cursor.strftime("%b %d"),
                "short": cursor.strftime("%d"),
                "weekday": cursor.strftime("%a"),
                "value": float(money(total)),
                "count": count,
            }
        )
        cursor += timedelta(days=1)

    top_products = sorted(products.values(), key=lambda row: row["revenue"], reverse=True)[:10]
    top_max = top_products[0]["revenue"] if top_products else ZERO
    for row in top_products:
        row["profit"] = row["revenue"] - row["cost"]
        row["share"] = float(row["revenue"] / top_max * 100) if top_max else 0

    total_collected = sum((Decimal(s.total_amount) for s in completed), ZERO)
    return {
        "start": start_date,
        "end": end_date,
        "transactions": len(completed),
        "voided": len(sales) - len(completed),
        "gross_sales": money(gross_sales),
        "discounts": money(discounts),
        "tax": money(tax),
        "net_sales": money(net_sales),
        "total_collected": money(total_collected),
        "average_sale": money(net_sales / len(completed)) if completed else Decimal("0.00"),
        "cogs": money(cogs),
        "gross_profit": money(gross_profit),
        "margin": float(gross_profit / net_sales * 100) if net_sales else 0.0,
        "expenses": money(expense_total),
        "net_income": money(gross_profit - expense_total),
        "purchases_total": money(sum((Decimal(p.total_amount) for p in purchases), ZERO)),
        "purchases_count": len(purchases),
        "days": days,
        "top_products": top_products,
        "payment_methods": sorted(
            (
                {
                    "label": PAYMENT_METHODS.get(method, method.title()),
                    "total": money(total),
                    "count": count,
                    "share": float(total / total_collected * 100) if total_collected else 0,
                }
                for method, (total, count) in methods.items()
            ),
            key=lambda row: row["total"],
            reverse=True,
        ),
        "cashiers": sorted(
            ({"name": name, "total": money(total), "count": count} for name, (total, count) in cashiers.items()),
            key=lambda row: row["total"],
            reverse=True,
        ),
        "expense_categories": sorted(
            ({"category": category, "total": money(total)} for category, total in expense_categories.items()),
            key=lambda row: row["total"],
            reverse=True,
        ),
    }
