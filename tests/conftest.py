import os
import shutil

import pytest

from app import create_app
from config import TestConfig


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    """Seed one demo database (30 days) that every test then copies."""
    folder = tmp_path_factory.mktemp("template")
    path = str(folder / "template.db")
    app = _make_app(folder, path)
    from app.services.seed import seed_demo_data
    with app.app_context():
        seed_demo_data(days=30)
    return path


def _make_app(folder, db_path):
    folder = str(folder)
    return create_app(TestConfig, {
        "DATABASE_PATH": db_path,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///" + db_path,
        "BACKUP_DIR": os.path.join(folder, "backups"),
        "UPLOAD_FOLDER": os.path.join(folder, "uploads"),
        "ML_DIR": os.path.join(folder, "ml"),
        "INSTANCE_DIR": folder,
    })


@pytest.fixture()
def app(tmp_path, template_db):
    """App with demo data (fresh copy per test)."""
    db_path = str(tmp_path / "test.db")
    shutil.copy(template_db, db_path)
    return _make_app(tmp_path, db_path)


@pytest.fixture()
def empty_app(tmp_path):
    """App with only the default admin (no restaurants / orders)."""
    return _make_app(tmp_path, str(tmp_path / "empty.db"))


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, email, password):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


@pytest.fixture()
def customer(client):
    login(client, "customer1@fyp.com", "Customer@123")
    return client


@pytest.fixture()
def owner(client):
    login(client, "owner1@fyp.com", "Owner@123")
    return client


@pytest.fixture()
def admin(client):
    login(client, "admin@fyp.com", "Admin@123")
    return client
