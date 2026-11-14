from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_permissions = db.Table(
    "user_permissions",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class Role(db.Model, TimestampMixin):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False, unique=True)
    description = db.Column(db.String(255))
    permissions = db.relationship("Permission", secondary=role_permissions, lazy="selectin")


class Permission(db.Model):
    __tablename__ = "permissions"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False, unique=True)
    description = db.Column(db.String(255), nullable=False)


class Employee(db.Model, TimestampMixin):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    employee_number = db.Column(db.String(40), nullable=False, unique=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(254), unique=True)
    phone = db.Column(db.String(40))
    position = db.Column(db.String(100))
    status = db.Column(db.String(20), nullable=False, default="active")


class User(UserMixin, db.Model, TimestampMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    email = db.Column(db.String(254), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id", ondelete="SET NULL"), unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime(timezone=True))
    role = db.relationship("Role", lazy="joined")
    employee = db.relationship("Employee", lazy="joined", backref=db.backref("user", uselist=False))
    extra_permissions = db.relationship("Permission", secondary=user_permissions, lazy="selectin")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_permission(self, permission):
        if self.role and self.role.name.upper() == "OWNER":
            return True
        role_codes = {item.code for item in self.role.permissions} if self.role else set()
        extra_codes = {item.code for item in self.extra_permissions}
        return permission in role_codes or permission in extra_codes

    @property
    def display_name(self):
        if self.employee:
            return f"{self.employee.first_name} {self.employee.last_name}"
        return self.username

    @property
    def is_owner(self):
        return bool(self.role and self.role.name.upper() == "OWNER")

    @property
    def role_label(self):
        return self.role.name.title() if self.role else "User"


class Category(db.Model, TimestampMixin):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Customer(db.Model, TimestampMixin):
    __tablename__ = "customers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False, index=True)
    phone = db.Column(db.String(40), unique=True)
    email = db.Column(db.String(254), unique=True)
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Product(db.Model, TimestampMixin):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(180), nullable=False, index=True)
    generic_name = db.Column(db.String(180))
    description = db.Column(db.Text)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    unit = db.Column(db.String(30), nullable=False, default="unit")
    selling_price = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default="0")
    reorder_level = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    requires_prescription = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    category = db.relationship("Category", lazy="joined")


class Supplier(db.Model, TimestampMixin):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False, unique=True)
    contact_person = db.Column(db.String(120))
    email = db.Column(db.String(254))
    phone = db.Column(db.String(40))
    address = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="active")


class Inventory(db.Model, TimestampMixin):
    __tablename__ = "inventory"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, unique=True)
    quantity = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    product = db.relationship("Product", lazy="joined")


class Purchase(db.Model, TimestampMixin):
    __tablename__ = "purchases"
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(60), nullable=False, unique=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    purchased_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    received_at = db.Column(db.DateTime(timezone=True))
    total_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    notes = db.Column(db.Text)
    supplier = db.relationship("Supplier")
    created_by = db.relationship("User")


class PurchaseItem(db.Model):
    __tablename__ = "purchase_items"
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity = db.Column(db.Numeric(12, 3), nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)
    selling_price = db.Column(db.Numeric(12, 2))
    batch_number = db.Column(db.String(80))
    expiration_date = db.Column(db.Date)
    purchase = db.relationship("Purchase", backref=db.backref("items", cascade="all, delete-orphan"))
    product = db.relationship("Product")


class MedicineBatch(db.Model, TimestampMixin):
    __tablename__ = "medicine_batches"
    __table_args__ = (
        db.UniqueConstraint("product_id", "batch_number", name="uq_batch_product_number"),
        db.Index("ix_batch_expiry_date", "expiration_date"),
    )
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    purchase_item_id = db.Column(db.Integer, db.ForeignKey("purchase_items.id", ondelete="SET NULL"))
    batch_number = db.Column(db.String(80), nullable=False)
    quantity = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    expiration_date = db.Column(db.Date, nullable=False)
    purchase_cost = db.Column(db.Numeric(12, 2), nullable=False)
    selling_price = db.Column(db.Numeric(12, 2), nullable=False)
    product = db.relationship("Product")
    purchase_item = db.relationship("PurchaseItem")


class Sale(db.Model, TimestampMixin):
    __tablename__ = "sales"
    id = db.Column(db.Integer, primary_key=True)
    receipt_number = db.Column(db.String(60), nullable=False, unique=True, index=True)
    cashier_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"), index=True)
    status = db.Column(db.String(20), nullable=False, default="completed", index=True)
    sold_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    discount_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    discount_type = db.Column(db.String(30))
    amount_tendered = db.Column(db.Numeric(12, 2))
    change_amount = db.Column(db.Numeric(12, 2))
    voided_at = db.Column(db.DateTime(timezone=True))
    void_reason = db.Column(db.String(255))
    cashier = db.relationship("User")
    customer = db.relationship("Customer", backref=db.backref("sales", lazy="dynamic"))


class SaleItem(db.Model):
    __tablename__ = "sale_items"
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("medicine_batches.id", ondelete="RESTRICT"))
    quantity = db.Column(db.Numeric(12, 3), nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)
    sale = db.relationship("Sale", backref=db.backref("items", cascade="all, delete-orphan"))
    product = db.relationship("Product")
    batch = db.relationship("MedicineBatch")


class Payment(db.Model, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        db.CheckConstraint(
            "(sale_id IS NOT NULL AND purchase_id IS NULL) OR "
            "(sale_id IS NULL AND purchase_id IS NOT NULL)",
            name="ck_payment_one_transaction",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id", ondelete="CASCADE"), index=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchases.id", ondelete="CASCADE"), index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(30), nullable=False)
    reference = db.Column(db.String(100))
    paid_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    sale = db.relationship("Sale", backref=db.backref("payments", cascade="all, delete-orphan"))


class Expense(db.Model, TimestampMixin):
    __tablename__ = "expenses"
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    incurred_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_by = db.relationship("User")


class InventoryLog(db.Model):
    __tablename__ = "inventory_logs"
    __table_args__ = (db.Index("ix_inventory_logs_created_at", "created_at"),)
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"), index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("medicine_batches.id", ondelete="SET NULL"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(40), nullable=False)
    quantity_change = db.Column(db.Numeric(12, 3), nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    product = db.relationship("Product")
    batch = db.relationship("MedicineBatch")
    user = db.relationship("User")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    __table_args__ = (db.Index("ix_audit_logs_created_at", "created_at"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(80))
    entity_id = db.Column(db.String(80))
    details = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    user = db.relationship("User")


class SystemSetting(db.Model, TimestampMixin):
    __tablename__ = "system_settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), nullable=False, unique=True)
    value = db.Column(db.Text)
    description = db.Column(db.String(255))
