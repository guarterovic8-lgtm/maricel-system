from app.extensions import db
from app.models import Permission, Role

PERMISSIONS = {
    "dashboard.view": "View the business dashboard",
    "products.manage": "Manage products and categories",
    "inventory.view": "View inventory and medicine batches",
    "inventory.manage": "Receive stock and adjust inventory",
    "suppliers.manage": "Manage suppliers",
    "purchases.manage": "Manage supplier purchases",
    "sales.process": "Process sales at the point of sale",
    "sales.manage": "View all sales and void transactions",
    "customers.view": "View and maintain customer records",
    "expenses.manage": "Manage expenses",
    "reports.view": "View reports",
    "employees.manage": "Manage employee accounts",
    "audit.view": "View audit history",
    "settings.manage": "Manage system settings",
}

CASHIER_PERMISSIONS = (
    "dashboard.view",
    "inventory.view",
    "sales.process",
    "customers.view",
)

ROLE_DESCRIPTIONS = {
    "OWNER": "Full system access",
    "CASHIER": "Point-of-sale, customer service and stock lookup",
}


def seed_roles():
    from app.services.settings import ensure_default_settings

    for code, description in PERMISSIONS.items():
        permission = Permission.query.filter_by(code=code).first()
        if not permission:
            db.session.add(Permission(code=code, description=description))
        elif permission.description != description:
            permission.description = description
    db.session.flush()

    owner = Role.query.filter_by(name="OWNER").first()
    if not owner:
        owner = Role(name="OWNER", description=ROLE_DESCRIPTIONS["OWNER"])
        db.session.add(owner)
    cashier = Role.query.filter_by(name="CASHIER").first()
    if not cashier:
        # Earlier releases called this role EMPLOYEE; rename it in place so existing accounts keep working.
        cashier = Role.query.filter_by(name="EMPLOYEE").first()
        if cashier:
            cashier.name = "CASHIER"
        else:
            cashier = Role(name="CASHIER")
            db.session.add(cashier)
    cashier.description = ROLE_DESCRIPTIONS["CASHIER"]
    db.session.flush()

    permissions = {permission.code: permission for permission in Permission.query.all()}
    owner.permissions = list(permissions.values())
    cashier.permissions = [permissions[code] for code in CASHIER_PERMISSIONS]
    ensure_default_settings()
    db.session.commit()
