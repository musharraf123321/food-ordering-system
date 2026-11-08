from datetime import datetime

from flask import (
    Blueprint, abort, current_app, flash, jsonify, redirect, render_template,
    request, url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.models import (
    ACTIVE_STATUSES, Cart, CartItem, Category, Favorite, MenuItem, Order,
    OrderItem, Restaurant, User,
)
from app.services import orders as order_service
from app.services.payment import process_payment
from app.utils import EMAIL_RE, home_for, is_safe_next, parse_date, roles_required

customer_bp = Blueprint("customer", __name__)
customer_only = roles_required("customer")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _get_cart():
    cart = current_user.cart
    if cart is None:
        cart = Cart(user_id=current_user.id)
        db.session.add(cart)
        db.session.commit()
    return cart


def _back(default_endpoint, **kwargs):
    nxt = request.form.get("next")
    return redirect(nxt if is_safe_next(nxt) else url_for(default_endpoint, **kwargs))


# ----------------------------------------------------------------------
# Home / dashboard
# ----------------------------------------------------------------------
@customer_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    return redirect(url_for("auth.login"))


@customer_bp.route("/dashboard")
@login_required
def dashboard():
    if not current_user.is_customer:
        return redirect(home_for(current_user))

    uid = current_user.id
    valid = Order.status != "Cancelled"
    total_orders = Order.query.filter_by(user_id=uid).count()
    total_spent = (
        db.session.query(func.coalesce(func.sum(Order.total_amount), 0))
        .filter(Order.user_id == uid, valid).scalar()
    )
    active_orders = Order.query.filter(
        Order.user_id == uid, Order.status.in_(ACTIVE_STATUSES)
    ).count()
    recent_orders = (
        Order.query.filter_by(user_id=uid).order_by(Order.order_date.desc()).limit(5).all()
    )
    favorites = (
        Favorite.query.filter_by(user_id=uid).order_by(Favorite.created_at.desc()).limit(6).all()
    )
    # "Your usual" - the items this customer orders most often
    usual = (
        db.session.query(MenuItem, func.sum(OrderItem.quantity).label("qty"))
        .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.user_id == uid, valid, MenuItem.is_deleted.is_(False))
        .group_by(MenuItem.id)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
        .all()
    )
    return render_template(
        "customer/dashboard.html", total_orders=total_orders, total_spent=total_spent,
        active_orders=active_orders, recent_orders=recent_orders,
        favorites=favorites, usual=usual,
    )


# ----------------------------------------------------------------------
# Restaurants & menu
# ----------------------------------------------------------------------
@customer_bp.route("/restaurants")
@login_required
def restaurants():
    keyword = request.args.get("search", "").strip()
    location = request.args.get("location", "").strip()
    cuisine = request.args.get("cuisine", "").strip()

    q = Restaurant.query
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(db.or_(Restaurant.name.ilike(like), Restaurant.cuisine_type.ilike(like)))
    if location:
        q = q.filter(Restaurant.location == location)
    if cuisine:
        q = q.filter(Restaurant.cuisine_type == cuisine)

    locations = [r[0] for r in db.session.query(Restaurant.location).filter(
        Restaurant.location.isnot(None)).distinct().order_by(Restaurant.location)]
    cuisines = [r[0] for r in db.session.query(Restaurant.cuisine_type).filter(
        Restaurant.cuisine_type.isnot(None)).distinct().order_by(Restaurant.cuisine_type)]

    return render_template(
        "customer/restaurants.html", restaurants=q.order_by(Restaurant.name).all(),
        keyword=keyword, location=location, cuisine=cuisine,
        locations=locations, cuisines=cuisines,
    )


