"""Operational workflows: product pricing, POS tender details, purchase receiving

Revision ID: 5c1f2e7a9b10
Revises: 09a8822ffa75
Create Date: 2026-11-14 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "5c1f2e7a9b10"
down_revision = "09a8822ffa75"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("selling_price", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0")
        )

    with op.batch_alter_table("purchases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("received_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))

    with op.batch_alter_table("purchase_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("selling_price", sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column("batch_number", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("expiration_date", sa.Date(), nullable=True))

    with op.batch_alter_table("sales", schema=None) as batch_op:
        batch_op.add_column(sa.Column("customer_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("discount_type", sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column("amount_tendered", sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column("change_amount", sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("void_reason", sa.String(length=255), nullable=True))
        batch_op.create_index(batch_op.f("ix_sales_customer_id"), ["customer_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_sales_customer_id_customers", "customers", ["customer_id"], ["id"], ondelete="SET NULL"
        )


def downgrade():
    with op.batch_alter_table("sales", schema=None) as batch_op:
        batch_op.drop_constraint("fk_sales_customer_id_customers", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_sales_customer_id"))
        batch_op.drop_column("void_reason")
        batch_op.drop_column("voided_at")
        batch_op.drop_column("change_amount")
        batch_op.drop_column("amount_tendered")
        batch_op.drop_column("discount_type")
        batch_op.drop_column("customer_id")

    with op.batch_alter_table("purchase_items", schema=None) as batch_op:
        batch_op.drop_column("expiration_date")
        batch_op.drop_column("batch_number")
        batch_op.drop_column("selling_price")

    with op.batch_alter_table("purchases", schema=None) as batch_op:
        batch_op.drop_column("notes")
        batch_op.drop_column("received_at")

    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.drop_column("selling_price")
