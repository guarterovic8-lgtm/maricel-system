"""Demo data for showcasing the system: realistic catalog, stock history, sales and staff accounts.

All activity is generated through the same services the application uses (purchases receive batches,
the POS deducts stock first-expiry-first-out), so every figure on every page is internally consistent.
"""

import math
import os
import random
import secrets
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models import (
    AuditLog,
    Category,
    Customer,
    Employee,
    Expense,
    Inventory,
    InventoryLog,
    MedicineBatch,
    Payment,
    Product,
    Purchase,
    PurchaseItem,
    Role,
    Sale,
    SaleItem,
    Supplier,
    SystemSetting,
    User,
)
from app.services.inventory import adjust_batch
from app.services.purchases import create_purchase
from app.services.sales import create_sale, void_sale
from app.services.settings import setting_decimal
from app.utils.formatting import business_tz, local_now, money

T = (1, 2, 4, 6, 8, 10, 10, 12, 20, 30)  # tablets / capsules per sale line
B = (1, 1, 1, 1, 2, 2, 3)  # bottles, boxes, pieces
S = (1, 2, 2, 3, 4, 5, 6)  # sachets, nebules

CATEGORIES = [
    ("Analgesics & Antipyretics", "Pain relievers and fever reducers"),
    ("Antibiotics", "Prescription anti-infectives"),
    ("Vitamins & Supplements", "Daily vitamins, minerals and supplements"),
    ("Cough & Cold", "Cough, colds and flu relief"),
    ("Antihistamines", "Allergy relief"),
    ("Gastrointestinal", "Acidity, diarrhea and digestive care"),
    ("Maintenance Medicines", "Cardiovascular, diabetes and respiratory maintenance"),
    ("First Aid & Medical Supplies", "Wound care, devices and consumables"),
    ("Personal & Baby Care", "Hygiene and baby essentials"),
]

