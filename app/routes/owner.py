from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from app.extensions import db
from app.models import (
    ACTIVE_STATUSES, CartItem, Category, MenuItem, Order, OrderItem, Restaurant,
)
from app.services import orders as order_service
from app.utils import (
    delete_image, is_safe_next, parse_date, parse_non_negative_int, parse_positive_float,
    roles_required, save_image,
)

owner_bp = Blueprint("owner", __name__)
owner_only = roles_required("owner")


def _my_restaurants():
    return Restaurant.query.filter_by(owner_id=current_user.id).order_by(Restaurant.name).all()


def _my_restaurant_ids():
    return [r.id for r in _my_restaurants()]


def _own_item_or_404(item_id):
    item = db.session.get(MenuItem, item_id)
    if item is None or item.is_deleted:
        abort(404)
    if item.restaurant_id not in _my_restaurant_ids():
        abort(403)
    return item


def _resolve_category(form):
    """Pick an existing category or create a new one from `new_category`."""
    new_name = form.get("new_category", "").strip()
    if new_name:
        cat = Category.query.filter(func.lower(Category.name) == new_name.lower()).first()
        if not cat:
            cat = Category(name=new_name[:80])
            db.session.add(cat)
            db.session.flush()
        return cat.id
    cat_id = form.get("category_id", type=int)
    return cat_id if cat_id and db.session.get(Category, cat_id) else None


def _validate_item_form(form):
    """Returns (cleaned dict, errors list)."""
    errors, data = [], {}
    name = form.get("name", "").strip()
    if not name:
        errors.append("Item name is required.")
    data["name"] = name[:150]
    data["description"] = form.get("description", "").strip()[:300] or None
    try:
        data["price"] = parse_positive_float(form.get("price"), "Price")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        data["stock_qty"] = parse_non_negative_int(form.get("stock_qty", 0), "Stock quantity")
    except ValueError as exc:
        errors.append(str(exc))
    return data, errors


# ----------------------------------------------------------------------
@owner_bp.route("/dashboard")
@owner_only
def dashboard():
    restaurants = _my_restaurants()
    ids = [r.id for r in restaurants]
    today_start = datetime.combine(date.today(), datetime.min.time())

    base = Order.query.filter(Order.restaurant_id.in_(ids or [-1]))
    todays = base.filter(Order.order_date >= today_start, Order.status != "Cancelled")
    stats = {
        "today_orders": todays.count(),
        "today_revenue": todays.with_entities(func.coalesce(func.sum(Order.total_amount), 0)).scalar(),
        "pending": base.filter(Order.status.in_(ACTIVE_STATUSES)).count(),
        "menu_items": MenuItem.query.filter(
            MenuItem.restaurant_id.in_(ids or [-1]), MenuItem.is_deleted.is_(False)).count(),
    }
    low_stock = [
        m for m in MenuItem.query.filter(
            MenuItem.restaurant_id.in_(ids or [-1]), MenuItem.is_deleted.is_(False)).all()
        if m.stock_status != "In Stock"
    ]
    recent = base.order_by(Order.order_date.desc()).limit(6).all()
    return render_template("owner/dashboard.html", restaurants=restaurants, stats=stats,
                           low_stock=low_stock, recent=recent)


# ----------------------------------------------------------------------
# Menu management (add / edit / delete)
# ----------------------------------------------------------------------
@owner_bp.route("/menu", methods=["GET", "POST"])
@owner_only
def menu():
    restaurants = _my_restaurants()
    categories = Category.query.order_by(Category.name).all()

    if not restaurants:
        flash("You have not been assigned a restaurant yet. Please contact the administrator.", "warning")
        return render_template("owner/manage_menu.html", restaurants=[], items=[], categories=categories)

    if request.method == "POST":
        restaurant_id = request.form.get("restaurant", type=int)
        if restaurant_id not in [r.id for r in restaurants]:
            abort(403)

        data, errors = _validate_item_form(request.form)
        filename = None
        try:
            filename = save_image(request.files.get("image"))
        except ValueError as exc:
            errors.append(str(exc))

        if errors:
            for e in errors:
                flash(e, "danger")
            if filename:
                delete_image(filename)
        else:
            item = MenuItem(
                restaurant_id=restaurant_id, category_id=_resolve_category(request.form),
                image=filename, is_available="is_available" in request.form, **data,
            )
            db.session.add(item)
            db.session.commit()
            flash(f"'{item.name}' was added to the menu.", "success")
            return redirect(url_for("owner.menu"))

    search = request.args.get("search", "").strip()
    q = MenuItem.query.filter(
        MenuItem.restaurant_id.in_([r.id for r in restaurants]), MenuItem.is_deleted.is_(False)
    )
    if search:
        q = q.filter(MenuItem.name.ilike(f"%{search}%"))
    items = q.order_by(MenuItem.restaurant_id, MenuItem.name).all()
    return render_template("owner/manage_menu.html", restaurants=restaurants, items=items,
                           categories=categories, search=search)