@customer_bp.route("/restaurant/<int:restaurant_id>")
@login_required
def menu(restaurant_id):
    restaurant = db.session.get(Restaurant, restaurant_id)
    if restaurant is None:
        flash("This restaurant's menu is not available.", "danger")
        return redirect(url_for("customer.restaurants"))

    keyword = request.args.get("search", "").strip()
    category_id = request.args.get("category", type=int)

    q = MenuItem.query.filter_by(restaurant_id=restaurant_id, is_deleted=False)
    if keyword:
        q = q.filter(MenuItem.name.ilike(f"%{keyword}%"))
    if category_id:
        q = q.filter_by(category_id=category_id)
    items = q.order_by(MenuItem.category_id, MenuItem.name).all()

    categories = (
        Category.query.join(MenuItem)
        .filter(MenuItem.restaurant_id == restaurant_id, MenuItem.is_deleted.is_(False))
        .distinct().order_by(Category.name).all()
    )
    fav_ids = {f.menu_item_id for f in Favorite.query.filter_by(user_id=current_user.id)}
    return render_template(
        "customer/menu.html", restaurant=restaurant, items=items, categories=categories,
        keyword=keyword, category_id=category_id, fav_ids=fav_ids,
    )


# ----------------------------------------------------------------------
# Favorites
# ----------------------------------------------------------------------
@customer_bp.route("/favorites")
@customer_only
def favorites():
    favs = (
        Favorite.query.filter_by(user_id=current_user.id)
        .order_by(Favorite.created_at.desc()).all()
    )
    favs = [f for f in favs if not f.menu_item.is_deleted]
    return render_template("customer/favorites.html", favorites=favs)


@customer_bp.route("/favorites/toggle/<int:item_id>", methods=["POST"])
@customer_only
def toggle_favorite(item_id):
    item = db.session.get(MenuItem, item_id)
    if item is None or item.is_deleted:
        abort(404)
    fav = Favorite.query.filter_by(user_id=current_user.id, menu_item_id=item_id).first()
    if fav:
        db.session.delete(fav)
        flash(f"'{item.name}' removed from your favorites.", "info")
    else:
        db.session.add(Favorite(user_id=current_user.id, menu_item_id=item_id))
        flash(f"'{item.name}' added to your favorites.", "success")
    db.session.commit()
    return _back("customer.menu", restaurant_id=item.restaurant_id)


# ----------------------------------------------------------------------
# Cart
# ----------------------------------------------------------------------
@customer_bp.route("/cart/add/<int:item_id>", methods=["POST"])
@customer_only
def add_to_cart(item_id):
    item = db.session.get(MenuItem, item_id)
    if item is None or item.is_deleted:
        flash("This item is no longer available.", "danger")
        return redirect(url_for("customer.restaurants"))

    back = lambda: _back("customer.menu", restaurant_id=item.restaurant_id)

    if not item.in_stock:
        flash(f"Sorry, '{item.name}' is out of stock.", "danger")
        return back()

    qty = request.form.get("quantity", 1, type=int) or 1
    if qty < 1:
        flash("Quantity must be at least 1.", "danger")
        return back()

    cart = _get_cart()
    if cart.items and cart.restaurant_id != item.restaurant_id:
        flash("Your cart already has items from another restaurant. "
              "Please clear the cart or checkout first.", "warning")
        return back()

    line = next((i for i in cart.items if i.menu_item_id == item.id), None)
    new_qty = (line.quantity if line else 0) + qty
    if new_qty > item.stock_qty:
        flash(f"Only {item.stock_qty} unit(s) of '{item.name}' are available.", "warning")
        return back()

    if line:
        line.quantity = new_qty
    else:
        db.session.add(CartItem(cart_id=cart.id, menu_item_id=item.id, quantity=qty))
    db.session.commit()
    flash(f"'{item.name}' added to your cart.", "success")
    return back()


@customer_bp.route("/cart")
@customer_only
def view_cart():
    cart = _get_cart()
    removed = False
    for line in list(cart.items):
        if line.menu_item.is_deleted:
            db.session.delete(line)
            removed = True
    if removed:
        db.session.commit()
        flash("Some items in your cart were removed because they are no longer available.", "warning")
        db.session.refresh(cart)
    issues = {l.id for l in cart.items if not l.menu_item.in_stock or l.quantity > l.menu_item.stock_qty}
    return render_template("customer/cart.html", cart=cart, issues=issues)