# sku, name, generic, category index, unit, price, cost, reorder level, Rx, demand weight, qty choices,
# stock profile, initial quantity
PRODUCTS = [
    ("ANL-001", "Paracetamol 500mg Tablet", "Paracetamol", 0, "tablet", "4.50", "2.20", 200, False, 5, T, "normal", 2000),
    ("ANL-002", "Paracetamol 250mg/5mL Syrup 60mL", "Paracetamol", 0, "bottle", "65.00", "38.00", 20, False, 2, B, "normal", 90),
    ("ANL-003", "Ibuprofen 400mg Tablet", "Ibuprofen", 0, "tablet", "7.50", "3.80", 150, False, 3, T, "normal", 1200),
    ("ANL-004", "Mefenamic Acid 500mg Capsule", "Mefenamic Acid", 0, "capsule", "6.00", "2.90", 150, False, 4, T, "normal", 1500),
    ("ANL-005", "Naproxen Sodium 550mg Tablet", "Naproxen Sodium", 0, "tablet", "12.00", "6.50", 80, False, 2, T, "low", 260),
    ("ABX-001", "Amoxicillin 500mg Capsule", "Amoxicillin", 1, "capsule", "9.00", "4.50", 200, True, 4, (7, 14, 21, 21, 21), "normal", 2000),
    ("ABX-002", "Amoxicillin 250mg/5mL Suspension 60mL", "Amoxicillin", 1, "bottle", "95.00", "55.00", 15, True, 1, B, "expired", 36),
    ("ABX-003", "Cefalexin 500mg Capsule", "Cefalexin", 1, "capsule", "15.00", "8.00", 100, True, 2, (12, 21, 28), "expiring", 900),
    ("ABX-004", "Azithromycin 500mg Tablet", "Azithromycin", 1, "tablet", "45.00", "26.00", 30, True, 2, (3, 3, 6), "out", 60),
    ("ABX-005", "Co-Amoxiclav 625mg Tablet", "Amoxicillin + Clavulanic Acid", 1, "tablet", "38.00", "22.00", 40, True, 2, (7, 14, 14), "normal", 500),
    ("ABX-006", "Ciprofloxacin 500mg Tablet", "Ciprofloxacin", 1, "tablet", "14.00", "7.00", 60, True, 1, (6, 10, 14), "normal", 400),
    ("VIT-001", "Ascorbic Acid 500mg Tablet", "Ascorbic Acid", 2, "tablet", "3.50", "1.60", 200, False, 4, T, "expiring", 1800),
    ("VIT-002", "Multivitamins + Iron Capsule", "Multivitamins + Iron", 2, "capsule", "6.50", "3.20", 150, False, 3, (10, 20, 30, 30), "normal", 1500),
    ("VIT-003", "Vitamin B Complex Tablet", "Vitamin B1 + B6 + B12", 2, "tablet", "7.00", "3.40", 120, False, 2, (10, 20, 30), "normal", 1000),
    ("VIT-004", "Ferrous Sulfate + Folic Acid Tablet", "Ferrous Sulfate + Folic Acid", 2, "tablet", "3.00", "1.30", 100, False, 1, (10, 30, 30), "normal", 800),
    ("VIT-005", "Calcium Carbonate + Vitamin D3 Tablet", "Calcium + Cholecalciferol", 2, "tablet", "8.00", "4.00", 100, False, 2, (10, 20, 30), "low", 330),
    ("VIT-006", "Zinc Sulfate 20mg/5mL Syrup 120mL", "Zinc Sulfate", 2, "bottle", "135.00", "80.00", 10, False, 1, B, "expiring", 40),
    ("CGH-001", "Carbocisteine 500mg Capsule", "Carbocisteine", 3, "capsule", "8.50", "4.20", 120, False, 3, T, "normal", 1200),
    ("CGH-002", "Ambroxol 30mg Tablet", "Ambroxol", 3, "tablet", "6.00", "2.80", 100, False, 2, T, "normal", 900),
    ("CGH-003", "Lagundi 600mg Tablet", "Vitex negundo", 3, "tablet", "6.50", "3.20", 100, False, 2, T, "normal", 900),
    ("CGH-004", "Phenylephrine + Chlorphenamine + Paracetamol Tablet", "Phenylephrine + Chlorphenamine + Paracetamol", 3, "tablet", "7.00", "3.30", 150, False, 4, T, "normal", 1500),
    ("CGH-005", "Dextromethorphan 15mg/5mL Syrup 60mL", "Dextromethorphan", 3, "bottle", "88.00", "50.00", 15, False, 1, B, "expired", 48),
    ("CGH-006", "Guaifenesin 100mg/5mL Syrup 120mL", "Guaifenesin", 3, "bottle", "120.00", "70.00", 12, False, 1, B, "normal", 60),
    ("AHS-001", "Cetirizine 10mg Tablet", "Cetirizine", 4, "tablet", "8.00", "3.50", 120, False, 3, T, "normal", 1200),
    ("AHS-002", "Loratadine 10mg Tablet", "Loratadine", 4, "tablet", "9.00", "4.00", 100, False, 2, T, "low", 280),
    ("AHS-003", "Diphenhydramine 50mg Capsule", "Diphenhydramine", 4, "capsule", "6.00", "2.70", 60, False, 1, T, "normal", 500),
    ("GIT-001", "Loperamide 2mg Capsule", "Loperamide", 5, "capsule", "6.00", "2.60", 80, False, 2, (2, 4, 6), "normal", 600),
    ("GIT-002", "Omeprazole 20mg Capsule", "Omeprazole", 5, "capsule", "12.00", "5.50", 100, False, 2, (7, 14, 30), "normal", 900),
    ("GIT-003", "Aluminum + Magnesium Hydroxide Suspension 120mL", "Aluminum Hydroxide + Magnesium Hydroxide", 5, "bottle", "110.00", "65.00", 10, False, 1, B, "normal", 50),
    ("GIT-004", "Oral Rehydration Salts Sachet", "Oral Rehydration Salts", 5, "sachet", "18.00", "9.00", 50, False, 2, S, "normal", 400),
    ("GIT-005", "Domperidone 10mg Tablet", "Domperidone", 5, "tablet", "9.00", "4.20", 60, True, 1, (6, 10, 20), "normal", 500),
    ("MNT-001", "Amlodipine 5mg Tablet", "Amlodipine", 6, "tablet", "8.00", "3.50", 200, True, 4, (30, 30, 30, 60), "normal", 3000),
    ("MNT-002", "Losartan 50mg Tablet", "Losartan Potassium", 6, "tablet", "12.00", "5.00", 200, True, 3, (30, 30, 60), "normal", 2400),
    ("MNT-003", "Metformin 500mg Tablet", "Metformin", 6, "tablet", "5.00", "2.20", 200, True, 3, (30, 60, 60), "normal", 3000),
    ("MNT-004", "Atorvastatin 20mg Tablet", "Atorvastatin", 6, "tablet", "18.00", "8.00", 100, True, 2, (30, 30), "normal", 1500),
    ("MNT-005", "Aspirin 80mg Tablet", "Acetylsalicylic Acid", 6, "tablet", "3.00", "1.30", 150, False, 2, (30, 30, 60), "normal", 2000),
    ("MNT-006", "Gliclazide 80mg Tablet", "Gliclazide", 6, "tablet", "9.00", "4.00", 100, True, 1, (30, 60), "normal", 1200),
    ("MNT-007", "Salbutamol 2.5mg/2.5mL Nebule", "Salbutamol", 6, "nebule", "22.00", "11.00", 40, True, 2, S, "normal", 400),
    ("SUP-001", "Povidone-Iodine 10% Solution 60mL", "Povidone-Iodine", 7, "bottle", "95.00", "55.00", 10, False, 1, B, "normal", 50),
    ("SUP-002", "Isopropyl Alcohol 70% 500mL", "Isopropyl Alcohol", 7, "bottle", "85.00", "48.00", 20, False, 3, B, "normal", 160),
    ("SUP-003", "Sterile Gauze Pad 4x4 (10s)", "Sterile Gauze", 7, "pack", "45.00", "24.00", 15, False, 1, B, "normal", 70),
    ("SUP-004", "Adhesive Bandage Strips (100s)", "Adhesive Bandage", 7, "box", "120.00", "68.00", 10, False, 1, B, "normal", 40),
    ("SUP-005", "Disposable Face Mask (50s)", "Surgical Face Mask", 7, "box", "150.00", "85.00", 15, False, 2, B, "normal", 90),
    ("SUP-006", "Digital Thermometer", "Digital Thermometer", 7, "piece", "180.00", "105.00", 8, False, 1, B, "low", 26),
    ("SUP-007", "Disposable Syringe 3mL", "Syringe", 7, "piece", "8.00", "3.50", 50, False, 1, (1, 2, 5, 10), "out", 40),
    ("PBC-001", "Hand Sanitizer 250mL", "Ethyl Alcohol Gel", 8, "bottle", "99.00", "58.00", 15, False, 2, B, "normal", 100),
    ("PBC-002", "Baby Diapers Medium (24s)", "Disposable Diapers", 8, "pack", "380.00", "290.00", 10, False, 1, B, "normal", 45),
    ("PBC-003", "Petroleum Jelly 100g", "Petrolatum", 8, "jar", "75.00", "42.00", 10, False, 1, B, "normal", 50),
]