@owner_bp.route("/menu/edit/<int:item_id>", methods=["GET", "POST"])
@owner_only
def edit_menu(item_id):
    item = _own_item_or_404(item_id)
    restaurants = _my_restaurants()
    categories = Category.query.order_by(Category.name).all()

    if request.method == "POST":
        restaurant_id = request.form.get("restaurant", type=int)
        if restaurant_id not in [r.id for r in restaurants]:
            abort(403)

        data, errors = _validate_item_form(request.form)
        new_image = None
        try:
            new_image = save_image(request.files.get("image"))
        except ValueError as exc:
            errors.append(str(exc))

        if errors:
            for e in errors:
                flash(e, "danger")
            if new_image:
                delete_image(new_image)
        else:
            item.restaurant_id = restaurant_id
            item.category_id = _resolve_category(request.form)
            item.is_available = "is_available" in request.form
            for key, value in data.items():
                setattr(item, key, value)
            if new_image:
                delete_image(item.image)
                item.image = new_image
            db.session.commit()
            flash("Menu item updated successfully.", "success")
            return redirect(url_for("owner.menu"))

    return render_template("owner/edit_menu.html", item=item, restaurants=restaurants,
                           categories=categories)


@owner_bp.route("/menu/toggle/<int:item_id>", methods=["POST"])
@owner_only
def toggle_item(item_id):
    item = _own_item_or_404(item_id)
    item.is_available = not item.is_available
    db.session.commit()
    flash(f"'{item.name}' is now {'available' if item.is_available else 'unavailable'}.", "info")
    return redirect(url_for("owner.menu"))


@owner_bp.route("/menu/delete/<int:item_id>", methods=["POST"])
@owner_only
def delete_menu(item_id):
    item = _own_item_or_404(item_id)
    name = item.name
    linked_orders = OrderItem.query.filter_by(menu_item_id=item.id).count()

    # Remove the item from every customer's cart in all cases.
    CartItem.query.filter_by(menu_item_id=item.id).delete()

    if linked_orders:
        # Past orders still refer to this item (reports, history, ML data),
        # so it is archived (soft deleted) instead of being erased.
        item.is_deleted = True
        item.is_available = False
        db.session.commit()
        flash(f"'{name}' is linked to {linked_orders} past order line(s), so it was archived "
              "(hidden from customers) instead of permanently deleted. Order history is kept.", "warning")
    else:
        delete_image(item.image)
        db.session.delete(item)
        db.session.commit()
        flash(f"'{name}' was deleted.", "success")
    return redirect(url_for("owner.menu"))


# ----------------------------------------------------------------------
# Customer orders
# ----------------------------------------------------------------------
@owner_bp.route("/orders")
@owner_only
def orders():
    ids = _my_restaurant_ids()
    status = request.args.get("status", "").strip()
    start, end = parse_date(request.args.get("start")), parse_date(request.args.get("end"))

    q = Order.query.filter(Order.restaurant_id.in_(ids or [-1]))
    if status:
        q = q.filter_by(status=status)
    if start:
        q = q.filter(Order.order_date >= datetime.combine(start, datetime.min.time()))
    if end:
        q = q.filter(Order.order_date <= datetime.combine(end, datetime.max.time()))
    page = request.args.get("page", 1, type=int)
    pagination = q.order_by(Order.order_date.desc()).paginate(page=page, per_page=15, error_out=False)
    return render_template(
        "owner/orders.html", pagination=pagination, orders=pagination.items, status=status,
        start=request.args.get("start", ""), end=request.args.get("end", ""),
    )


@owner_bp.route("/orders/<int:order_id>/status", methods=["POST"])
@owner_only
def update_order_status(order_id):
    order = db.session.get(Order, order_id)
    if order is None or order.restaurant_id not in _my_restaurant_ids():
        abort(404)
    try:
        order_service.change_status(order, request.form.get("status", ""))
        db.session.commit()
        flash(f"Order #{order.id} is now '{order.status}'.", "success")
    except order_service.OrderError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    nxt = request.form.get("next")
    return redirect(nxt if is_safe_next(nxt) else url_for("owner.orders"))
