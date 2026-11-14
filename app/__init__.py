import click
from flask import Flask, render_template
from flask_login import LoginManager

from app.extensions import csrf, db, migrate
from config import Config

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "info"


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("Set SECRET_KEY in the environment or .env file before starting the application.")
    if app.config.get("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user = db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None
        return user if user and user.is_active else None

    from app.routes.admin import admin_bp
    from app.routes.auth import auth_bp
    from app.routes.catalog import catalog_bp
    from app.routes.customers import customers_bp
    from app.routes.finance import finance_bp
    from app.routes.inventory import inventory_bp
    from app.routes.main import main_bp
    from app.routes.purchasing import purchasing_bp
    from app.routes.sales import sales_bp

    for blueprint in (
        auth_bp,
        main_bp,
        catalog_bp,
        inventory_bp,
        purchasing_bp,
        sales_bp,
        customers_bp,
        finance_bp,
        admin_bp,
    ):
        app.register_blueprint(blueprint)

    _register_template_helpers(app)
    _register_error_handlers(app)
    _register_cli(app)
    return app


def _register_template_helpers(app):
    from app.utils.formatting import format_local, format_peso, format_qty, local_today, to_local

    app.add_template_filter(format_peso, "peso")
    app.add_template_filter(format_qty, "qty")
    app.add_template_filter(format_local, "localtime")
    app.add_template_filter(lambda value, fmt="%b %d, %Y": format_local(value, fmt), "localdate")
    app.add_template_filter(lambda value: f"{float(value or 0):,.1f}%", "pct")

    @app.context_processor
    def inject_template_helpers():
        from app.services.settings import get_settings

        def pharmacy_name():
            try:
                return get_settings().get("pharmacy_name") or "Maricel Pharmacy"
            except Exception:
                return "Maricel Pharmacy"

        return {"today": local_today, "to_local": to_local, "pharmacy_name": pharmacy_name}

    def url_with(**overrides):
        """Current URL with query arguments replaced (used by filters and pagination)."""
        from flask import request, url_for

        args = request.args.to_dict()
        args.update(overrides)
        args = {key: value for key, value in args.items() if value not in (None, "")}
        return url_for(request.endpoint, **(request.view_args or {}), **args)

    # Globals (unlike context-processor values) are visible inside imported macros.
    app.jinja_env.globals["url_with"] = url_with


def _register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html", title="Access denied"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html", title="Page not found"), 404

    @app.errorhandler(500)
    def server_error(_error):
        db.session.rollback()
        return render_template("errors/500.html", title="Something went wrong"), 500


def _register_cli(app):
    @app.cli.command("seed-roles")
    def seed_roles_command():
        """Create the built-in roles, permissions and default settings if missing."""
        from app.services.bootstrap import seed_roles

        seed_roles()
        click.echo("OWNER and CASHIER roles, permissions and default settings are initialized.")

    @app.cli.command("init-db")
    def init_db_command():
        """Create schema directly (no migration tracking) and seed roles."""
        from app.services.bootstrap import seed_roles

        db.create_all()
        seed_roles()
        click.echo("Database schema is ready; OWNER and CASHIER roles are initialized.")

    @app.cli.command("seed-demo")
    @click.option("--reset", is_flag=True, help="Delete existing business data first, then reseed.")
    def seed_demo_command(reset):
        """Load realistic demo data (products, stock, sales, staff accounts) for both owner and cashier views."""
        from app.services.bootstrap import seed_roles
        from app.services.demo import seed_demo

        seed_roles()
        result = seed_demo(reset=reset)
        click.echo(result)

    @app.cli.command("create-owner")
    def create_owner_command():
        """Create the first owner using interactive password entry."""
        import getpass

        from app.models import Role, User
        from app.utils.access import audit_event

        if User.query.join(Role).filter(Role.name == "OWNER").first():
            raise RuntimeError("An owner account already exists; refusing to create another.")
        username = input("Owner username: ").strip()
        email = input("Owner email (optional): ").strip() or None
        password = getpass.getpass("Owner password (minimum 12 characters): ")
        confirmation = getpass.getpass("Confirm password: ")
        if not username or len(password) < 12 or password != confirmation:
            raise RuntimeError("Username is required; passwords must match and be at least 12 characters.")
        role = Role.query.filter_by(name="OWNER").first()
        if not role:
            raise RuntimeError("Run `flask --app run.py seed-roles` before creating an owner.")
        owner = User(username=username, email=email, role=role, is_active=True)
        owner.set_password(password)
        db.session.add(owner)
        db.session.flush()
        audit_event("user.owner_created", "User", owner.id, {"username": username}, user_id=owner.id)
        db.session.commit()
        click.echo("Owner account created.")

    @app.cli.command("create-employee")
    def create_employee_command():
        """Create a cashier employee record and its login account."""
        import getpass

        from app.models import Employee, Role, User

        employee_number = input("Employee number: ").strip()
        first_name = input("First name: ").strip()
        last_name = input("Last name: ").strip()
        username = input("Login username: ").strip()
        password = getpass.getpass("Temporary password (minimum 12 characters): ")
        if not all((employee_number, first_name, last_name, username)) or len(password) < 12:
            raise RuntimeError("All listed fields are required; password must be at least 12 characters.")
        cashier_role = Role.query.filter_by(name="CASHIER").first()
        if not cashier_role:
            raise RuntimeError("Run `flask --app run.py seed-roles` before creating an employee.")
        employee = Employee(
            employee_number=employee_number,
            first_name=first_name,
            last_name=last_name,
            position="Cashier",
        )
        user = User(username=username, role=cashier_role, employee=employee, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo("Cashier account created.")
