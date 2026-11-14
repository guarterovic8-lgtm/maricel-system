from flask import Blueprint, redirect, request, url_for
from flask_login import login_required
from sqlalchemy import func, or_

from app.extensions import db
from app.models import Category, Inventory, Product
from app.routes.helpers import back, checkbox, form_action, get_or_404, page
from app.services.inventory import low_stock_level, sellable_stock_map, stock_status
from app.services.settings import setting_decimal
from app.utils.access import audit_event, permission_required
from app.utils.formatting import MILLI, clean, parse_decimal

catalog_bp = Blueprint("catalog", __name__, url_prefix="/modules")

DUPLICATE_PRODUCT = "A product with that SKU already exists."
DUPLICATE_CATEGORY = "A category with that name already exists."


def _apply_product_form(product, form):
    name = clean(form.get("name"), 180)
    sku = clean(form.get("sku"), 64)
    if not name or not sku:
        raise ValueError("Product name and SKU are required.")
    category_id = form.get("category_id", type=int)
    if category_id and db.session.get(Category, category_id) is None:
        raise ValueError("The selected category does not exist.")
    product.name = name
    product.sku = sku
    product.generic_name = clean(form.get("generic_name"), 180)
    product.description = clean(form.get("description"))
    product.category_id = category_id or None
    product.unit = clean(form.get("unit"), 30) or "unit"
    product.selling_price = parse_decimal(form.get("selling_price"), "Selling price", required=False) or 0
    product.reorder_level = parse_decimal(form.get("reorder_level") or "0", "Reorder level", places=MILLI)
    product.requires_prescription = checkbox("requires_prescription")


@catalog_bp.route("/products", methods=["GET", "POST"])
@login_required
@permission_required("products.manage")
def products():
    if request.method == "POST":
        with form_action(
            "Product created. Receive stock from Purchases or Stock & Batches.", DUPLICATE_PRODUCT
        ):
            product = Product(is_active=True)
            _apply_product_form(product, request.form)
            db.session.add(product)
            db.session.flush()
            db.session.add(Inventory(product_id=product.id, quantity=0))
            audit_event("product.created", "Product", product.id, {"sku": product.sku, "name": product.name})
        return redirect(url_for("catalog.products"))

    search = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    status = request.args.get("status", "active")
    query = Product.query
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.generic_name.ilike(like)))
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if status == "active":
        query = query.filter(Product.is_active.is_(True))
    elif status == "inactive":
        query = query.filter(Product.is_active.is_(False))
    rows = query.order_by(Product.name.asc()).limit(500).all()
    stock = sellable_stock_map()
    threshold = setting_decimal("low_stock_threshold")
    stock_rows = []
    for product in rows:
        quantity = stock.get(product.id, 0)
        stock_rows.append((product, quantity, stock_status(quantity, low_stock_level(product, threshold))))
    categories = Category.query.order_by(Category.name.asc()).all()
    return page(
        "modules/products.html",
        "products",
        title="Products",
        rows=stock_rows,
        categories=categories,
        filters={"q": search, "category": category_id, "status": status},
        total_count=Product.query.count(),
    )


@catalog_bp.post("/products/<int:product_id>/edit")
@login_required
@permission_required("products.manage")
def product_edit(product_id):
    product = get_or_404(Product, product_id)
    with form_action("Product updated.", DUPLICATE_PRODUCT):
        _apply_product_form(product, request.form)
        audit_event("product.updated", "Product", product.id, {"sku": product.sku})
    return back(url_for("catalog.products"))


@catalog_bp.post("/products/<int:product_id>/toggle")
@login_required
@permission_required("products.manage")
def product_toggle(product_id):
    product = get_or_404(Product, product_id)
    with form_action() as result:
        product.is_active = not product.is_active
        state = "activated" if product.is_active else "deactivated"
        audit_event(f"product.{state}", "Product", product.id, {"sku": product.sku})
        result.message = f"{product.name} {state}."
    return back(url_for("catalog.products"))


def _apply_category_form(category, form):
    name = clean(form.get("name"), 100)
    if not name:
        raise ValueError("Category name is required.")
    category.name = name
    category.description = clean(form.get("description"), 255)


@catalog_bp.route("/categories", methods=["GET", "POST"])
@login_required
@permission_required("products.manage")
def categories():
    if request.method == "POST":
        with form_action("Category created.", DUPLICATE_CATEGORY):
            category = Category(is_active=True)
            _apply_category_form(category, request.form)
            db.session.add(category)
            db.session.flush()
            audit_event("category.created", "Category", category.id, {"name": category.name})
        return redirect(url_for("catalog.categories"))

    counts = dict(
        db.session.query(Product.category_id, func.count(Product.id))
        .filter(Product.is_active.is_(True))
        .group_by(Product.category_id)
        .all()
    )
    rows = Category.query.order_by(Category.name.asc()).all()
    return page(
        "modules/categories.html",
        "categories",
        title="Categories",
        rows=[(category, counts.get(category.id, 0)) for category in rows],
        uncategorized=counts.get(None, 0),
    )


@catalog_bp.post("/categories/<int:category_id>/edit")
@login_required
@permission_required("products.manage")
def category_edit(category_id):
    category = get_or_404(Category, category_id)
    with form_action("Category updated.", DUPLICATE_CATEGORY):
        _apply_category_form(category, request.form)
        audit_event("category.updated", "Category", category.id, {"name": category.name})
    return redirect(url_for("catalog.categories"))


@catalog_bp.post("/categories/<int:category_id>/toggle")
@login_required
@permission_required("products.manage")
def category_toggle(category_id):
    category = get_or_404(Category, category_id)
    with form_action():
        category.is_active = not category.is_active
        audit_event(
            "category.activated" if category.is_active else "category.deactivated", "Category", category.id
        )
    return redirect(url_for("catalog.categories"))
