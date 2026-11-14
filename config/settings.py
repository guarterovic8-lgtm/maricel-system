import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _bool(name, default="false"):
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def normalize_database_url(url):
    """Accept provider URLs (e.g. Railway's ``mysql://``) and select the PyMySQL driver."""
    if not url:
        return url
    if url.startswith("mysql://"):
        url = "mysql+pymysql://" + url[len("mysql://"):]
    if url.startswith("mysql+pymysql://") and "charset=" not in url:
        url += ("&" if "?" in url else "?") + "charset=utf8mb4"
    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = normalize_database_url(
        os.getenv("DATABASE_URL")
        or os.getenv("MYSQL_URL")
        or "mysql+pymysql://localhost/maricel_pharmacy_db?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE")
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8
    WTF_CSRF_TIME_LIMIT = 60 * 60
    LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "10"))
    EXPIRING_WITHIN_DAYS = int(os.getenv("EXPIRING_WITHIN_DAYS", "90"))
    BUSINESS_TIMEZONE = os.getenv("BUSINESS_TIMEZONE", "Asia/Manila")
    # Set when the app runs behind a reverse proxy (Railway, Render, Nginx) so client IPs,
    # scheme and host come from the X-Forwarded-* headers.
    TRUST_PROXY = _bool("TRUST_PROXY")
