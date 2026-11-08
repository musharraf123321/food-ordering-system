from datetime import date, datetime

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for,
)
from flask_login import current_user
from sqlalchemy import func

from app.extensions import db
from app.models import (
    ACTIVE_STATUSES, BackupLog, CartItem, DemandPrediction, DemandPredictionRun,
    Favorite, MenuItem, Order, OrderItem, Restaurant, User,
)
from app.services import backup as backup_service
from app.services import orders as order_service
from app.utils import (
    delete_image, is_safe_next, parse_date, roles_required, save_image,
)

admin_bp = Blueprint("admin", __name__)
admin_only = roles_required("admin")


# ----------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------
@admin_bp.route("/dashboard")
@admin_only
def dashboard():
    today_start = datetime.combine(date.today(), datetime.min.time())
    valid = Order.status != "Cancelled"
    stats = {
        "restaurants": Restaurant.query.count(),
        "menu_items": MenuItem.query.filter_by(is_deleted=False).count(),
        "customers": User.query.filter_by(role="customer").count(),
        "owners": User.query.filter_by(role="owner").count(),
        "orders": Order.query.count(),
        "today_orders": Order.query.filter(Order.order_date >= today_start, valid).count(),
        "revenue": db.session.query(func.coalesce(func.sum(Order.total_amount), 0))
                   .filter(valid).scalar(),
        "active": Order.query.filter(Order.status.in_(ACTIVE_STATUSES)).count(),
    }
    recent = Order.query.order_by(Order.order_date.desc()).limit(8).all()
    backups = backup_service.list_backups()
    return render_template("admin/dashboard.html", stats=stats, recent=recent,
                           last_backup=backups[0] if backups else None)


# ----------------------------------------------------------------------
# Restaurants
# ----------------------------------------------------------------------
def _restaurant_form(restaurant=None):
    """Validate the restaurant form. Returns (data, errors)."""
    f = request.form
    errors = []
    name = f.get("name", "").strip()
    if not name:
        errors.append("Restaurant name is required.")
    owner_id = f.get("owner_id", type=int)
    if owner_id:
        owner = db.session.get(User, owner_id)
        if owner is None or owner.role != "owner":
            errors.append("Please choose a valid restaurant owner.")
    data = {
        "name": name[:150],
        "description": f.get("description", "").strip()[:300] or None,
        "location": f.get("location", "").strip()[:150] or None,
        "cuisine_type": f.get("cuisine_type", "").strip()[:80] or None,
        "owner_id": owner_id or None,
    }
    return data, errors


@admin_bp.route("/restaurants", methods=["GET", "POST"])
@admin_only
def restaurants():
    owners = User.query.filter_by(role="owner", active=True).order_by(User.name).all()

    if request.method == "POST":
        data, errors = _restaurant_form()
        filename = None
        try:
            filename = save_image(request.files.get("image"))
        except ValueError as exc:
            errors.append(str(exc))
        if errors:
            for e in errors:
                flash(e, "danger")
            delete_image(filename)
        else:
            db.session.add(Restaurant(image=filename, **data))
            db.session.commit()
            flash("Restaurant added successfully.", "success")
            return redirect(url_for("admin.restaurants"))

    items = Restaurant.query.order_by(Restaurant.id.desc()).all()
    order_counts = dict(
        db.session.query(Order.restaurant_id, func.count(Order.id)).group_by(Order.restaurant_id).all()
    )
    return render_template("admin/manage_restaurants.html", restaurants=items, owners=owners,
                           order_counts=order_counts)


@admin_bp.route("/restaurants/edit/<int:restaurant_id>", methods=["GET", "POST"])
@admin_only
def edit_restaurant(restaurant_id):
    restaurant = db.session.get(Restaurant, restaurant_id)
    if restaurant is None:
        abort(404)
    owners = User.query.filter_by(role="owner").order_by(User.name).all()

    if request.method == "POST":
        data, errors = _restaurant_form(restaurant)
        new_image = None
        try:
            new_image = save_image(request.files.get("image"))
        except ValueError as exc:
            errors.append(str(exc))
        if errors:
            for e in errors:
                flash(e, "danger")
            delete_image(new_image)
        else:
            for k, v in data.items():
                setattr(restaurant, k, v)
            if new_image:
                delete_image(restaurant.image)
                restaurant.image = new_image
            db.session.commit()
            flash("Restaurant updated successfully.", "success")
            return redirect(url_for("admin.restaurants"))
    return render_template("admin/edit_restaurant.html", restaurant=restaurant, owners=owners)


@admin_bp.route("/restaurants/delete/<int:restaurant_id>", methods=["POST"])
@admin_only
def delete_restaurant(restaurant_id):
    restaurant = db.session.get(Restaurant, restaurant_id)
    if restaurant is None:
        abort(404)

    item_ids = [i.id for i in restaurant.menu_items]
    order_ids = [o.id for o in Order.query.filter_by(restaurant_id=restaurant.id)]

    # remove everything that points to this restaurant, in a safe order
    if order_ids:
        OrderItem.query.filter(OrderItem.order_id.in_(order_ids)).delete(synchronize_session=False)
    if item_ids:
        OrderItem.query.filter(OrderItem.menu_item_id.in_(item_ids)).delete(synchronize_session=False)
        CartItem.query.filter(CartItem.menu_item_id.in_(item_ids)).delete(synchronize_session=False)
        Favorite.query.filter(Favorite.menu_item_id.in_(item_ids)).delete(synchronize_session=False)
        DemandPrediction.query.filter(DemandPrediction.item_id.in_(item_ids)).delete(synchronize_session=False)
    Order.query.filter_by(restaurant_id=restaurant.id).delete(synchronize_session=False)
    DemandPredictionRun.query.filter_by(restaurant_id=restaurant.id).delete(synchronize_session=False)

    for item in restaurant.menu_items:
        delete_image(item.image)
    delete_image(restaurant.image)

    db.session.delete(restaurant)
    db.session.commit()
    flash("Restaurant and all its menu items and orders were deleted.", "success")
    return redirect(url_for("admin.restaurants"))

