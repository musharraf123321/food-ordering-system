"""Database models.

The schema follows the ERD / Database Design in the project Design Document:
Users, Restaurants, Item_Categories, Menu_Items, Carts, Cart_Items, Orders,
Order_Items, Favorites, Demand_Predictions (+ runs), Order_Data_Export_Log and
Database_Backup_Log.
"""
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db

ROLE_ADMIN = "admin"
ROLE_OWNER = "owner"
ROLE_CUSTOMER = "customer"

ORDER_STATUSES = [
    "Pending",
    "Confirmed",
    "Preparing",
    "Out for Delivery",
    "Delivered",
    "Cancelled",
]
ACTIVE_STATUSES = ["Pending", "Confirmed", "Preparing", "Out for Delivery"]
FINAL_STATUSES = ["Delivered", "Cancelled"]


# ======================================================================
# Users
# ======================================================================
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_CUSTOMER)
    phone = db.Column(db.String(30))
    address = db.Column(db.String(255))
    loyalty_points = db.Column(db.Integer, default=0, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    orders = db.relationship("Order", backref="user", lazy=True)

    # ---- passwords ----------------------------------------------------
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ---- Flask-Login: deactivated accounts cannot log in ----------------
    @property
    def is_active(self):
        return bool(self.active)

    # ---- role helpers ---------------------------------------------------
    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_owner(self):
        return self.role == ROLE_OWNER

    @property
    def is_customer(self):
        return self.role == ROLE_CUSTOMER

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


# ======================================================================
# Restaurants, categories and menu items
# ======================================================================
class Restaurant(db.Model):
    __tablename__ = "restaurants"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(300))
    location = db.Column(db.String(150))
    cuisine_type = db.Column(db.String(80))
    image = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.now)

    owner = db.relationship("User", backref="owned_restaurants")
    menu_items = db.relationship(
        "MenuItem", backref="restaurant", lazy=True, cascade="all, delete-orphan"
    )
    orders = db.relationship("Order", backref="restaurant", lazy=True)

    @property
    def visible_items(self):
        return [m for m in self.menu_items if not m.is_deleted]

    def __repr__(self):
        return f"<Restaurant {self.name}>"


class Category(db.Model):
    __tablename__ = "item_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)

    items = db.relationship("MenuItem", backref="category", lazy=True)

    def __repr__(self):
        return f"<Category {self.name}>"


class MenuItem(db.Model):
    __tablename__ = "menu_items"

    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(
        db.Integer, db.ForeignKey("restaurants.id"), nullable=False, index=True
    )
    category_id = db.Column(db.Integer, db.ForeignKey("item_categories.id"))
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(300))
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(200))
    stock_qty = db.Column(db.Integer, default=50, nullable=False)
    is_available = db.Column(db.Boolean, default=True, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)  # soft delete
    created_at = db.Column(db.DateTime, default=datetime.now)

    favorites = db.relationship(
        "Favorite", backref="menu_item", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def category_name(self):
        return self.category.name if self.category else "Uncategorised"

    @property
    def in_stock(self):
        return self.is_available and self.stock_qty > 0

    @property
    def stock_status(self):
        if not self.is_available or self.stock_qty <= 0:
            return "Out of Stock"
        from flask import current_app

        if self.stock_qty <= current_app.config["LOW_STOCK_THRESHOLD"]:
            return "Low Stock"
        return "In Stock"

    def __repr__(self):
        return f"<MenuItem {self.name}>"


# ======================================================================
# Cart
# ======================================================================
class Cart(db.Model):
    __tablename__ = "carts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship("User", backref=db.backref("cart", uselist=False, cascade="all, delete-orphan"))
    items = db.relationship(
        "CartItem", backref="cart", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def total_amount(self):
        return sum(i.subtotal for i in self.items)

    @property
    def item_count(self):
        return sum(i.quantity for i in self.items)

    @property
    def restaurant_id(self):
        return self.items[0].menu_item.restaurant_id if self.items else None


class CartItem(db.Model):
    __tablename__ = "cart_items"

    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("carts.id"), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    menu_item = db.relationship("MenuItem")

    @property
    def subtotal(self):
        return self.menu_item.price * self.quantity


# ======================================================================
# Orders
# ======================================================================
class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    restaurant_id = db.Column(
        db.Integer, db.ForeignKey("restaurants.id"), nullable=False, index=True
    )
    order_date = db.Column(db.DateTime, default=datetime.now, index=True)
    status = db.Column(db.String(30), default="Pending", nullable=False)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    payment_method = db.Column(db.String(20), default="COD", nullable=False)
    payment_status = db.Column(db.String(20), default="Pending", nullable=False)
    delivery_address = db.Column(db.String(255))
    notes = db.Column(db.String(255))
    loyalty_awarded = db.Column(db.Boolean, default=False, nullable=False)

    items = db.relationship(
        "OrderItem", backref="order", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def item_count(self):
        return sum(i.quantity for i in self.items)

    @property
    def can_cancel(self):
        return self.status == "Pending"

    def __repr__(self):
        return f"<Order {self.id}>"


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    menu_item_id = db.Column(
        db.Integer, db.ForeignKey("menu_items.id"), nullable=False, index=True
    )
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)

    menu_item = db.relationship("MenuItem", backref="order_items")

    @property
    def subtotal(self):
        return self.quantity * self.unit_price


# ======================================================================
# Favorites
# ======================================================================
class Favorite(db.Model):
    __tablename__ = "favorites"
    __table_args__ = (db.UniqueConstraint("user_id", "menu_item_id", name="uq_fav"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)


# ======================================================================
# Demand prediction
# ======================================================================
class DemandPredictionRun(db.Model):
    __tablename__ = "demand_prediction_runs"

    id = db.Column(db.Integer, primary_key=True)
    run_date = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), default="Success")  # Success / Failed
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=True)
    trained_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    model_name = db.Column(db.String(60))
    n_samples = db.Column(db.Integer)
    n_items = db.Column(db.Integer)
    mae = db.Column(db.Float)            # model error on the hold-out period
    baseline_mae = db.Column(db.Float)   # 7-day moving-average error (for comparison)
    message = db.Column(db.String(255))

    predictions = db.relationship(
        "DemandPrediction", backref="run", lazy=True, cascade="all, delete-orphan"
    )


class DemandPrediction(db.Model):
    __tablename__ = "demand_predictions"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(
        db.Integer, db.ForeignKey("demand_prediction_runs.id"), nullable=False, index=True
    )
    item_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"), nullable=False)
    prediction_date = db.Column(db.Date, nullable=False)
    predicted_qty = db.Column(db.Float, nullable=False)

    item = db.relationship("MenuItem")


# ======================================================================
# Logs
# ======================================================================
class ExportLog(db.Model):
    __tablename__ = "order_data_export_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    export_date = db.Column(db.DateTime, default=datetime.now)
    format = db.Column(db.String(10))
    file_name = db.Column(db.String(200))
    record_count = db.Column(db.Integer)

    user = db.relationship("User")


class BackupLog(db.Model):
    __tablename__ = "database_backup_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True)
    backup_date = db.Column(db.DateTime, default=datetime.now)
    action = db.Column(db.String(20), default="backup")  # backup / restore
    file_name = db.Column(db.String(200))
    file_path = db.Column(db.String(400))
    size_bytes = db.Column(db.Integer)
    status = db.Column(db.String(20), default="Success")
    message = db.Column(db.String(255))