@customer_bp.route("/cart/update/<int:item_id>", methods=["POST"])
@customer_only
def update_cart(item_id):
    cart = _get_cart()
    line = next((i for i in cart.items if i.menu_item_id == item_id), None)
    if line is None:
        return redirect(url_for("customer.view_cart"))
    qty = request.form.get("quantity", type=int)
    if qty is None or qty < 0:
        flash("Please enter a valid quantity.", "danger")
    elif qty == 0:
        db.session.delete(line)
        db.session.commit()
        flash("Item removed from cart.", "info")
    elif qty > line.menu_item.stock_qty:
        flash(f"Only {line.menu_item.stock_qty} unit(s) of '{line.menu_item.name}' are available.", "warning")
    else:
        line.quantity = qty
        db.session.commit()
        flash("Cart updated.", "success")
    return redirect(url_for("customer.view_cart"))


@customer_bp.route("/cart/remove/<int:item_id>", methods=["POST"])
@customer_only
def remove_from_cart(item_id):
    cart = _get_cart()
    line = next((i for i in cart.items if i.menu_item_id == item_id), None)
    if line:
        db.session.delete(line)
        db.session.commit()
        flash("Item removed from cart.", "info")
    return redirect(url_for("customer.view_cart"))


@customer_bp.route("/cart/clear", methods=["POST"])
@customer_only
def clear_cart():
    cart = _get_cart()
    for line in list(cart.items):
        db.session.delete(line)
    db.session.commit()
    flash("Cart cleared.", "info")
    return redirect(url_for("customer.view_cart"))


# ----------------------------------------------------------------------
# Checkout & orders
# ----------------------------------------------------------------------
@customer_bp.route("/checkout", methods=["GET", "POST"])
@customer_only
def checkout():
    cart = _get_cart()
    if not cart.items:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("customer.view_cart"))

    # every line must still be orderable
    problems = [
        f"'{l.menu_item.name}' is " + ("out of stock." if not l.menu_item.in_stock
                                        else f"limited to {l.menu_item.stock_qty} unit(s).")
        for l in cart.items
        if l.menu_item.is_deleted or not l.menu_item.in_stock or l.quantity > l.menu_item.stock_qty
    ]
    if problems:
        for p in problems:
            flash(p, "danger")
        flash("Please update your cart before checking out.", "warning")
        return redirect(url_for("customer.view_cart"))

    if request.method == "POST":
        address = request.form.get("address", "").strip()
        method = request.form.get("payment_method", "COD")
        notes = request.form.get("notes", "").strip()[:255]

        if not address:
            flash("Please enter a delivery address.", "danger")
            return render_template("customer/checkout.html", cart=cart, form=request.form)

        ok, message = process_payment(
            method, cart.total_amount,
            request.form.get("card_number", ""), request.form.get("expiry", ""),
            request.form.get("cvv", ""),
        )
        if not ok:
            flash(message, "danger")
            return render_template("customer/checkout.html", cart=cart, form=request.form)

        order = Order(
            user_id=current_user.id, restaurant_id=cart.restaurant_id,
            total_amount=cart.total_amount, payment_method=method,
            payment_status="Paid" if method == "Online" else "Pending",
            delivery_address=address, notes=notes or None,
            order_date=datetime.now(), status="Pending",
        )
        for line in cart.items:
            order.items.append(OrderItem(
                menu_item_id=line.menu_item_id, quantity=line.quantity,
                unit_price=line.menu_item.price,
            ))
            line.menu_item.stock_qty -= line.quantity
        db.session.add(order)
        for line in list(cart.items):
            db.session.delete(line)
        if not current_user.address:
            current_user.address = address
        db.session.commit()
        return redirect(url_for("customer.order_confirmation", order_id=order.id))

    return render_template("customer/checkout.html", cart=cart, form={"address": current_user.address or ""})


def _own_order_or_404(order_id):
    order = db.session.get(Order, order_id)
    if order is None or order.user_id != current_user.id:
        abort(404)
    return order