SUPPLIERS = [
    ("MedSource Distribution Inc.", "Ramon Castillo", "orders@medsource.example", "0917 555 0101", "Km. 18 West Service Road, Parañaque City"),
    ("Luzon Pharma Supply Co.", "Grace Navarro", "sales@luzonpharma.example", "0918 555 0202", "45 Shaw Boulevard, Mandaluyong City"),
    ("HealthLink Trading", "Dennis Uy", "hello@healthlink.example", "0920 555 0303", "88 Ortigas Avenue, Pasig City"),
    ("Pacific Medical Distributors", "Carla Bautista", "support@pacificmed.example", "0927 555 0404", "12 Mabini Street, Caloocan City"),
    ("GreenLeaf Wellness Supply", "Paolo Garcia", "greenleaf@wellness.example", "0939 555 0505", "7 Aguinaldo Highway, Imus, Cavite"),
]

# name, phone, email, notes, senior/PWD
CUSTOMERS = [
    ("Lourdes Pascual", "0917 812 3401", None, "Senior citizen. Maintenance: Amlodipine, Losartan.", True),
    ("Ernesto Villareal", "0918 223 4502", None, "Senior citizen. Diabetic — Metformin.", True),
    ("Carmela Ramos", "0919 334 5603", "carmela.ramos@mail.example", None, False),
    ("Benjamin Torres", "0920 445 6704", None, "PWD ID on file.", True),
    ("Rosario Dizon", "0921 556 7805", None, "Senior citizen.", True),
    ("Miguel Fernandez", "0922 667 8906", "miguel.f@mail.example", None, False),
    ("Kristine Aquino", "0923 778 9007", None, "Prefers GCash.", False),
    ("Antonio Salazar", "0925 889 0108", None, "Senior citizen. Atorvastatin.", True),
    ("Jasmine Cruz", "0926 990 1209", "jas.cruz@mail.example", None, False),
    ("Ricardo Lim", "0927 101 2310", None, None, False),
    ("Teresita Gomez", "0928 212 3411", None, "Senior citizen.", True),
    ("Paolo Mercado", "0929 323 4512", None, None, False),
    ("Angelica Morales", "0930 434 5613", "angelica.m@mail.example", "Buys baby care items monthly.", False),
    ("Fernando Castro", "0931 545 6714", None, None, False),
    ("Victoria Robles", "0932 656 7815", None, "Senior citizen.", True),
    ("Daniel Ocampo", "0933 767 8916", None, None, False),
]

