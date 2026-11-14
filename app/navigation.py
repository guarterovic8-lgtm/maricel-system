"""Sidebar navigation: (key, label, endpoint, permission, icon) grouped by section."""

NAV_SECTIONS = [
    (
        "Overview",
        [
            ("dashboard", "Dashboard", "main.dashboard", "dashboard.view", "fa-chart-pie"),
        ],
    ),
    (
        "Sales",
        [
            ("pos", "Point of Sale", "sales.pos", "sales.process", "fa-cash-register"),
            ("sales", "Sales History", "sales.history", "sales.process", "fa-receipt"),
            ("customers", "Customers", "customers.index", "customers.view", "fa-users"),
        ],
    ),
    (
        "Inventory",
        [
            ("products", "Products", "catalog.products", "products.manage", "fa-pills"),
            ("categories", "Categories", "catalog.categories", "products.manage", "fa-layer-group"),
            ("inventory", "Stock & Batches", "inventory.index", "inventory.view", "fa-boxes-stacked"),
            ("suppliers", "Suppliers", "purchasing.suppliers", "suppliers.manage", "fa-truck-field"),
            ("purchases", "Purchases", "purchasing.purchases", "purchases.manage", "fa-cart-flatbed"),
        ],
    ),
    (
        "Business",
        [
            ("expenses", "Expenses", "finance.expenses", "expenses.manage", "fa-wallet"),
            ("reports", "Reports", "finance.reports", "reports.view", "fa-chart-line"),
        ],
    ),
    (
        "Administration",
        [
            ("employees", "Employees", "admin.employees", "employees.manage", "fa-user-doctor"),
            ("audit-logs", "Audit Logs", "admin.audit_logs", "audit.view", "fa-clipboard-list"),
            ("settings", "Settings", "admin.settings", "settings.manage", "fa-gear"),
        ],
    ),
]


def visible_navigation(user):
    sections = []
    for title, items in NAV_SECTIONS:
        allowed = [item for item in items if user.has_permission(item[3])]
        if allowed:
            sections.append((title, allowed))
    return sections
