from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import current_app

CENT = Decimal("0.01")
MILLI = Decimal("0.001")


def business_tz():
    return ZoneInfo(current_app.config["BUSINESS_TIMEZONE"])


def local_now():
    return datetime.now(business_tz())


def local_today():
    return local_now().date()


def to_local(value):
    """Convert a stored timestamp (naive values are UTC) to the business timezone."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(business_tz())
    return value


def local_day_bounds(start_date, end_date):
    """Return UTC [start, end) bounds covering local calendar dates start_date..end_date inclusive."""
    tz = business_tz()
    start = datetime.combine(start_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    return start, end


def money(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def to_decimal(value, default=Decimal("0")):
    try:
        return Decimal(str(value)) if value not in (None, "") else default
    except (InvalidOperation, ValueError):
        return default


def parse_decimal(raw, label, *, minimum=Decimal("0"), required=True, places=CENT, maximum=None):
    raw = (raw or "").strip() if isinstance(raw, str) else raw
    if raw in (None, ""):
        if required:
            raise ValueError(f"{label} is required.")
        return None
    try:
        value = Decimal(str(raw).replace(",", ""))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} must be a number.") from None
    if not value.is_finite():
        raise ValueError(f"{label} must be a number.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} cannot be less than {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} cannot be more than {maximum}.")
    return value.quantize(places, rounding=ROUND_HALF_UP)


def parse_date(raw, label, *, required=True):
    raw = (raw or "").strip()
    if not raw:
        if required:
            raise ValueError(f"{label} is required.")
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{label} must be a valid date (YYYY-MM-DD).") from None


def clean(value, max_length=None):
    value = (value or "").strip()
    if max_length:
        value = value[:max_length]
    return value or None


def format_peso(value):
    return f"₱{money(value):,.2f}"


def format_qty(value):
    number = to_decimal(value)
    if number == number.to_integral_value():
        return f"{int(number):,}"
    return f"{number.quantize(MILLI).normalize():,f}"


def format_local(value, fmt="%b %d, %Y %I:%M %p"):
    if value is None:
        return "—"
    local = to_local(value)
    return local.strftime(fmt)
