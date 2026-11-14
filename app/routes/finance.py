import csv
import io
from datetime import datetime, time, timedelta, timezone

from flask import Blueprint, Response, redirect, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.models import Expense
from app.routes.helpers import form_action, get_or_404, page
from app.services.reports import RANGE_PRESETS, build_report, resolve_range, sales_in_range
from app.services.sales import PAYMENT_METHODS
from app.utils.access import audit_event, permission_required
from app.utils.formatting import business_tz, clean, local_day_bounds, local_today, parse_date, parse_decimal, to_local

finance_bp = Blueprint("finance", __name__, url_prefix="/modules")

EXPENSE_CATEGORIES = (
    "Rent",
    "Utilities",
    "Salaries & Wages",
    "Supplies",
    "Maintenance & Repairs",
    "Taxes & Licenses",
    "Delivery & Transport",
    "Marketing",
    "Miscellaneous",
)


def _apply_expense_form(expense, form):
    category = clean(form.get("category"), 100)
    description = clean(form.get("description"), 255)
    if not category or not description:
        raise ValueError("Category and description are required.")
    amount = parse_decimal(form.get("amount"), "Amount")
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    incurred = parse_date(form.get("incurred_at"), "Date")
    if incurred > local_today():
        raise ValueError("The expense date cannot be in the future.")
    expense.category = category
    expense.description = description
    expense.amount = amount
    expense.incurred_at = datetime.combine(incurred, time(hour=12), tzinfo=business_tz()).astimezone(timezone.utc)


def _month_bounds(month_raw):
    today = local_today()
    try:
        first = datetime.strptime(month_raw or "", "%Y-%m").date()
    except ValueError:
        first = today.replace(day=1)
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, next_month - timedelta(days=1)


@finance_bp.route("/expenses", methods=["GET", "POST"])
@login_required
@permission_required("expenses.manage")
def expenses():
    if request.method == "POST":
        with form_action("Expense recorded."):
            expense = Expense(created_by_id=current_user.id)
            _apply_expense_form(expense, request.form)
            db.session.add(expense)
            db.session.flush()
            audit_event(
                "expense.created", "Expense", expense.id, {"category": expense.category, "amount": str(expense.amount)}
            )
        return redirect(url_for("finance.expenses", month=request.args.get("month")))

    first, last = _month_bounds(request.args.get("month"))
    category = request.args.get("category", "")
    start, end = local_day_bounds(first, last)
    query = Expense.query.filter(Expense.incurred_at >= start, Expense.incurred_at < end)
    if category:
        query = query.filter(Expense.category == category)
    rows = query.order_by(Expense.incurred_at.desc(), Expense.id.desc()).all()
    by_category = (
        db.session.query(Expense.category, func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.incurred_at >= start, Expense.incurred_at < end)
        .group_by(Expense.category)
        .order_by(func.sum(Expense.amount).desc())
        .all()
    )
    month_total = sum((amount for _, amount in by_category), 0)
    previous = (first - timedelta(days=1)).replace(day=1)
    following = last + timedelta(days=1)
    return page(
        "modules/expenses.html",
        "expenses",
        title="Expenses",
        rows=rows,
        by_category=by_category,
        month_total=month_total,
        month=first,
        previous_month=previous.strftime("%Y-%m"),
        next_month=following.strftime("%Y-%m") if following <= local_today() else None,
        category=category,
        categories=EXPENSE_CATEGORIES,
        today_date=local_today(),
    )


@finance_bp.post("/expenses/<int:expense_id>/edit")
@login_required
@permission_required("expenses.manage")
def expense_edit(expense_id):
    expense = get_or_404(Expense, expense_id)
    with form_action("Expense updated."):
        _apply_expense_form(expense, request.form)
        audit_event("expense.updated", "Expense", expense.id, {"amount": str(expense.amount)})
    return redirect(url_for("finance.expenses", month=to_local(expense.incurred_at).strftime("%Y-%m")))


@finance_bp.post("/expenses/<int:expense_id>/delete")
@login_required
@permission_required("expenses.manage")
def expense_delete(expense_id):
    expense = get_or_404(Expense, expense_id)
    month = to_local(expense.incurred_at).strftime("%Y-%m")
    with form_action("Expense deleted."):
        audit_event(
            "expense.deleted",
            "Expense",
            expense.id,
            {"category": expense.category, "description": expense.description, "amount": str(expense.amount)},
        )
        db.session.delete(expense)
    return redirect(url_for("finance.expenses", month=month))


@finance_bp.get("/reports")
@login_required
@permission_required("reports.view")
def reports():
    preset, start, end = resolve_range(
        request.args.get("range", "month"), request.args.get("start"), request.args.get("end")
    )
    return page(
        "modules/reports.html",
        "reports",
        title="Reports",
        report=build_report(start, end),
        presets=RANGE_PRESETS,
        preset=preset,
    )


@finance_bp.get("/reports/sales.csv")
@login_required
@permission_required("reports.view")
def reports_csv():
    _, start, end = resolve_range(request.args.get("range", "month"), request.args.get("start"), request.args.get("end"))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["Receipt", "Date", "Cashier", "Customer", "Status", "Payment", "Subtotal", "Discount", "Tax", "Total"]
    )
    for sale in sales_in_range(start, end):
        method = sale.payments[0].method if sale.payments else ""
        writer.writerow(
            [
                sale.receipt_number,
                to_local(sale.sold_at).strftime("%Y-%m-%d %H:%M"),
                sale.cashier.display_name if sale.cashier else "",
                sale.customer.name if sale.customer else "Walk-in",
                sale.status,
                PAYMENT_METHODS.get(method, method),
                f"{sale.subtotal:.2f}",
                f"{sale.discount_amount:.2f}",
                f"{sale.tax_amount:.2f}",
                f"{sale.total_amount:.2f}",
            ]
        )
    filename = f"maricel-sales-{start.isoformat()}-to-{end.isoformat()}.csv"
    return Response(
        "﻿" + buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