@customer_bp.route("/order-confirmation/<int:order_id>")
@customer_only
def order_confirmation(order_id):
    order = _own_order_or_404(order_id)
    return render_template("customer/order_detail.html", order=order, placed=True)


@customer_bp.route("/orders")
@customer_only
def order_history():
    status = request.args.get("status", "").strip()
    start = parse_date(request.args.get("start"))
    end = parse_date(request.args.get("end"))

    q = Order.query.filter_by(user_id=current_user.id)
    if status:
        q = q.filter_by(status=status)
    if start:
        q = q.filter(Order.order_date >= datetime.combine(start, datetime.min.time()))
    if end:
        q = q.filter(Order.order_date <= datetime.combine(end, datetime.max.time()))
    orders = q.order_by(Order.order_date.desc()).all()
    has_any = Order.query.filter_by(user_id=current_user.id).count() > 0
    return render_template(
        "customer/order_history.html", orders=orders, status=status,
        start=request.args.get("start", ""), end=request.args.get("end", ""),
        has_any=has_any,
    )


@customer_bp.route("/orders/<int:order_id>")
@customer_only
def order_detail(order_id):
    order = _own_order_or_404(order_id)
    return render_template("customer/order_detail.html", order=order, placed=False)


@customer_bp.route("/orders/<int:order_id>/status.json")
@customer_only
def order_status_json(order_id):
    order = _own_order_or_404(order_id)
    return jsonify(status=order.status, payment_status=order.payment_status)


@customer_bp.route("/orders/<int:order_id>/cancel", methods=["POST"])
@customer_only
def cancel_order(order_id):
    order = _own_order_or_404(order_id)
    try:
        order_service.customer_cancel(order)
        db.session.commit()
        flash(f"Order #{order.id} has been cancelled.", "success")
    except order_service.OrderError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("customer.order_detail", order_id=order.id))


@customer_bp.route("/orders/<int:order_id>/reorder", methods=["POST"])
@customer_only
def reorder(order_id):
    order = _own_order_or_404(order_id)
    cart = _get_cart()
    for line in list(cart.items):
        db.session.delete(line)
    added, skipped = 0, []
    for line in order.items:
        item = line.menu_item
        if item.is_deleted or not item.in_stock:
            skipped.append(item.name)
            continue
        db.session.add(CartItem(cart_id=cart.id, menu_item_id=item.id,
                                quantity=min(line.quantity, item.stock_qty)))
        added += 1
    db.session.commit()
    if skipped:
        flash("Some items are unavailable and were skipped: " + ", ".join(skipped), "warning")
    if added:
        flash("Items from your previous order were added to the cart.", "success")
        return redirect(url_for("customer.view_cart"))
    return redirect(url_for("customer.order_history"))


# ----------------------------------------------------------------------
# Profile
# ----------------------------------------------------------------------
@customer_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        errors = []
        if not name:
            errors.append("Name is required.")
        if not EMAIL_RE.match(email):
            errors.append("Please enter a valid email address.")
        else:
            clash = User.query.filter(User.email == email, User.id != current_user.id).first()
            if clash:
                errors.append("That email address is already used by another account.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return redirect(url_for("customer.profile"))
        current_user.name = name
        current_user.email = email
        current_user.phone = request.form.get("phone", "").strip() or None
        current_user.address = request.form.get("address", "").strip() or None
        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("customer.profile"))
    return render_template("customer/profile.html")


@customer_bp.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    min_len = current_app.config["MIN_PASSWORD_LENGTH"]
    if not current_user.check_password(current):
        flash("Your current password is incorrect.", "danger")
    elif len(new) < min_len:
        flash(f"The new password must be at least {min_len} characters long.", "danger")
    elif new != confirm:
        flash("The new passwords do not match.", "danger")
    else:
        current_user.set_password(new)
        db.session.commit()
        flash("Password changed successfully.", "success")
    return redirect(url_for("customer.profile"))
