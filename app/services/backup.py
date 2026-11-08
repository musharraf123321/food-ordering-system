"""Database backup & restore (SQLite).

* Backups are consistent snapshots made with SQLite's online-backup API, so
  they are safe to take while the application is running.
* Restore validates the file first (integrity check + required tables), makes
  an automatic safety backup of the current data, then copies the backup into
  the live database.
* A small background thread creates scheduled (automatic) backups.
"""
import errno
import os
import re
import sqlite3
import threading
import time
from datetime import datetime

from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import BackupLog

REQUIRED_TABLES = {"users", "restaurants", "menu_items", "orders", "order_items"}
KINDS = ("manual", "auto", "prerestore", "uploaded")


class BackupError(Exception):
    pass


# ----------------------------------------------------------------------
def _db_path():
    return current_app.config["DATABASE_PATH"]


def backup_dir():
    path = current_app.config["BACKUP_DIR"]
    os.makedirs(path, exist_ok=True)
    return path


def _log(action, file_name, path, size, user_id, status="Success", message=None):
    try:
        db.session.add(BackupLog(
            user_id=user_id, action=action, file_name=file_name, file_path=path,
            size_bytes=size, status=status, message=message,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _human_error(exc):
    text = str(exc).lower()
    if getattr(exc, "errno", None) == errno.ENOSPC or "disk is full" in text or "no space" in text:
        return "Backup failed: the storage is full. Free some disk space and try again."
    if isinstance(exc, PermissionError):
        return "Backup failed: permission denied for the backup folder."
    return f"Backup failed: {exc}"


# ----------------------------------------------------------------------
# Create
# ----------------------------------------------------------------------
def create_backup(kind="manual", user_id=None):
    if kind not in KINDS:
        kind = "manual"
    src_path = _db_path()
    if not os.path.isfile(src_path):
        raise BackupError("Backup failed: the database file could not be found.")

    name = f"{kind}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    dest_path = os.path.join(backup_dir(), name)
    src = dst = None
    try:
        src = sqlite3.connect(src_path)
        dst = sqlite3.connect(dest_path)
        src.backup(dst)
    except (OSError, sqlite3.Error) as exc:
        for c in (dst, src):
            if c:
                c.close()
        src = dst = None
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        message = _human_error(exc)
        _log("backup", name, dest_path, 0, user_id, "Failed", message)
        raise BackupError(message)
    finally:
        for c in (dst, src):
            if c:
                c.close()

    size = os.path.getsize(dest_path)
    _log("backup", name, dest_path, size, user_id)
    return name


# ----------------------------------------------------------------------
# List / delete
# ----------------------------------------------------------------------
def list_backups():
    folder = backup_dir()
    rows = []
    for fname in os.listdir(folder):
        if not fname.endswith(".db"):
            continue
        full = os.path.join(folder, fname)
        stat = os.stat(full)
        kind = fname.split("_", 1)[0]
        rows.append({
            "name": fname,
            "kind": kind if kind in KINDS else "other",
            "size_kb": round(stat.st_size / 1024, 1),
            "created": datetime.fromtimestamp(stat.st_mtime),
        })
    rows.sort(key=lambda r: r["created"], reverse=True)
    return rows


def resolve_backup(filename):
    """Map a user supplied name to a real file inside the backup folder."""
    safe = secure_filename(filename or "")
    if not safe or safe != filename or not safe.endswith(".db"):
        raise BackupError("Invalid backup file name.")
    path = os.path.join(backup_dir(), safe)
    if not os.path.isfile(path):
        raise BackupError("The selected backup could not be found.")
    return path


def delete_backup(filename):
    os.remove(resolve_backup(filename))


# ----------------------------------------------------------------------
# Validate / restore
# ----------------------------------------------------------------------
def validate_backup(path):
    """Raise BackupError unless `path` is a healthy copy of this application's DB."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()
            if not ok or ok[0] != "ok":
                raise BackupError("Restore failed: the backup file is corrupt.")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
    except sqlite3.DatabaseError:
        raise BackupError("Restore failed: the backup file is corrupt or is not a valid database.")
    missing = REQUIRED_TABLES - tables
    if missing:
        raise BackupError(
            "Restore failed: this file is not a backup of this system "
            f"(missing tables: {', '.join(sorted(missing))})."
        )


def restore_backup(filename, user_id=None):
    path = resolve_backup(filename)
    validate_backup(path)

    # Safety net: keep the current data so a mistaken restore can be undone.
    safety = create_backup("prerestore", user_id)

    db.session.remove()
    db.engine.dispose()
    src = dst = None
    try:
        src = sqlite3.connect(path)
        dst = sqlite3.connect(_db_path())
        src.backup(dst)
    except (OSError, sqlite3.Error) as exc:
        raise BackupError(f"Restore failed: {exc}")
    finally:
        for c in (dst, src):
            if c:
                c.close()
    db.engine.dispose()
    db.create_all()  # adds any table that did not exist when the backup was taken
    _log("restore", filename, path, os.path.getsize(path), user_id)
    return safety


def save_uploaded_backup(file_storage, user_id=None):
    """Store an uploaded .db file in the backup folder after validating it."""
    if not file_storage or not file_storage.filename:
        raise BackupError("Please choose a backup file to upload.")
    if not file_storage.filename.lower().endswith(".db"):
        raise BackupError("Backup files must have the .db extension.")
    name = f"uploaded_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    path = os.path.join(backup_dir(), name)
    try:
        file_storage.save(path)
    except OSError as exc:
        raise BackupError(_human_error(exc))
    try:
        validate_backup(path)
    except BackupError:
        os.remove(path)
        raise
    return name


# ----------------------------------------------------------------------
# Scheduled backups
# ----------------------------------------------------------------------
def _prune_auto(keep):
    autos = [b for b in list_backups() if b["kind"] == "auto"]
    for old in autos[keep:]:
        try:
            os.remove(os.path.join(backup_dir(), old["name"]))
        except OSError:
            pass


def run_scheduled_backup_if_due():
    """Create an automatic backup if the last one is older than the interval."""
    interval = current_app.config["AUTO_BACKUP_INTERVAL_HOURS"] * 3600
    autos = [b for b in list_backups() if b["kind"] == "auto"]
    if autos and (time.time() - autos[0]["created"].timestamp()) < interval:
        return None
    name = create_backup("auto")
    _prune_auto(current_app.config["AUTO_BACKUP_KEEP"])
    return name


def start_scheduler(app):
    """Background thread: checks every 30 minutes whether a backup is due."""
    if app.config.get("_scheduler_started"):
        return
    app.config["_scheduler_started"] = True

    def loop():
        time.sleep(15)  # let the app finish starting
        while True:
            try:
                with app.app_context():
                    run_scheduled_backup_if_due()
            except Exception as exc:  # never let the thread die
                app.logger.warning("Scheduled backup failed: %s", exc)
            time.sleep(1800)

    threading.Thread(target=loop, name="auto-backup", daemon=True).start()