EMPLOYEES = [
    # number, first, last, position, email, phone, status, (username, role, password env)
    ("EMP-001", "Maricel", "Dela Cruz", "Owner / Pharmacist", "owner@maricelpharmacy.example", "0917 000 1001", "active", ("owner", "OWNER", "DEMO_OWNER_PASSWORD")),
    ("EMP-002", "Ana", "Reyes", "Cashier", "ana.reyes@maricelpharmacy.example", "0917 000 1002", "active", ("cashier", "CASHIER", "DEMO_CASHIER_PASSWORD")),
    ("EMP-003", "Jose", "Mendoza", "Cashier", "jose.mendoza@maricelpharmacy.example", "0917 000 1003", "active", ("cashier2", "CASHIER", "DEMO_CASHIER_PASSWORD")),
    ("EMP-004", "Liza", "Santos", "Pharmacy Assistant", None, "0917 000 1004", "active", None),
    ("EMP-005", "Mark", "Villanueva", "Stock Clerk", None, "0917 000 1005", "inactive", None),
]

DEMO_SETTINGS = {
    "pharmacy_name": "Maricel Pharmacy",
    "pharmacy_address": "Unit 3, 128 Rizal Avenue, Barangay San Roque, Quezon City",
    "pharmacy_phone": "(02) 8123 4567 · 0917 000 1000",
    "pharmacy_email": "hello@maricelpharmacy.example",
    "tin": "000-123-456-000",
    "receipt_footer": "Thank you for trusting Maricel Pharmacy! Get well soon.",
}


def _utc(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=business_tz()).astimezone(timezone.utc)


