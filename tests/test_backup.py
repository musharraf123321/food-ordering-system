import os
import errno

import pytest

from app.extensions import db
from app.models import Order, Restaurant


def backups(app):
    return sorted(os.listdir(app.config["BACKUP_DIR"])) if os.path.isdir(app.config["BACKUP_DIR"]) else []


def test_uc17_01_manual_backup(admin, app):                       # TC_UC17_01
    r = admin.post("/admin/backup/create", follow_redirects=True)
    assert b"Backup created successfully" in r.data
    assert any(n.startswith("manual_") for n in backups(app))


def test_uc17_02_scheduled_backup(app):                           # TC_UC17_02
    from app.services.backup import run_scheduled_backup_if_due
    with app.app_context():
        name = run_scheduled_backup_if_due()
        assert name.startswith("auto_")
        assert run_scheduled_backup_if_due() is None             # not due again yet


def test_uc17_03_storage_full(admin, app, monkeypatch):           # TC_UC17_03
    import sqlite3

    class Boom(sqlite3.Connection):
        def backup(self, *a, **k):
            raise OSError(errno.ENOSPC, "No space left on device")

    real = sqlite3.connect
    monkeypatch.setattr("app.services.backup.sqlite3.connect", lambda *a, **k: real(*a, factory=Boom, **k))
    r = admin.post("/admin/backup/create", follow_redirects=True)
    assert b"storage is full" in r.data
    assert not any(n.endswith(".db") for n in backups(app))      # no partial file left behind


def test_uc18_01_02_restore_selected_version(admin, app):         # TC_UC18_01 / 02
    from app.services.backup import create_backup
    with app.app_context():
        original = Restaurant.query.count()
        first = create_backup("manual")
        db.session.add(Restaurant(name="Temp Place")); db.session.commit()
        assert Restaurant.query.count() == original + 1
    r = admin.post("/admin/backup/restore", data={"filename": first}, follow_redirects=True)
    assert b"Database restored" in r.data
    with app.app_context():
        assert Restaurant.query.count() == original
    assert any(n.startswith("prerestore_") for n in backups(app))  # safety copy


def test_uc18_03_corrupt_backup(admin, app):                      # TC_UC18_03
    os.makedirs(app.config["BACKUP_DIR"], exist_ok=True)
    bad = os.path.join(app.config["BACKUP_DIR"], "manual_bad.db")
    with open(bad, "wb") as f:
        f.write(b"this is not a sqlite database at all" * 50)
    with app.app_context():
        before = Order.query.count()
    r = admin.post("/admin/backup/restore", data={"filename": "manual_bad.db"}, follow_redirects=True)
    assert b"corrupt" in r.data
    with app.app_context():
        assert Order.query.count() == before                      # nothing changed


def test_restore_rejects_foreign_database(admin, app, tmp_path):
    import sqlite3
    p = os.path.join(app.config["BACKUP_DIR"], "manual_other.db")
    os.makedirs(app.config["BACKUP_DIR"], exist_ok=True)
    c = sqlite3.connect(p); c.execute("create table foo(x)"); c.commit(); c.close()
    r = admin.post("/admin/backup/restore", data={"filename": "manual_other.db"}, follow_redirects=True)
    assert b"not a backup of this system" in r.data


def test_backup_path_traversal_blocked(admin):
    r = admin.get("/admin/backup/download/..%2Fconfig.py", follow_redirects=True)
    assert r.status_code in (200, 404) and b"SECRET_KEY" not in r.data
    r = admin.post("/admin/backup/delete", data={"filename": "../config.py"}, follow_redirects=True)
    assert b"Invalid backup file name" in r.data


def test_upload_and_restore(admin, app):
    from app.services.backup import create_backup
    import io
    with app.app_context():
        name = create_backup("manual")
    data = open(os.path.join(app.config["BACKUP_DIR"], name), "rb").read()
    r = admin.post("/admin/backup/restore", data={"backup_file": (io.BytesIO(data), "mine.db")},
                   content_type="multipart/form-data", follow_redirects=True)
    assert b"Database restored" in r.data
    r = admin.post("/admin/backup/restore", data={"backup_file": (io.BytesIO(b"garbage"), "mine.db")},
                   content_type="multipart/form-data", follow_redirects=True)
    assert b"corrupt" in r.data
