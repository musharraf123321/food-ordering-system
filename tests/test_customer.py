from app.extensions import db
from app.models import CartItem, Favorite, MenuItem, Order, Restaurant, User


def first_item(app, restaurant_id=1):
    with app.app_context():
        it = MenuItem.query.filter_by(restaurant_id=restaurant_id, is_deleted=False).filter(MenuItem.stock_qty > 20).first()
        return it.id, it.stock_qty, it.price


def test_uc2_01_list_restaurants(customer):                       # TC_UC2_01
    assert b"Ranchers Grill" in customer.get("/restaurants").data


def test_uc2_02_filter_by_location(customer):                     # TC_UC2_02
    r = customer.get("/restaurants?location=Lahore")
    assert b"Spice Bazaar" in r.data and b"Ranchers Grill" not in r.data


def test_uc2_03_no_restaurants(customer):                         # TC_UC2_03
    assert b"No restaurants found" in customer.get("/restaurants?search=zzzzz").data


def test_uc3_01_view_menu(customer):                              # TC_UC3_01
    assert b"Bronco Chicken Burger" in customer.get("/restaurant/1").data


def test_uc3_03_menu_unavailable(customer):                       # TC_UC3_03
    r = customer.get("/restaurant/9999", follow_redirects=True)
    assert b"menu is not available" in r.data


def test_uc4_01_add_to_cart(customer, app):                       # TC_UC4_01
    iid, _, _ = first_item(app)
    r = customer.post(f"/cart/add/{iid}", data={"quantity": 2}, follow_redirects=True)
    assert b"added to your cart" in r.data
    assert b"My Cart" in customer.get("/cart").data


def test_uc4_02_change_quantity(customer, app):                   # TC_UC4_02
    iid, _, price = first_item(app)
    customer.post(f"/cart/add/{iid}", data={"quantity": 1})
    r = customer.post(f"/cart/update/{iid}", data={"quantity": 3}, follow_redirects=True)
    assert b"Cart updated" in r.data
    with app.app_context():
        u = User.query.filter_by(email="customer1@fyp.com").first()
        assert u.cart.total_amount == price * 3


def test_uc4_03_out_of_stock_item(customer, app):                 # TC_UC4_03
    with app.app_context():
        it = MenuItem.query.filter_by(restaurant_id=1, stock_qty=0).first()
        iid = it.id
    r = customer.post(f"/cart/add/{iid}", data={"quantity": 1}, follow_redirects=True)
    assert b"out of stock" in r.data


def test_cannot_exceed_stock(customer, app):
    iid, stock, _ = first_item(app)
    r = customer.post(f"/cart/add/{iid}", data={"quantity": stock + 1}, follow_redirects=True)
    assert b"available" in r.data


def test_cart_single_restaurant_rule(customer, app):
    a, _, _ = first_item(app, 1)
    b, _, _ = first_item(app, 2)
    customer.post(f"/cart/add/{a}", data={"quantity": 1})
    r = customer.post(f"/cart/add/{b}", data={"quantity": 1}, follow_redirects=True)
    assert b"another restaurant" in r.data


def place(client, app, method="COD", **extra):
    iid, stock, price = first_item(app)
    client.post(f"/cart/add/{iid}", data={"quantity": 2})
    data = {"address": "House 1", "payment_method": method}
    data.update(extra)
    return client.post("/checkout", data=data, follow_redirects=True), iid, stock


def test_uc5_01_place_order(customer, app):                       # TC_UC5_01 / TC_UC5_02 (COD)
    r, iid, stock = place(customer, app)
    assert b"placed successfully" in r.data
    with app.app_context():
        assert db.session.get(MenuItem, iid).stock_qty == stock - 2     # stock reserved
        u = User.query.filter_by(email="customer1@fyp.com").first()
        assert u.cart.item_count == 0


def test_uc5_online_success(customer, app):
    r, _, _ = place(customer, app, "Online", card_number="4242 4242 4242 4242", expiry="12/35", cvv="123")
    assert b"placed successfully" in r.data and b"Paid" in r.data


def test_uc5_03_online_payment_fails(customer, app):              # TC_UC5_03
    with app.app_context():
        before = Order.query.count()
    r, iid, stock = place(customer, app, "Online", card_number="4000 0000 0000 0002", expiry="12/35", cvv="123")
    assert b"card was declined" in r.data
    with app.app_context():
        assert Order.query.count() == before                    # no order created
        assert db.session.get(MenuItem, iid).stock_qty == stock   # stock untouched


def test_checkout_requires_address(customer, app):
    iid, _, _ = first_item(app)
    customer.post(f"/cart/add/{iid}", data={"quantity": 1})
    assert b"delivery address" in customer.post("/checkout", data={"address": "", "payment_method": "COD"}).data


def test_uc6_status_view_refresh_and_missing(customer, app):      # TC_UC6_01-03
    place(customer, app)
    with app.app_context():
        oid = Order.query.order_by(Order.id.desc()).first().id
    assert b"Pending" in customer.get(f"/orders/{oid}").data
    assert customer.get(f"/orders/{oid}/status.json").get_json()["status"] == "Pending"
    assert customer.get("/orders/999999").status_code == 404


def test_cannot_view_other_users_order(customer, app):
    with app.app_context():
        other = Order.query.filter(Order.user_id != User.query.filter_by(email="customer1@fyp.com").first().id).first().id
    assert customer.get(f"/orders/{other}").status_code == 404


def test_uc7_history_and_filters(customer):                       # TC_UC7_01-02
    assert b"Order history" in customer.get("/orders").data
    r = customer.get("/orders?status=Delivered")
    assert b"Cancelled</span>" not in r.data
    assert b"No orders match" in customer.get("/orders?start=2000-01-01&end=2000-01-02").data


def test_uc7_03_no_history(empty_app):                            # TC_UC7_03
    c = empty_app.test_client()
    c.post("/register", data=dict(name="Z", email="z@z.com", password="secret1", confirm_password="secret1"))
    c.post("/login", data={"email": "z@z.com", "password": "secret1"})
    assert b"No history available" in c.get("/orders").data


def test_cancel_pending_restores_stock(customer, app):
    _, iid, stock = place(customer, app)
    with app.app_context():
        oid = Order.query.order_by(Order.id.desc()).first().id
    assert b"has been cancelled" in customer.post(f"/orders/{oid}/cancel", follow_redirects=True).data
    with app.app_context():
        assert db.session.get(MenuItem, iid).stock_qty == stock


def test_uc9_favorites(customer, app):                            # TC_UC9_01-03
    assert b"Favorite" in customer.get("/favorites").data
    iid, _, _ = first_item(app)
    with app.app_context():
        uid = User.query.filter_by(email="customer1@fyp.com").first().id
        Favorite.query.filter_by(user_id=uid).delete(); db.session.commit()
    assert b"No favorites yet" in customer.get("/favorites").data
    customer.post(f"/favorites/toggle/{iid}")
    assert b"Remove" in customer.get("/favorites").data
    customer.post(f"/favorites/toggle/{iid}")
    assert b"No favorites yet" in customer.get("/favorites").data


def test_dashboard_shows_orders_and_favorites(customer):
    r = customer.get("/dashboard")
    assert b"Recent orders" in r.data and b"Favorite items" in r.data


def test_profile_email_uniqueness(customer):
    r = customer.post("/profile", data={"name": "A", "email": "customer2@fyp.com"}, follow_redirects=True)
    assert b"already used" in r.data
