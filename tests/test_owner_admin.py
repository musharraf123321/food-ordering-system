import io

from app.extensions import db
from app.models import MenuItem, Order, OrderItem, Restaurant, User


def item_form(**kw):
    d = dict(restaurant=1, name="Test Dish", price="300", stock_qty="20", new_category="Specials", description="x", is_available="on")
    d.update(kw)
    return d


def test_uc10_01_add_item(owner, app):                            # TC_UC10_01 / UC13_01
    r = owner.post("/owner/menu", data=item_form(), follow_redirects=True)
    assert b"was added to the menu" in r.data
    with app.app_context():
        assert MenuItem.query.filter_by(name="Test Dish").first().category.name == "Specials"


def test_uc10_02_image_later(owner, app):                         # TC_UC10_02
    owner.post("/owner/menu", data=item_form(), follow_redirects=True)
    with app.app_context():
        it = MenuItem.query.filter_by(name="Test Dish").first()
        assert it.image is None
        iid = it.id
    data = item_form(); data["image"] = (io.BytesIO(b"\x89PNG\r\n"), "pic.png")
    r = owner.post(f"/owner/menu/edit/{iid}", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert b"updated successfully" in r.data
    with app.app_context():
        assert db.session.get(MenuItem, iid).image.endswith(".png")


def test_uc10_03_invalid_data(owner):                             # TC_UC10_03
    r = owner.post("/owner/menu", data=item_form(price="-5", name=""), follow_redirects=True)
    assert b"Item name is required" in r.data and b"greater than zero" in r.data
    r = owner.post("/owner/menu", data=item_form(stock_qty="abc"), follow_redirects=True)
    assert b"whole number" in r.data


def test_bad_image_type_rejected(owner):
    d = item_form(); d["image"] = (io.BytesIO(b"x"), "evil.exe")
    assert b"Invalid image type" in owner.post("/owner/menu", data=d, content_type="multipart/form-data", follow_redirects=True).data


def test_uc11_update_and_missing(owner, app):                     # TC_UC11_01-03
    owner.post("/owner/menu", data=item_form(), follow_redirects=True)
    with app.app_context():
        iid = MenuItem.query.filter_by(name="Test Dish").first().id
    owner.post(f"/owner/menu/edit/{iid}", data=item_form(price="999"), follow_redirects=True)
    with app.app_context():
        assert db.session.get(MenuItem, iid).price == 999
    assert owner.get("/owner/menu/edit/999999").status_code == 404


def test_uc12_01_delete_unused_item(owner, app):                  # TC_UC12_01
    owner.post("/owner/menu", data=item_form(), follow_redirects=True)
    with app.app_context():
        iid = MenuItem.query.filter_by(name="Test Dish").first().id
    assert b"was deleted" in owner.post(f"/owner/menu/delete/{iid}", follow_redirects=True).data
    with app.app_context():
        assert db.session.get(MenuItem, iid) is None


def test_uc12_02_03_soft_delete_linked_item(owner, app):          # TC_UC12_02 / 03
    with app.app_context():
        iid = OrderItem.query.join(MenuItem).filter(MenuItem.restaurant_id == 1).first().menu_item_id
    r = owner.post(f"/owner/menu/delete/{iid}", follow_redirects=True)
    assert b"archived" in r.data
    with app.app_context():
        it = db.session.get(MenuItem, iid)
        assert it.is_deleted and OrderItem.query.filter_by(menu_item_id=iid).count() > 0


def test_owner_cannot_touch_other_restaurant(owner, app):
    with app.app_context():
        other = MenuItem.query.filter_by(restaurant_id=2).first().id
    assert owner.post(f"/owner/menu/delete/{other}").status_code == 403
    assert owner.post("/owner/menu", data=item_form(restaurant=2)).status_code == 403


def test_uc14_owner_orders_and_status(owner, app):                # TC_UC14_01-02, status update
    assert b"Customer orders" in owner.get("/owner/orders").data
    r = owner.get("/owner/orders?status=Delivered")
    assert b"Delivered" in r.data
    with app.app_context():
        o = Order.query.filter_by(restaurant_id=1, status="Pending").first() or Order.query.filter_by(restaurant_id=1, status="Confirmed").first()
        oid = o.id
    owner.post(f"/owner/orders/{oid}/status", data={"status": "Preparing"})
    with app.app_context():
        assert db.session.get(Order, oid).status == "Preparing"


def test_uc14_03_no_orders(empty_app):                            # TC_UC14_03
    c = empty_app.test_client()
    c.post("/register", data=dict(name="O", email="o@o.com", password="secret1", confirm_password="secret1", role="owner"))
    c.post("/login", data={"email": "o@o.com", "password": "secret1"})
    assert b"No customer orders" in c.get("/owner/orders").data


def test_delivery_awards_points_and_final_state_locked(admin, app):
    with app.app_context():
        o = Order.query.filter_by(status="Pending").first() or Order.query.filter_by(status="Confirmed").first()
        oid, uid, total = o.id, o.user_id, o.total_amount
        before = db.session.get(User, uid).loyalty_points
    admin.post(f"/admin/orders/{oid}/status", data={"status": "Delivered"})
    with app.app_context():
        assert db.session.get(User, uid).loyalty_points == before + int(total // 100)
    r = admin.post(f"/admin/orders/{oid}/status", data={"status": "Pending"}, follow_redirects=True)
    assert b"can no longer be changed" in r.data


def test_admin_restaurant_crud(admin, app):
    r = admin.post("/admin/restaurants", data={"name": "New Place", "location": "Multan", "cuisine_type": "Cafe"}, follow_redirects=True)
    assert b"added successfully" in r.data
    with app.app_context():
        rid = Restaurant.query.filter_by(name="New Place").first().id
    admin.post(f"/admin/restaurants/edit/{rid}", data={"name": "New Place 2"}, follow_redirects=True)
    assert b"deleted successfully" in admin.post(f"/admin/restaurants/delete/{rid}", follow_redirects=True).data
    # restaurant with orders cannot be deleted
    assert b"cannot be deleted" in admin.post("/admin/restaurants/delete/1", follow_redirects=True).data


def test_admin_user_management(admin, app):
    with app.app_context():
        uid = User.query.filter_by(email="customer3@fyp.com").first().id
    admin.post(f"/admin/users/{uid}/toggle")
    with app.app_context():
        assert db.session.get(User, uid).active is False
    admin.post(f"/admin/users/{uid}/role", data={"role": "owner"})
    with app.app_context():
        assert db.session.get(User, uid).role == "owner"
    assert b"cannot change your own" in admin.post("/admin/users/1/toggle", follow_redirects=True).data
    assert b"Users" in admin.get("/admin/users?search=customer").data
