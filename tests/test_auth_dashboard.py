from app.extensions import db
from app.models import Category, Inventory, Product, Role, User


def login(client, identity, password):
    return client.post(
        "/auth/login",
        data={"identity": identity, "password": password},
        follow_redirects=True,
    )


def test_login_logout_and_protected_dashboard(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]

    response = login(client, "owner", "Owner-password-123")
    assert response.status_code == 200
    assert b"Active products" in response.data
    assert client.post("/auth/logout").status_code == 302


def test_wrong_password_is_rejected(client):
    response = client.post(
        "/auth/login",
        data={"identity": "owner", "password": "wrong-password"},
    )
    assert response.status_code == 200
    assert b"incorrect" in response.data
    assert client.get("/", follow_redirects=False).status_code == 302


def test_login_requires_csrf_token(app):
    app.config["WTF_CSRF_ENABLED"] = True
    response = app.test_client().post(
        "/auth/login",
        data={"identity": "owner", "password": "Owner-password-123"},
    )
    assert response.status_code == 400


def test_static_pharmacy_favicon_is_served(client):
    response = client.get("/static/images/favicon.svg")
    assert response.status_code == 200
    assert b"<svg" in response.data


def test_employee_can_access_sales_but_not_owner_settings(client):
    login(client, "employee", "Employee-password-123")
    assert client.get("/modules/sales").status_code == 200
    assert client.get("/modules/settings").status_code == 403
    assert client.get("/modules/employees").status_code == 403


def test_dashboard_uses_database_product_and_inventory_values(app, client):
    with app.app_context():
        category = Category(name="Analgesics")
        db.session.add(category)
        db.session.flush()
        product = Product(sku="MED-001", name="Example medicine", category=category, reorder_level=5)
        db.session.add(product)
        db.session.flush()
        db.session.add(Inventory(product_id=product.id, quantity=3))
        db.session.commit()

    login(client, "owner", "Owner-password-123")
    response = client.get("/")
    assert b"Example medicine" in response.data  # listed under stock alerts
    assert b"Low stock products" in response.data
    assert b">1</div>" in response.data
    assert b">3</div>" in response.data


def test_employee_password_is_hashed(app):
    with app.app_context():
        employee = User.query.filter_by(username="employee").one()
        assert employee.password_hash != "Employee-password-123"
        assert employee.check_password("Employee-password-123")


def test_owner_can_create_category_and_product(client):
    login(client, "owner", "Owner-password-123")

    category_response = client.post(
        "/modules/categories",
        data={"name": "First Aid", "description": "First-aid supplies"},
        follow_redirects=True,
    )
    assert category_response.status_code == 200
    assert b"Category created." in category_response.data

    with client.application.app_context():
        category = Category.query.filter_by(name="First Aid").one()
        category_id = category.id

    product_response = client.post(
        "/modules/products",
        data={
            "name": "Sterile gauze",
            "sku": "GAUZE-001",
            "category_id": str(category_id),
            "reorder_level": "5",
        },
        follow_redirects=True,
    )
    assert product_response.status_code == 200
    assert b"Sterile gauze" in product_response.data
