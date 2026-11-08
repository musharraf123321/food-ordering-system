"""Shared helpers used across the application."""
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta
from functools import wraps

from flask import abort, current_app, flash, redirect, request, session, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


# ----------------------------------------------------------------------
# CSRF protection (lightweight, session based)
# ----------------------------------------------------------------------
def generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(16)
    return session["_csrf_token"]


def csrf_protect():
    """Reject any state-changing request that lacks a valid CSRF token."""
    if not current_app.config.get("CSRF_ENABLED", True):
        return
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        expected = session.get("_csrf_token")
        if not expected or not sent or not secrets.compare_digest(sent, expected):
            abort(400, description="Invalid or missing security token. Please reload the page and try again.")


# ----------------------------------------------------------------------
# Role based access control
# ----------------------------------------------------------------------
def roles_required(*roles):
    """Allow only logged-in users who have one of the given roles."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def home_for(user):
    """Landing page for each role after login."""
    if user.is_admin:
        return url_for("admin.dashboard")
    if user.is_owner:
        return url_for("owner.dashboard")
    return url_for("customer.dashboard")


def is_safe_next(target):
    return bool(target) and target.startswith("/") and not target.startswith("//")


# ----------------------------------------------------------------------
# Image uploads
# ----------------------------------------------------------------------
def save_image(file_storage):
    """Validate and save an uploaded image. Returns the stored file name,
    or None when no file was chosen. Raises ValueError for invalid files."""
    if not file_storage or not file_storage.filename:
        return None
    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]:
        raise ValueError("Invalid image type. Allowed: PNG, JPG, JPEG, GIF, WEBP.")
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    name = f"{uuid.uuid4().hex[:12]}.{ext}"  # unique name: no overwriting
    file_storage.save(os.path.join(folder, name))
    return name


def delete_image(filename):
    if not filename:
        return
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    # Only remove files we created (never the bundled static images).
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


# ----------------------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------------------
def parse_date(value, default=None):
    if not value:
        return default
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return default


def default_range(days=30):
    end = date.today()
    return end - timedelta(days=days - 1), end


def parse_positive_float(value, field="Value"):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number.")
    if number <= 0:
        raise ValueError(f"{field} must be greater than zero.")
    return round(number, 2)


def parse_non_negative_int(value, field="Value"):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a whole number.")
    if number < 0:
        raise ValueError(f"{field} cannot be negative.")
    return number


def flash_errors(errors):
    for e in errors:
        flash(e, "danger")


# ----------------------------------------------------------------------
# Template filters
# ----------------------------------------------------------------------
def money(value):
    try:
        return f"Rs. {float(value):,.0f}" if float(value).is_integer() else f"Rs. {float(value):,.2f}"
    except (TypeError, ValueError):
        return "Rs. 0"


STATUS_BADGES = {
    "Pending": "warning text-dark",
    "Confirmed": "info text-dark",
    "Preparing": "primary",
    "Out for Delivery": "secondary",
    "Delivered": "success",
    "Cancelled": "danger",
    "Paid": "success",
    "Failed": "danger",
    "Refunded": "secondary",
    "In Stock": "success",
    "Low Stock": "warning text-dark",
    "Out of Stock": "danger",
}


def status_badge(status):
    return STATUS_BADGES.get(status, "secondary")


def dt(value, fmt="%d %b %Y, %I:%M %p"):
    return value.strftime(fmt) if value else "—"


def image_url(filename):
    """URL for an uploaded image, or a bundled one in static/images, else None."""
    if not filename:
        return None
    if os.path.isfile(os.path.join(current_app.config["UPLOAD_FOLDER"], filename)):
        return url_for("static", filename=f"uploads/{filename}")
    if os.path.isfile(os.path.join(current_app.static_folder, "images", filename)):
        return url_for("static", filename=f"images/{filename}")
    return None


CATEGORY_EMOJI = {
    "Burgers": "🍔", "Wraps": "🌯", "Sides": "🍟", "Starters": "🍗", "Drinks": "🥤",
    "Desserts": "🍰", "Desi": "🍛", "BBQ": "🍢", "Pizza": "🍕", "Pasta": "🍝",
    "Chinese": "🥡", "Sandwiches": "🥪",
}


def category_emoji(name):
    return CATEGORY_EMOJI.get(name, "🍽️")
