import json
from datetime import timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import (
    AuditLog,
    Customer,
    Employee,
    Expense,
    Inventory,
    MedicineBatch,
    Product,
    Purchase,
    Sale,
    Supplier,
    SystemSetting,
    User,
)
from app.utils.formatting import local_today


def business_today(app):
    with app.app_context():
        return local_today()


def login(client, identity, password):
    return client.post("/auth/login", data={"identity": identity, "password": password}, follow_redirects=True)


@pytest.fixture
def owner(client):
    login(client, "owner", "Owner-password-123")
    return client


@pytest.fixture
def stocked_product(app):
    """A product with two unexpired batches (earlier expiry first) and one expired batch."""
    with app.app_context():
        today = local_today()
        product = Product(sku="PAR-500", name="Paracetamol 500mg", unit="tablet", selling_price=Decimal("5.00"), reorder_level=5)
        db.session.add(product)
        db.session.flush()
        db.session.add(Inventory(product_id=product.id, quantity=35))
        db.session.add_all(
            [
                MedicineBatch(product_id=product.id, batch_number="LATE", quantity=20, expiration_date=today + timedelta(days=400), purchase_cost=2, selling_price=5),
                MedicineBatch(product_id=product.id, batch_number="SOON", quantity=10, expiration_date=today + timedelta(days=30), purchase_cost=2, selling_price=5),
                MedicineBatch(product_id=product.id, batch_number="OLD", quantity=5, expiration_date=today - timedelta(days=1), purchase_cost=2, selling_price=5),
            ]
        )
        db.session.commit()
        return product.id


def checkout(client, product_id, qty, **extra):
    data = {"cart": json.dumps([{"id": product_id, "qty": qty}]), "payment_method": "cash", "amount_tendered": "1000"}
    data.update(extra)
    return client.post("/modules/pos", data=data)


def batch_qty(number):
    return MedicineBatch.query.filter_by(batch_number=number).one().quantity


def test_pos_sale_uses_fefo_and_skips_expired_stock(app, owner, stocked_product):
    response = checkout(owner, stocked_product, 12)
    assert response.status_code == 302 and "/modules/sales/" in response.headers["Location"]
    with app.app_context():
        sale = Sale.query.one()
        assert sale.total_amount == Decimal("60.00")
        assert sale.change_amount == Decimal("940.00")
        assert sale.receipt_number.startswith("OR-")
        assert batch_qty("SOON") == 0
        assert batch_qty("LATE") == 18
        assert batch_qty("OLD") == 5  # expired stock is never sold
        assert Inventory.query.one().quantity == 23
        assert AuditLog.query.filter_by(action="sale.completed").count() == 1
    receipt = owner.get(response.headers["Location"])
    assert b"Paracetamol 500mg" in receipt.data and b"940.00" in receipt.data


def test_pos_rejects_overselling_and_short_cash(app, owner, stocked_product):
    response = checkout(owner, stocked_product, 31)  # only 30 unexpired
    assert "/modules/pos" in response.headers["Location"]
    assert checkout(owner, stocked_product, 2, amount_tendered="5").headers["Location"].endswith("/modules/pos")
    with app.app_context():
        assert Sale.query.count() == 0
        assert batch_qty("SOON") == 10


def test_senior_discount_requires_customer_and_applies_rate(app, owner, stocked_product):
    assert checkout(owner, stocked_product, 10, discount_type="senior").headers["Location"].endswith("/modules/pos")
    with app.app_context():
        customer = Customer(name="Lola Test")
        db.session.add(customer)
        db.session.commit()
        customer_id = customer.id
    checkout(owner, stocked_product, 10, discount_type="senior", customer_id=str(customer_id))
    with app.app_context():
        sale = Sale.query.one()
        assert sale.discount_amount == Decimal("10.00")  # 20% of 50.00
        assert sale.total_amount == Decimal("40.00")


