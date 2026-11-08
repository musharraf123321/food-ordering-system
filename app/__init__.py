import os

import click
from flask import Flask, Response, render_template
from flask_login import current_user

from config import Config
from app.extensions import db, login_manager
from app.utils import (
    category_emoji, csrf_protect, dt, generate_csrf_token, image_url, money, status_badge,
)


def create_app(config_object=Config, overrides=None):
    app = Flask(__name__)
    app.config.from_object(config_object)
    if overrides:
        app.config.update(overrides)

    os.makedirs(app.config["INSTANCE_DIR"], exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from app.models import User, ORDER_STATUSES

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ---- blueprints ------------------------------------------------------
    from app.routes.auth import auth_bp
    from app.routes.customer import customer_bp
    from app.routes.owner import owner_bp
    from app.routes.admin import admin_bp
    from app.routes.insights import insights_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(owner_bp, url_prefix="/owner")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(insights_bp, url_prefix="/insights")

    # ---- request hooks / template helpers ---------------------------------
    app.before_request(csrf_protect)
    app.jinja_env.filters["money"] = money
    app.jinja_env.filters["badge"] = status_badge
    app.jinja_env.filters["dt"] = dt
    app.jinja_env.filters["emoji"] = category_emoji
    app.jinja_env.globals["image_url"] = image_url

    @app.context_processor
    def inject_globals():
        cart_count = 0
        if current_user.is_authenticated and current_user.is_customer and current_user.cart:
            cart_count = current_user.cart.item_count
        return {
            "csrf_token": generate_csrf_token,
            "cart_count": cart_count,
            "ORDER_STATUSES": ORDER_STATUSES,
        }

    @app.route("/plotly.min.js")
    def plotly_js():
        """Serve Plotly.js from the installed python package (works offline)."""
        from plotly.offline import get_plotlyjs

        resp = Response(get_plotlyjs(), mimetype="application/javascript")
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    # ---- error pages -------------------------------------------------------
    @app.errorhandler(400)
    def bad_request(e):
        return render_template("errors/error.html", code=400, title="Bad Request",
                               message=getattr(e, "description", "Bad request.")), 400

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/error.html", code=403, title="Access Denied",
                               message="You do not have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/error.html", code=404, title="Not Found",
                               message="The page or record you asked for does not exist."), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("errors/error.html", code=413, title="File Too Large",
                               message="The uploaded file is larger than the 5 MB limit."), 413

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template("errors/error.html", code=500, title="Something went wrong",
                               message="An unexpected error occurred. Please try again."), 500

    # ---- database ----------------------------------------------------------
    with app.app_context():
        db.create_all()
        from app.services.seed import seed_default_admin
        seed_default_admin()

    register_cli(app)

    # Scheduled automatic backups (only in the real server process, not in the
    # Flask reloader's parent process and never during tests).
    if app.config.get("AUTO_BACKUP_ENABLED") and not app.config.get("TESTING"):
        if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            from app.services.backup import start_scheduler
            start_scheduler(app)

    return app


def register_cli(app):
    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", default=None)
    @click.option("--password", default=None, hide_input=True)
    def create_admin(email, name, password):
        """Promote an existing user to admin, or create a new admin account."""
        from app.models import User

        user = User.query.filter_by(email=email).first()
        if user:
            user.role = "admin"
            db.session.commit()
            click.echo(f"'{email}' is now an admin.")
            return
        if not name or not password:
            raise click.UsageError("Pass --name and --password to create a new admin.")
        user = User(name=name, email=email, role="admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Admin '{email}' created.")

    @app.cli.command("seed-demo")
    @click.option("--reset", is_flag=True, help="Delete ALL data first.")
    @click.option("--days", default=90, show_default=True)
    def seed_demo(reset, days):
        """Fill the database with demo restaurants, users and order history."""
        from app.services.seed import seed_demo_data

        if reset:
            db.drop_all()
            db.create_all()
        counts = seed_demo_data(days=days)
        click.echo(f"Demo data created: {counts}")

    @app.cli.command("train-model")
    def train_model():
        """Train the demand prediction model on all orders."""
        from app.services.forecasting import train_and_forecast

        run = train_and_forecast(None, None)
        click.echo(f"{run.status}: {run.message}")

    @app.cli.command("backup")
    def backup_cmd():
        """Create a manual database backup."""
        from app.services.backup import create_backup

        click.echo(f"Backup created: {create_backup('manual')}")
