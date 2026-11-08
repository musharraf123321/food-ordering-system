"""Order lifecycle rules shared by customers, restaurant owners and admins."""
from flask import current_app

from app.models import FINAL_STATUSES, ORDER_STATUSES


class OrderError(Exception):
    pass


def restock(order):
    """Give the reserved quantities back to the menu items."""
    for line in order.items:
        if line.menu_item is not None:
            line.menu_item.stock_qty += line.quantity


def award_loyalty(order):
    if order.loyalty_awarded:
        return
    per = current_app.config["LOYALTY_POINT_PER_RS"]
    order.user.loyalty_points += int(order.total_amount // per)
    order.loyalty_awarded = True


def change_status(order, new_status):
    """Apply a status change (caller commits). Raises OrderError if not allowed."""
    if new_status not in ORDER_STATUSES:
        raise OrderError("Invalid order status.")
    if new_status == order.status:
        return order
    if order.status in FINAL_STATUSES:
        raise OrderError(f"This order is already {order.status.lower()} and can no longer be changed.")

    if new_status == "Cancelled":
        restock(order)
        if order.payment_method == "Online" and order.payment_status == "Paid":
            order.payment_status = "Refunded"
    elif new_status == "Delivered":
        order.payment_status = "Paid"
        award_loyalty(order)

    order.status = new_status
    return order


def customer_cancel(order):
    if order.status != "Pending":
        raise OrderError("Only orders that are still Pending can be cancelled.")
    change_status(order, "Cancelled")
