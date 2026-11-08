"""Order analytics: data access + aggregation (pandas) for charts & reports."""
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import func

from app.extensions import db
from app.models import MenuItem, Order, OrderItem, Restaurant, Category, User


def _day_bounds(start, end):
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())
    return start_dt, end_dt


def order_lines(restaurant_ids=None, start=None, end=None, include_cancelled=False):
    """One row per order line (order x item) as a DataFrame."""
    q = (
        db.session.query(
            Order.id.label("order_id"),
            Order.order_date,
            Order.status,
            Order.payment_method,
            Order.restaurant_id,
            Restaurant.name.label("restaurant"),
            User.name.label("customer"),
            MenuItem.id.label("item_id"),
            MenuItem.name.label("item"),
            Category.name.label("category"),
            OrderItem.quantity,
            OrderItem.unit_price,
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id)
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .join(User, User.id == Order.user_id)
        .outerjoin(Category, Category.id == MenuItem.category_id)
    )
    if restaurant_ids is not None:
        q = q.filter(Order.restaurant_id.in_(restaurant_ids or [-1]))
    if start and end:
        s, e = _day_bounds(start, end)
        q = q.filter(Order.order_date >= s, Order.order_date <= e)
    if not include_cancelled:
        q = q.filter(Order.status != "Cancelled")
    q = q.order_by(Order.order_date)

    cols = [
        "order_id", "order_date", "status", "payment_method", "restaurant_id",
        "restaurant", "customer", "item_id", "item", "category", "quantity", "unit_price",
    ]
    df = pd.DataFrame([tuple(r) for r in q.all()], columns=cols)
    if df.empty:
        return df
    df["order_date"] = pd.to_datetime(df["order_date"])
    df["category"] = df["category"].fillna("Uncategorised")
    df["revenue"] = df["quantity"] * df["unit_price"]
    return df


# ----------------------------------------------------------------------
# Aggregations
# ----------------------------------------------------------------------
def summary(df):
    if df.empty:
        return {"orders": 0, "revenue": 0.0, "items": 0, "avg_order": 0.0}
    orders = df["order_id"].nunique()
    revenue = float(df["revenue"].sum())
    return {
        "orders": int(orders),
        "revenue": revenue,
        "items": int(df["quantity"].sum()),
        "avg_order": revenue / orders if orders else 0.0,
    }


def top_items(df, n=10):
    if df.empty:
        return pd.DataFrame(columns=["item", "quantity", "revenue"])
    g = df.groupby("item").agg(quantity=("quantity", "sum"), revenue=("revenue", "sum"))
    return g.sort_values("quantity", ascending=False).head(n).reset_index()


def peak_hours(df):
    """Number of orders placed in each hour of the day (0-23)."""
    hours = pd.Series(0, index=range(24), dtype=int)
    if not df.empty:
        per_order = df.drop_duplicates("order_id")
        counts = per_order["order_date"].dt.hour.value_counts()
        for h, c in counts.items():
            hours[int(h)] = int(c)
    return hours


def weekday_pattern(df):
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    out = pd.Series(0, index=names, dtype=int)
    if not df.empty:
        per_order = df.drop_duplicates("order_id")
        counts = per_order["order_date"].dt.dayofweek.value_counts()
        for d, c in counts.items():
            out[names[int(d)]] = int(c)
    return out


def category_share(df):
    if df.empty:
        return pd.DataFrame(columns=["category", "quantity", "revenue"])
    g = df.groupby("category").agg(quantity=("quantity", "sum"), revenue=("revenue", "sum"))
    return g.sort_values("quantity", ascending=False).reset_index()


def daily_report(df):
    if df.empty:
        return pd.DataFrame(columns=["date", "orders", "items", "revenue", "avg_order"])
    d = df.assign(date=df["order_date"].dt.date)
    g = d.groupby("date").agg(
        orders=("order_id", "nunique"), items=("quantity", "sum"), revenue=("revenue", "sum")
    )
    g["avg_order"] = g["revenue"] / g["orders"]
    return g.reset_index()


def monthly_report(df):
    if df.empty:
        return pd.DataFrame(columns=["month", "orders", "items", "revenue", "avg_order"])
    d = df.assign(month=df["order_date"].dt.strftime("%Y-%m"))
    g = d.groupby("month").agg(
        orders=("order_id", "nunique"), items=("quantity", "sum"), revenue=("revenue", "sum")
    )
    g["avg_order"] = g["revenue"] / g["orders"]
    return g.reset_index()


def trending_items(df, window=7, n=8):
    """Compare units sold in the last `window` days with the previous window."""
    if df.empty:
        return pd.DataFrame(columns=["item", "recent", "previous", "change_pct"])
    last_day = df["order_date"].max().normalize()
    recent_start = last_day - timedelta(days=window - 1)
    prev_start = recent_start - timedelta(days=window)
    recent = df[df["order_date"] >= recent_start].groupby("item")["quantity"].sum()
    prev = df[(df["order_date"] >= prev_start) & (df["order_date"] < recent_start)] \
        .groupby("item")["quantity"].sum()
    t = pd.concat([recent.rename("recent"), prev.rename("previous")], axis=1).fillna(0)
    t = t[(t["recent"] > 0) | (t["previous"] > 0)]
    t["change_pct"] = ((t["recent"] - t["previous"]) / t["previous"].where(t["previous"] > 0) * 100)
    t["change_pct"] = t["change_pct"].round(0)
    t = t.sort_values("recent", ascending=False).head(n).reset_index()
    t = t.rename(columns={"index": "item"})
    return t


def order_status_counts(restaurant_ids=None):
    q = db.session.query(Order.status, func.count(Order.id)).group_by(Order.status)
    if restaurant_ids is not None:
        q = q.filter(Order.restaurant_id.in_(restaurant_ids or [-1]))
    return dict(q.all())