def test_void_restores_stock_and_requires_owner(app, client, stocked_product):
    login(client, "employee", "Employee-password-123")
    checkout(client, stocked_product, 4)
    with app.app_context():
        sale_id = Sale.query.one().id
    assert client.post(f"/modules/sales/{sale_id}/void", data={"reason": "test"}).status_code == 403
    client.post("/auth/logout")
    login(client, "owner", "Owner-password-123")
    client.post(f"/modules/sales/{sale_id}/void", data={"reason": "Wrong item"})
    with app.app_context():
        sale = db.session.get(Sale, sale_id)
        assert sale.status == "voided" and sale.void_reason == "Wrong item"
        assert batch_qty("SOON") == 10
        assert Inventory.query.one().quantity == 35


def test_cashier_sees_only_own_sales(app, client, stocked_product):
    login(client, "owner", "Owner-password-123")
    checkout(client, stocked_product, 1)
    client.post("/auth/logout")
    login(client, "employee", "Employee-password-123")
    with app.app_context():
        owner_sale = Sale.query.one()
        receipt = owner_sale.receipt_number
        sale_id = owner_sale.id
    assert receipt.encode() not in client.get("/modules/sales").data
    assert client.get(f"/modules/sales/{sale_id}").status_code == 403


def test_purchase_order_then_receive_creates_batches(app, owner):
    with app.app_context():
        supplier = Supplier(name="Test Pharma", status="active")
        product = Product(sku="AMX-1", name="Amoxicillin 500mg", unit="capsule", selling_price=0)
        db.session.add_all([supplier, product])
        db.session.commit()
        supplier_id, product_id = supplier.id, product.id
    expiry = (business_today(app) + timedelta(days=365)).isoformat()
    owner.post(
        "/modules/purchases/new",
        data={
            "supplier_id": supplier_id,
            "purchased_at": business_today(app).isoformat(),
            "action": "order",
            "product_id": [str(product_id)],
            "quantity": ["100"],
            "unit_cost": ["4.50"],
            "selling_price": ["9.00"],
            "batch_number": [""],
            "expiration_date": [""],
        },
    )
    with app.app_context():
        purchase = Purchase.query.one()
        assert purchase.status == "ordered" and purchase.total_amount == Decimal("450.00")
        item_id = purchase.items[0].id
        purchase_id = purchase.id
    owner.post(
        f"/modules/purchases/{purchase_id}/receive",
        data={f"batch_number_{item_id}": "AMX2026", f"expiration_date_{item_id}": expiry, f"selling_price_{item_id}": "9.50"},
    )
    with app.app_context():
        purchase = db.session.get(Purchase, purchase_id)
        assert purchase.status == "received"
        assert batch_qty("AMX2026") == 100
        assert Inventory.query.filter_by(product_id=product_id).one().quantity == 100
        assert db.session.get(Product, product_id).selling_price == Decimal("9.50")


def test_stock_in_and_adjustment(app, owner, stocked_product):
    expiry = (business_today(app) + timedelta(days=200)).isoformat()
    owner.post(
        "/modules/inventory/stock-in",
        data={"product_id": stocked_product, "batch_number": "NEW1", "expiration_date": expiry, "quantity": "50", "purchase_cost": "2.10"},
    )
    with app.app_context():
        assert batch_qty("NEW1") == 50
        batch_id = MedicineBatch.query.filter_by(batch_number="OLD").one().id
    owner.post(f"/modules/inventory/batches/{batch_id}/adjust", data={"new_quantity": "0", "reason": "expired"})
    with app.app_context():
        assert batch_qty("OLD") == 0
        assert Inventory.query.filter_by(product_id=stocked_product).one().quantity == 80