def _reset_business_data():
    for model in (SaleItem, Payment, Sale, InventoryLog, MedicineBatch, PurchaseItem, Purchase, Inventory, Expense):
        db.session.query(model).delete(synchronize_session=False)
    db.session.query(Product).delete(synchronize_session=False)
    db.session.query(Category).delete(synchronize_session=False)
    db.session.query(Customer).delete(synchronize_session=False)
    db.session.query(Supplier).delete(synchronize_session=False)
    db.session.query(AuditLog).delete(synchronize_session=False)
    db.session.commit()


def _ensure_staff(created_on):
    roles = {role.name: role for role in Role.query.all()}
    users = {}
    credentials = {}
    for number, first, last, position, email, phone, status, account in EMPLOYEES:
        employee = Employee.query.filter_by(employee_number=number).first()
        if employee is None:
            employee = Employee(
                employee_number=number,
                first_name=first,
                last_name=last,
                position=position,
                email=email,
                phone=phone,
                status=status,
                created_at=created_on,
            )
            db.session.add(employee)
            db.session.flush()
        if account is None:
            continue
        username, role_name, password_env = account
        user = User.query.filter_by(username=username).first()
        if user is None:
            password = os.getenv(password_env) or secrets.token_urlsafe(12)
            user = User(
                username=username,
                email=email,
                role=roles[role_name],
                employee=employee if employee.user is None else None,
                is_active=True,
                created_at=created_on,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            credentials[username] = password if not os.getenv(password_env) else f"(from {password_env})"
        users[username] = user
    return users, credentials


def _tendered(total, rng):
    total = Decimal(total)
    options = [total]
    for step in (20, 50, 100, 500, 1000):
        options.append(Decimal(math.ceil(total / step) * step))
    options = [option for option in options if option >= total]
    return rng.choice(options)


def _available(product_id, on_date):
    value = (
        db.session.query(func.coalesce(func.sum(MedicineBatch.quantity), 0))
        .filter(
            MedicineBatch.product_id == product_id,
            MedicineBatch.quantity > 0,
            MedicineBatch.expiration_date >= on_date,
        )
        .scalar()
    )
    return Decimal(value or 0)


def seed_demo(reset=False):
    rng = random.Random(2026)
    if reset:
        _reset_business_data()
    elif Product.query.count() > 0:
        return "Demo data skipped: products already exist. Use --reset to rebuild the demo dataset."

    now_local = local_now()
    today = now_local.date()
    start_day = today - timedelta(days=80)
    sales_start = today - timedelta(days=60)

    for key, value in DEMO_SETTINGS.items():
        row = SystemSetting.query.filter_by(key=key).first()
        if row is not None and not row.value:
            row.value = value
        elif row is None:
            db.session.add(SystemSetting(key=key, value=value))

    users, credentials = _ensure_staff(_utc(start_day, 9))
    owner = users["owner"]
    cashiers = [users["cashier"], users["cashier2"]]

    categories = []
    for name, description in CATEGORIES:
        category = Category(name=name, description=description, is_active=True, created_at=_utc(start_day, 9))
        db.session.add(category)
        categories.append(category)
    db.session.flush()

    products = {}
    meta = {}
    for sku, name, generic, cat, unit, price, cost, reorder, rx, weight, qty, profile, initial in PRODUCTS:
        product = Product(
            sku=sku,
            name=name,
            generic_name=generic,
            category_id=categories[cat].id,
            unit=unit,
            selling_price=Decimal(price),
            reorder_level=reorder,
            requires_prescription=rx,
            is_active=True,
            created_at=_utc(start_day, 10),
        )
        db.session.add(product)
        db.session.flush()
        db.session.add(Inventory(product_id=product.id, quantity=0))
        products[sku] = product
        floor = Decimal(int(reorder * 0.45)) if profile == "low" else Decimal(0)
        meta[sku] = {
            "cost": Decimal(cost),
            "price": Decimal(price),
            "weight": weight,
            "qty": qty,
            "profile": profile,
            "initial": int(initial * {"normal": 2.2, "expiring": 1.5}.get(profile, 1)),
            "floor": floor,
            "unit": unit,
            "category": cat,
        }
    # One discontinued product to show inactive records.
    discontinued = Product(
        sku="ANL-099",
        name="Aspirin 325mg Tablet (discontinued)",
        generic_name="Acetylsalicylic Acid",
        category_id=categories[0].id,
        unit="tablet",
        selling_price=Decimal("2.50"),
        reorder_level=0,
        is_active=False,
        created_at=_utc(start_day, 10),
    )
    db.session.add(discontinued)
    db.session.flush()
    db.session.add(Inventory(product_id=discontinued.id, quantity=0))

    suppliers = []
    for name, contact, email, phone, address in SUPPLIERS:
        supplier = Supplier(
            name=name, contact_person=contact, email=email, phone=phone, address=address, status="active",
            created_at=_utc(start_day, 9),
        )
        db.session.add(supplier)
        suppliers.append(supplier)
    suppliers[4].status = "inactive"
    db.session.flush()

    customers = []
    for name, phone, email, notes, senior in CUSTOMERS:
        customer = Customer(name=name, phone=phone, email=email, notes=notes, is_active=True,
                            created_at=_utc(start_day + timedelta(days=rng.randint(0, 40)), 11))
        db.session.add(customer)
        customers.append((customer, senior))
    db.session.flush()

    def line(sku, quantity, *, expiry_days=None, expiry_date=None, batch=None):
        info = meta[sku]
        if expiry_date is None:
            expiry_date = today + timedelta(days=expiry_days or rng.randint(420, 900))
        return {
            "product_id": products[sku].id,
            "quantity": Decimal(quantity),
            "unit_cost": info["cost"],
            "selling_price": info["price"],
            "batch_number": batch or f"{sku.split('-')[0]}{rng.randint(10000, 99999)}",
            "expiration_date": expiry_date,
        }

    def initial_lines(category_indexes):
        lines = []
        for sku, info in meta.items():
            if info["category"] not in category_indexes:
                continue
            profile = info["profile"]
            if profile == "expired":
                lines.append(line(sku, info["initial"], expiry_date=today - timedelta(days=rng.randint(4, 14))))
            elif profile == "expiring":
                lines.append(line(sku, info["initial"], expiry_days=rng.randint(35, 75)))
            else:
                lines.append(line(sku, info["initial"]))
        return lines

    def restock_lines(skus, factor=0.5):
        return [line(sku, max(int(meta[sku]["initial"] * factor), 10)) for sku in skus]

    popular = [sku for sku, info in meta.items() if info["weight"] >= 3 and info["profile"] == "normal"]
    expired_profile = [sku for sku, info in meta.items() if info["profile"] == "expired"]
    low_or_out = [sku for sku, info in meta.items() if info["profile"] in {"low", "out"}]

    purchase_plan = {
        today - timedelta(days=78): [(suppliers[0], initial_lines({0, 1, 3, 4}), "received", "Opening stock")],
        today - timedelta(days=76): [(suppliers[1], initial_lines({2, 5, 6}), "received", "Opening stock")],
        today - timedelta(days=74): [(suppliers[2], initial_lines({7, 8}), "received", "Opening stock")],
        today - timedelta(days=42): [
            (suppliers[0], restock_lines(popular[:8]) + restock_lines(expired_profile, 1.2), "received", "Monthly restock"),
        ],
        today - timedelta(days=38): [
            (suppliers[3], restock_lines(["SUP-002", "SUP-005", "PBC-001"], 0.6), "cancelled", "Supplier could not deliver on time"),
        ],
        today - timedelta(days=22): [
            (suppliers[1], restock_lines(popular[8:], 0.6), "received", "Mid-month restock"),
        ],
        today - timedelta(days=9): [
            (suppliers[0], restock_lines(["ANL-001", "ANL-004", "CGH-004", "MNT-001", "MNT-003"], 0.4), "received", None),
            (suppliers[2], restock_lines(["SUP-002", "SUP-005", "PBC-001", "GIT-004"], 0.6), "received", None),
        ],
        today - timedelta(days=2): [
            (suppliers[0], restock_lines(low_or_out, 1.5), "ordered", "Urgent: low and out-of-stock items"),
        ],
        today - timedelta(days=1): [
            (suppliers[1], restock_lines(["VIT-001", "VIT-006", "ABX-003"], 0.8), "ordered", "Replace near-expiry batches"),
        ],
    }

    adjustments = {
        today - timedelta(days=33): ("SUP-002", "damaged", 2, "Two bottles broken during shelf restocking"),
        today - timedelta(days=17): ("ANL-001", "count_correction", -20, "Monthly cycle count variance"),
        today - timedelta(days=6): ("GIT-004", "found", 5, "Sachets found in back storage during count"),
    }

    expense_plan = []
    month_cursor = start_day.replace(day=1)
    while month_cursor <= today:
        def dated(day_number):
            try:
                return month_cursor.replace(day=day_number)
            except ValueError:
                next_month = (month_cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
                return next_month - timedelta(days=1)

        expense_plan += [
            (dated(1), "Rent", "Monthly store rent", Decimal("18000.00")),
            (dated(5), "Utilities", "Electricity bill", money(rng.uniform(5200, 7400))),
            (dated(6), "Utilities", "Water bill", money(rng.uniform(780, 1250))),
            (dated(8), "Utilities", "Internet and POS line", Decimal("1699.00")),
            (dated(10), "Supplies", "Receipt paper, paper bags and labels", money(rng.uniform(1200, 2800))),
            (dated(15), "Salaries & Wages", "Payroll — 1st half (3 staff)", Decimal("22500.00")),
            (dated(18), "Delivery & Transport", "Rider fees for home deliveries", money(rng.uniform(600, 1500))),
            (dated(30), "Salaries & Wages", "Payroll — 2nd half (3 staff)", Decimal("22500.00")),
        ]
        if month_cursor.month % 3 == 1:
            expense_plan.append((dated(20), "Taxes & Licenses", "Quarterly percentage tax", Decimal("4850.00")))
        if month_cursor.month % 2 == 0:
            expense_plan.append((dated(12), "Maintenance & Repairs", "Aircon cleaning and maintenance", Decimal("2500.00")))
        month_cursor = (month_cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    expense_plan.append((today - timedelta(days=11), "Marketing", "Tarpaulin and flyers for senior wellness week", Decimal("1850.00")))
    expense_plan.append((today - timedelta(days=3), "Miscellaneous", "Pest control service", Decimal("1500.00")))
    expenses_by_day = {}
    for day, category, description, amount in expense_plan:
        if start_day <= day <= today:
            expenses_by_day.setdefault(day, []).append((category, description, amount))

    skus = list(meta)
    weights = [meta[sku]["weight"] for sku in skus]
    sale_count = 0
    void_targets = {today - timedelta(days=19), today - timedelta(days=4)}

    day = start_day
    while day <= today:
        for supplier, lines, status, note in purchase_plan.get(day, []):
            purchase = create_purchase(
                supplier_id=supplier.id,
                lines=lines,
                user=owner,
                purchased_at=_utc(day, 9, 15),
                notes=note,
                receive=status == "received",
                received_at=_utc(day, 14, 30),
            )
            purchase.created_at = _utc(day, 9, 15)
            if status == "cancelled":
                purchase.status = "cancelled"
                db.session.add(AuditLog(user_id=owner.id, action="purchase.cancelled", entity_type="Purchase",
                                        entity_id=str(purchase.id), details={"reference": purchase.reference},
                                        created_at=_utc(day, 16)))

        if day in adjustments:
            sku, reason, change, note = adjustments[day]
            batch = (
                MedicineBatch.query.filter(MedicineBatch.product_id == products[sku].id, MedicineBatch.quantity > abs(change))
                .order_by(MedicineBatch.expiration_date.asc())
                .first()
            )
            if batch is not None:
                when = _utc(day, 17, 40)
                adjust_batch(batch, Decimal(batch.quantity) + change, reason=reason, note=note, user_id=owner.id, when=when)
                db.session.add(AuditLog(user_id=owner.id, action="inventory.adjusted", entity_type="MedicineBatch",
                                        entity_id=str(batch.id), details={"product": products[sku].name, "change": str(change), "reason": reason},
                                        created_at=when))

        for category, description, amount in expenses_by_day.get(day, []):
            db.session.add(Expense(category=category, description=description, amount=amount,
                                   incurred_at=_utc(day, 12), created_by_id=owner.id, created_at=_utc(day, 12)))

        if day >= sales_start:
            weekday = day.weekday()
            base = 17 if weekday < 5 else (23 if weekday == 5 else 12)
            count = max(6, base + rng.randint(-3, 5))
            minutes = sorted(rng.sample(range(8 * 60, 20 * 60), count))
            logged_in = set()
            for minute in minutes:
                sold_at = _utc(day, minute // 60, minute % 60)
                if day == today and sold_at > now_local.astimezone(timezone.utc) - timedelta(minutes=5):
                    break
                roll = rng.random()
                cashier = owner if roll < 0.15 else (cashiers[0] if roll < 0.7 else cashiers[1])
                chosen = []
                for sku in rng.choices(skus, weights=weights, k=rng.choice((1, 1, 2, 2, 2, 3, 3, 4))):
                    if sku in {c[0] for c in chosen}:
                        continue
                    info = meta[sku]
                    quantity = Decimal(rng.choice(info["qty"]))
                    available = _available(products[sku].id, day) - info["floor"]
                    if available <= 0:
                        continue
                    quantity = min(quantity, available)
                    if quantity > 0:
                        chosen.append((sku, quantity))
                if not chosen:
                    continue
                customer_id, discount_type = None, ""
                if rng.random() < 0.38:
                    customer, senior = rng.choice(customers)
                    customer_id = customer.id
                    if senior and rng.random() < 0.85:
                        discount_type = "pwd" if "PWD" in (customer.notes or "") else "senior"
                method = rng.choices(["cash", "gcash", "maya", "card"], weights=[68, 22, 6, 4])[0]
                subtotal = sum((meta[sku]["price"] * qty for sku, qty in chosen), Decimal("0"))
                estimate = money(subtotal * (1 + setting_decimal("tax_rate") / 100))
                if cashier.id not in logged_in:
                    db.session.add(AuditLog(user_id=cashier.id, action="auth.login", ip_address="192.168.1." + str(20 + cashier.id),
                                            created_at=sold_at - timedelta(minutes=rng.randint(3, 25))))
                    logged_in.add(cashier.id)
                sale = create_sale(
                    cashier=cashier,
                    lines=[(products[sku].id, qty) for sku, qty in chosen],
                    customer_id=customer_id,
                    discount_type=discount_type,
                    payment_method=method,
                    amount_tendered=_tendered(estimate, rng) if method == "cash" else None,
                    payment_reference=f"{rng.randint(1000000000, 9999999999)}" if method in {"gcash", "maya"} else None,
                    sold_at=sold_at,
                )
                sale.created_at = sold_at
                sale_count += 1
                if day in void_targets and cashier is not owner:
                    void_targets.discard(day)
                    void_sale(sale, user=owner, reason=rng.choice(["Customer changed mind before leaving the counter", "Wrong item rung up; re-entered as new sale"]),
                              when=sold_at + timedelta(minutes=6))
            db.session.flush()
        day += timedelta(days=1)

    db.session.commit()
    lines = [f"Demo data loaded: {len(PRODUCTS) + 1} products, {sale_count} sales, {Purchase.query.count()} purchases."]
    for username, password in credentials.items():
        lines.append(f"  login {username}: {password}")
    return "\n".join(lines)
