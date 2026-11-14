from decimal import Decimal

from flask import current_app, g, has_app_context

from app.extensions import db
from app.models import SystemSetting
from app.utils.formatting import to_decimal

# key: (default value, description, input type)
SETTING_DEFINITIONS = {
    "pharmacy_name": ("Maricel Pharmacy", "Business name shown on receipts and reports", "text"),
    "pharmacy_address": ("", "Store address printed on receipts", "text"),
    "pharmacy_phone": ("", "Contact number printed on receipts", "text"),
    "pharmacy_email": ("", "Contact email", "email"),
    "tin": ("", "Tax identification number (TIN)", "text"),
    "receipt_footer": ("Thank you for your purchase! Get well soon.", "Message printed at the bottom of receipts", "text"),
    "tax_rate": ("0", "Sales tax added at checkout (%). Use 0 when shelf prices already include VAT.", "number"),
    "senior_discount_rate": ("20", "Senior citizen / PWD discount (%)", "number"),
    "low_stock_threshold": (None, "Default low-stock level for products without a reorder level", "number"),
    "expiring_within_days": (None, "Days before expiration to flag medicine batches as expiring", "number"),
}

NUMERIC_SETTINGS = {"tax_rate", "senior_discount_rate", "low_stock_threshold", "expiring_within_days"}


def _defaults():
    values = {key: default for key, (default, _, _) in SETTING_DEFINITIONS.items()}
    if has_app_context():
        values["low_stock_threshold"] = str(current_app.config["LOW_STOCK_THRESHOLD"])
        values["expiring_within_days"] = str(current_app.config["EXPIRING_WITHIN_DAYS"])
    return values


def ensure_default_settings():
    existing = {row.key for row in SystemSetting.query.all()}
    defaults = _defaults()
    for key, (_, description, _) in SETTING_DEFINITIONS.items():
        if key not in existing:
            db.session.add(SystemSetting(key=key, value=defaults[key], description=description))


def get_settings(refresh=False):
    cache = g.get("_settings") if has_app_context() else None
    if cache is not None and not refresh:
        return cache
    values = _defaults()
    for row in SystemSetting.query.all():
        if row.value is not None and row.value != "":
            values[row.key] = row.value
    if has_app_context():
        g._settings = values
    return values


def setting_decimal(key):
    return to_decimal(get_settings().get(key), Decimal("0"))


def setting_int(key):
    try:
        return int(Decimal(str(get_settings().get(key) or 0)))
    except Exception:
        return 0


def save_settings(form_values):
    rows = {row.key: row for row in SystemSetting.query.all()}
    changed = {}
    for key, (_, description, _) in SETTING_DEFINITIONS.items():
        if key not in form_values:
            continue
        value = (form_values.get(key) or "").strip()
        if key in NUMERIC_SETTINGS:
            number = to_decimal(value, None)
            if number is None or number < 0:
                raise ValueError(f"{description.split('(')[0].strip()} must be a non-negative number.")
            if key in {"tax_rate", "senior_discount_rate"} and number > 100:
                raise ValueError("Percentages cannot exceed 100.")
            value = format(number.normalize(), "f")
        row = rows.get(key)
        if row is None:
            row = SystemSetting(key=key, description=description)
            db.session.add(row)
        if row.value != value:
            changed[key] = value
        row.value = value
    g.pop("_settings", None)
    return changed
