from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import User
from app.utils import EMAIL_RE, home_for, is_safe_next

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))

    form = {}
    if request.method == "POST":
        form = request.form
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        confirm = form.get("confirm_password", "")
        role = form.get("role", "customer")
        if role not in ("customer", "owner"):
            role = "customer"

        errors = []
        if not name:
            errors.append("Full name is required.")
        if not email:
            errors.append("Email is required.")
        elif not EMAIL_RE.match(email):
            errors.append("Please enter a valid email address.")
        min_len = current_app.config["MIN_PASSWORD_LENGTH"]
        if not password:
            errors.append("Password is required.")
        elif len(password) < min_len:
            errors.append(f"Password must be at least {min_len} characters long.")
        elif password != confirm:
            errors.append("Passwords do not match.")
        if email and EMAIL_RE.match(email) and User.query.filter_by(email=email).first():
            errors.append("This email is already registered. Please log in instead.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("auth/register.html", form=form)

        user = User(name=name, email=email, role=role,
                    phone=form.get("phone", "").strip() or None,
                    address=form.get("address", "").strip() or None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Please enter both email and password.", "danger")
            return render_template("auth/login.html")

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if not user.is_active:
                flash("This account has been deactivated. Please contact the administrator.", "danger")
                return render_template("auth/login.html")
            login_user(user)
            nxt = request.args.get("next")
            return redirect(nxt if is_safe_next(nxt) else home_for(user))
        flash("Invalid email or password.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
