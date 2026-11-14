import pytest

from app import create_app
from app.extensions import db
from app.models import Employee, Role, User
from app.services.bootstrap import seed_roles


@pytest.fixture
def app(tmp_path):
    database_path = tmp_path / "test.db"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-key-not-for-production",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            "WTF_CSRF_ENABLED": False,
            "SESSION_COOKIE_SECURE": False,
        }
    )
    with app.app_context():
        db.create_all()
        seed_roles()
        owner_role = Role.query.filter_by(name="OWNER").one()
        employee_role = Role.query.filter_by(name="CASHIER").one()
        owner = User(username="owner", email="owner@example.test", role=owner_role)
        owner.set_password("Owner-password-123")
        employee_record = Employee(
            employee_number="EMP-001",
            first_name="Test",
            last_name="Employee",
        )
        employee = User(
            username="employee",
            role=employee_role,
            employee=employee_record,
        )
        employee.set_password("Employee-password-123")
        db.session.add_all([owner, employee])
        db.session.commit()
    # Yield outside the app context so every request gets a fresh context (and ``g``), as in production.
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