def test_product_edit_toggle_and_customer_expense_crud(app, owner, stocked_product):
    owner.post(f"/modules/products/{stocked_product}/edit", data={"name": "Paracetamol 500mg Tab", "sku": "PAR-500", "unit": "tablet", "selling_price": "4.75", "reorder_level": "50"})
    owner.post(f"/modules/products/{stocked_product}/toggle")
    owner.post("/modules/customers", data={"name": "Juan Dela Cruz", "phone": "0917 000 0000"})
    duplicate = owner.post("/modules/customers", data={"name": "Other", "phone": "0917 000 0000"}, follow_redirects=True)
    assert b"already uses that phone" in duplicate.data
    owner.post("/modules/expenses", data={"category": "Rent", "description": "November rent", "amount": "18000", "incurred_at": business_today(app).isoformat()})
    with app.app_context():
        product = db.session.get(Product, stocked_product)
        assert product.name == "Paracetamol 500mg Tab" and product.selling_price == Decimal("4.75") and not product.is_active
        assert Customer.query.count() == 1
        expense_id = Expense.query.one().id
    owner.post(f"/modules/expenses/{expense_id}/delete")
    with app.app_context():
        assert Expense.query.count() == 0


def test_employee_account_lifecycle(app, owner):
    with app.app_context():
        from app.models import Role

        cashier_role = Role.query.filter_by(name="CASHIER").one().id
    owner.post(
        "/modules/employees",
        data={"employee_number": "EMP-900", "first_name": "Rosa", "last_name": "Diaz", "login_enabled": "on", "username": "rosa", "role_id": cashier_role, "password": "Rosa-password-123"},
    )
    with app.app_context():
        employee = Employee.query.filter_by(employee_number="EMP-900").one()
        assert employee.user.username == "rosa"
        employee_id, user_id = employee.id, employee.user.id
    owner.post(f"/modules/employees/{employee_id}/toggle")
    with app.app_context():
        assert not db.session.get(User, user_id).is_active
    other = app.test_client()
    assert b"incorrect" in login(other, "rosa", "Rosa-password-123").data
    owner.post(f"/modules/employees/{employee_id}/toggle")
    owner.post(f"/modules/users/{user_id}/reset-password", data={"password": "Rosa-new-password-1"})
    assert b"Good day" in login(other, "rosa", "Rosa-new-password-1").data


def test_settings_reports_and_password_change(app, owner, stocked_product):
    owner.post("/modules/settings", data={"pharmacy_name": "Maricel Drugstore", "tax_rate": "0", "senior_discount_rate": "20", "low_stock_threshold": "10", "expiring_within_days": "60"})
    with app.app_context():
        assert SystemSetting.query.filter_by(key="pharmacy_name").one().value == "Maricel Drugstore"
    checkout(owner, stocked_product, 3)
    report = owner.get("/modules/reports?range=today")
    assert report.status_code == 200 and b"15.00" in report.data
    csv = owner.get("/modules/reports/sales.csv?range=today")
    assert csv.mimetype == "text/csv" and b"OR-" in csv.data
    bad = owner.post("/account", data={"current_password": "wrong", "new_password": "Brand-new-pass-1", "confirm_password": "Brand-new-pass-1"}, follow_redirects=True)
    assert b"incorrect" in bad.data
    owner.post("/account", data={"current_password": "Owner-password-123", "new_password": "Brand-new-pass-1", "confirm_password": "Brand-new-pass-1"})
    with app.app_context():
        assert User.query.filter_by(username="owner").one().check_password("Brand-new-pass-1")


def test_demo_seed_populates_every_area(app):
    from app.services.demo import seed_demo

    with app.app_context():
        message = seed_demo()
        assert "Demo data loaded" in message
        assert Product.query.count() > 40
        assert Sale.query.filter_by(status="completed").count() > 100
        assert Sale.query.filter_by(status="voided").count() >= 1
        assert Purchase.query.filter_by(status="ordered").count() >= 1
        assert Expense.query.count() > 10
        assert User.query.filter_by(username="cashier").one().role.name == "CASHIER"
        assert "skipped" in seed_demo()
