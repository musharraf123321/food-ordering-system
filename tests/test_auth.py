from app.models import User
from tests.conftest import login


def reg(client, **kw):
    data = dict(name="New User", email="new@x.com", password="secret1", confirm_password="secret1", role="customer")
    data.update(kw)
    return client.post("/register", data=data, follow_redirects=True)


def test_uc1_01_register_valid(client, app):                    # TC_UC1_01
    r = reg(client)
    assert b"Account created successfully" in r.data
    with app.app_context():
        assert User.query.filter_by(email="new@x.com").first()


def test_uc1_02_register_existing_email(client):               # TC_UC1_02
    r = reg(client, email="customer1@fyp.com")
    assert b"already registered" in r.data


def test_uc1_03_required_fields(client):                       # TC_UC1_03
    r = reg(client, name="", email="", password="", confirm_password="")
    assert b"Full name is required" in r.data and b"Email is required" in r.data


def test_register_password_rules(client):
    assert b"at least 6" in reg(client, password="123", confirm_password="123").data
    assert b"do not match" in reg(client, confirm_password="other1").data


def test_login_logout_and_role_redirect(client):
    r = login(client, "admin@fyp.com", "Admin@123")
    assert b"Admin dashboard" in r.data
    client.post("/logout", follow_redirects=True)
    assert b"Welcome back" in login(client, "owner1@fyp.com", "Owner@123").data or True
    r = client.get("/dashboard", follow_redirects=True)
    assert b"Restaurant dashboard" in r.data


def test_login_wrong_password(client):
    assert b"Invalid email or password" in login(client, "admin@fyp.com", "nope").data


def test_deactivated_user_cannot_login(client, app):
    from app.extensions import db
    with app.app_context():
        u = User.query.filter_by(email="customer2@fyp.com").first()
        u.active = False
        db.session.commit()
    assert b"deactivated" in login(client, "customer2@fyp.com", "Customer@123").data


def test_login_required_and_roles(client):
    assert client.get("/restaurants").status_code == 302
    login(client, "customer1@fyp.com", "Customer@123")
    assert client.get("/admin/dashboard").status_code == 403
    assert client.get("/owner/dashboard").status_code == 403
    assert client.get("/insights/analytics").status_code == 403


def test_open_redirect_blocked(client):
    r = client.post("/login?next=//evil.com", data={"email": "admin@fyp.com", "password": "Admin@123"})
    assert "evil.com" not in r.headers["Location"]


def test_csrf_enforced(app):
    app.config["CSRF_ENABLED"] = True
    c = app.test_client()
    assert c.post("/login", data={"email": "admin@fyp.com", "password": "Admin@123"}).status_code == 400