# ----------------------------------------------------------------------
# Users
# ----------------------------------------------------------------------
@admin_bp.route("/users")
@admin_only
def users():
    search = request.args.get("search", "").strip()
    role = request.args.get("role", "").strip()
    q = User.query
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(User.name.ilike(like), User.email.ilike(like)))
    if role:
        q = q.filter_by(role=role)
    page = request.args.get("page", 1, type=int)
    pagination = q.order_by(User.id).paginate(page=page, per_page=15, error_out=False)
    return render_template("admin/users.html", pagination=pagination, users=pagination.items,
                           search=search, role=role)


def _other_user_or_redirect(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot change your own account from here.", "warning")
        return None
    return user


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_only
def toggle_user(user_id):
    user = _other_user_or_redirect(user_id)
    if user:
        user.active = not user.active
        db.session.commit()
        flash(f"{user.name}'s account was {'activated' if user.active else 'deactivated'}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/role", methods=["POST"])
@admin_only
def change_role(user_id):
    user = _other_user_or_redirect(user_id)
    if user:
        role = request.form.get("role")
        if role not in ("customer", "owner", "admin"):
            flash("Invalid role.", "danger")
        else:
            if user.role == "owner" and role != "owner":
                Restaurant.query.filter_by(owner_id=user.id).update({"owner_id": None})
            user.role = role
            db.session.commit()
            flash(f"{user.name} is now a(n) {role}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_only
def delete_user(user_id):
    user = _other_user_or_redirect(user_id)
    if user:
        if Order.query.filter_by(user_id=user.id).count():
            flash("This user has placed orders and cannot be deleted. Deactivate the account instead.", "danger")
        else:
            Restaurant.query.filter_by(owner_id=user.id).update({"owner_id": None})
            db.session.delete(user)
            db.session.commit()
            flash("User deleted.", "success")
    return redirect(url_for("admin.users"))


# ----------------------------------------------------------------------
# Orders
# ----------------------------------------------------------------------
@admin_bp.route("/orders")
@admin_only
def orders():
    status = request.args.get("status", "").strip()
    restaurant_id = request.args.get("restaurant", type=int)
    start, end = parse_date(request.args.get("start")), parse_date(request.args.get("end"))

    q = Order.query
    if status:
        q = q.filter_by(status=status)
    if restaurant_id:
        q = q.filter_by(restaurant_id=restaurant_id)
    if start:
        q = q.filter(Order.order_date >= datetime.combine(start, datetime.min.time()))
    if end:
        q = q.filter(Order.order_date <= datetime.combine(end, datetime.max.time()))
    page = request.args.get("page", 1, type=int)
    pagination = q.order_by(Order.order_date.desc()).paginate(page=page, per_page=15, error_out=False)
    return render_template(
        "admin/manage_orders.html", pagination=pagination, orders=pagination.items,
        status=status, restaurant_id=restaurant_id,
        start=request.args.get("start", ""), end=request.args.get("end", ""),
        restaurants=Restaurant.query.order_by(Restaurant.name).all(),
    )


@admin_bp.route("/orders/<int:order_id>/status", methods=["POST"])
@admin_only
def update_order_status(order_id):
    order = db.session.get(Order, order_id)
    if order is None:
        abort(404)
    try:
        order_service.change_status(order, request.form.get("status", ""))
        db.session.commit()
        flash(f"Order #{order.id} is now '{order.status}'.", "success")
    except order_service.OrderError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    nxt = request.form.get("next")
    return redirect(nxt if is_safe_next(nxt) else url_for("admin.orders"))


# ----------------------------------------------------------------------
# Backup & restore
# ----------------------------------------------------------------------
@admin_bp.route("/backup")
@admin_only
def backup():
    logs = BackupLog.query.order_by(BackupLog.id.desc()).limit(12).all()
    return render_template(
        "admin/backup.html", backups=backup_service.list_backups(), logs=logs,
        interval=current_app.config["AUTO_BACKUP_INTERVAL_HOURS"],
    )


@admin_bp.route("/backup/create", methods=["POST"])
@admin_only
def create_backup():
    try:
        name = backup_service.create_backup("manual", current_user.id)
        flash(f"Backup created successfully: {name}", "success")
    except backup_service.BackupError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("admin.backup"))


@admin_bp.route("/backup/download/<filename>")
@admin_only
def download_backup(filename):
    try:
        backup_service.resolve_backup(filename)
    except backup_service.BackupError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.backup"))
    return send_from_directory(backup_service.backup_dir(), filename, as_attachment=True)


@admin_bp.route("/backup/restore", methods=["POST"])
@admin_only
def restore_backup():
    filename = request.form.get("filename", "")
    uploaded = request.files.get("backup_file")
    try:
        if uploaded and uploaded.filename:
            filename = backup_service.save_uploaded_backup(uploaded, current_user.id)
        safety = backup_service.restore_backup(filename, current_user.id)
        flash(f"Database restored from '{filename}'. A safety copy of the previous data "
              f"was saved as '{safety}'.", "success")
    except backup_service.BackupError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("admin.backup"))


@admin_bp.route("/backup/delete", methods=["POST"])
@admin_only
def delete_backup():
    try:
        backup_service.delete_backup(request.form.get("filename", ""))
        flash("Backup deleted.", "info")
    except backup_service.BackupError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("admin.backup"))
