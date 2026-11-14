from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Expense, Inventory, InventoryLog, MedicineBatch, Product, Sale, SaleItem
from app.services.inventory import (
    expiring_batches_query,
    low_stock_level,
    sellable_stock_map,
    stock_status,
)
from app.services.settings import setting_decimal
from app.utils.formatting import local_day_bounds, local_today, money, to_local

ZERO = Decimal("0")


def _sales_query(start, end, cashier_id=None):
    query = Sale.query.filter(Sale.status == "completed", Sale.sold_at >= start, Sale.sold_at < end)
    if cashier_id:
        query = query.filter(Sale.cashier_id == cashier_id)
    return query


def _sum_sales(start, end, cashier_id=None):
    query = db.session.query(
        func.coalesce(func.sum(Sale.total_amount), 0), func.count(Sale.id)
    ).filter(Sale.status == "completed", Sale.sold_at >= start, Sale.sold_at < end)
    if cashier_id:
        query = query.filter(Sale.cashier_id == cashier_id)
    total, count = query.one()
    return money(total), int(count or 0)


def daily_sales_series(days=14, cashier_id=None, today=None):
    today = today or local_today()
    first = today - timedelta(days=days - 1)
    start, end = local_day_bounds(first, today)
    buckets = defaultdict(lambda: [ZERO, 0])
    for sold_at, total in (
        _sales_query(start, end, cashier_id).with_entities(Sale.sold_at, Sale.total_amount).all()
    ):
        bucket = buckets[to_local(sold_at).date()]
        bucket[0] += Decimal(total)
        bucket[1] += 1
    series = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        total, count = buckets.get(day, [ZERO, 0])
        series.append(
            {
                "date": day.isoformat(),
                "label": day.strftime("%b %d"),
                "short": day.strftime("%d"),
                "weekday": day.strftime("%a"),
                "value": float(money(total)),
                "count": count,
            }
        )
    return series


def _low_stock(threshold):
    sellable = sellable_stock_map()
    rows = []
    for product in Product.query.filter(Product.is_active.is_(True)).all():
        level = low_stock_level(product, threshold)
        quantity = sellable.get(product.id, ZERO)
        status = stock_status(quantity, level)
        if status != "ok":
            rows.append({"product": product, "quantity": quantity, "level": level, "status": status})
    rows.sort(key=lambda row: (row["quantity"], row["product"].name))
    return rows


def get_dashboard_data(user):
    today = local_today()
    threshold = setting_decimal("low_stock_threshold")
    is_owner = user.has_permission("sales.manage")
    cashier_filter = None if is_owner else user.id

    today_start, today_end = local_day_bounds(today, today)
    week_start, _ = local_day_bounds(today - timedelta(days=6), today)
    month_start, _ = local_day_bounds(today.replace(day=1), today)

    today_sales, today_transactions = _sum_sales(today_start, today_end, cashier_filter)
    week_sales, week_transactions = _sum_sales(week_start, today_end, cashier_filter)
    month_sales, month_transactions = _sum_sales(month_start, today_end, cashier_filter)

    total_quantity = (
        db.session.query(func.coalesce(func.sum(Inventory.quantity), 0))
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.is_active.is_(True))
        .scalar()
    )
    low_stock = _low_stock(threshold)
    expiring_query = expiring_batches_query(today)
    expired_count = (
        MedicineBatch.query.join(Product)
        .filter(MedicineBatch.quantity > 0, MedicineBatch.expiration_date < today, Product.is_active.is_(True))
        .count()
    )

    recent_sales_query = Sale.query.options(joinedload(Sale.cashier), selectinload(Sale.payments))
    if cashier_filter:
        recent_sales_query = recent_sales_query.filter(Sale.cashier_id == cashier_filter)

    data = {
        "is_owner": is_owner,
        "total_products": Product.query.filter_by(is_active=True).count(),
        "total_quantity": Decimal(total_quantity or 0),
        "today_sales": today_sales,
        "today_transactions": today_transactions,
        "week_sales": week_sales,
        "week_transactions": week_transactions,
        "month_sales": month_sales,
        "month_transactions": month_transactions,
        "average_sale": money(month_sales / month_transactions) if month_transactions else Decimal("0.00"),
        "low_stock_count": len(low_stock),
        "low_stock_products": low_stock[:6],
        "expiring_count": expiring_query.count(),
        "expiring_batches": expiring_query.limit(5).all(),
        "expired_count": expired_count,
        "recent_sales": recent_sales_query.order_by(Sale.sold_at.desc()).limit(7).all(),
        "recent_inventory": InventoryLog.query.order_by(InventoryLog.created_at.desc()).limit(7).all(),
        "sales_series": daily_sales_series(14, cashier_filter, today),
    }

    if is_owner:
        month_expenses = (
            db.session.query(func.coalesce(func.sum(Expense.amount), 0))
            .filter(Expense.incurred_at >= month_start, Expense.incurred_at < today_end)
            .scalar()
        )
        month_items = (
            SaleItem.query.join(Sale)
            .options(joinedload(SaleItem.batch), joinedload(SaleItem.product))
            .filter(Sale.status == "completed", Sale.sold_at >= month_start, Sale.sold_at < today_end)
            .all()
        )
        month_tax = (
            db.session.query(func.coalesce(func.sum(Sale.tax_amount), 0))
            .filter(Sale.status == "completed", Sale.sold_at >= month_start, Sale.sold_at < today_end)
            .scalar()
        )
        cogs = sum(
            (Decimal(item.quantity) * Decimal(item.batch.purchase_cost) for item in month_items if item.batch),
            ZERO,
        )
        # Revenue excludes sales tax collected on behalf of the government.
        net_revenue = month_sales - Decimal(month_tax or 0)
        inventory_value = sum(
            (
                Decimal(batch.quantity) * Decimal(batch.purchase_cost)
                for batch in MedicineBatch.query.filter(
                    MedicineBatch.quantity > 0, MedicineBatch.expiration_date >= today
                ).all()
            ),
            ZERO,
        )
        # Top products over the last 30 days, by revenue.
        top_start, _ = local_day_bounds(today - timedelta(days=29), today)
        top_rows = (
            db.session.query(
                Product.name,
                func.coalesce(func.sum(SaleItem.quantity), 0),
                func.coalesce(func.sum(SaleItem.line_total), 0),
            )
            .join(SaleItem, SaleItem.product_id == Product.id)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .filter(Sale.status == "completed", Sale.sold_at >= top_start, Sale.sold_at < today_end)
            .group_by(Product.id, Product.name)
            .order_by(func.sum(SaleItem.line_total).desc())
            .limit(5)
            .all()
        )
        top_max = max((Decimal(row[2]) for row in top_rows), default=ZERO)
        data.update(
            {
                "month_expenses": money(month_expenses),
                "month_gross_profit": money(net_revenue - cogs),
                "month_net_income": money(net_revenue - cogs - Decimal(month_expenses or 0)),
                "inventory_value": money(inventory_value),
                "top_products": [
                    {
                        "name": name,
                        "quantity": Decimal(quantity),
                        "revenue": money(revenue),
                        "share": float(Decimal(revenue) / top_max * 100) if top_max else 0,
                    }
                    for name, quantity, revenue in top_rows
                ],
            }
        )
    return data
