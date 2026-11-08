import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Application configuration.

    Every value can be overridden with an environment variable, which keeps
    secrets out of the source code when the project is deployed.
    """

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-fyp-2026")

    # ---- Database (SQLite, stored in ./instance) -------------------------
    INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
    DATABASE_PATH = os.environ.get(
        "DATABASE_PATH", os.path.join(INSTANCE_DIR, "food_ordering.db")
    )
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + DATABASE_PATH
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ---- Uploads ---------------------------------------------------------
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB per request
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

    # ---- Backup & restore ------------------------------------------------
    BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(BASE_DIR, "backups"))
    AUTO_BACKUP_ENABLED = True
    AUTO_BACKUP_INTERVAL_HOURS = 24      # scheduled backup frequency
    AUTO_BACKUP_KEEP = 10                # how many scheduled backups to keep

    # ---- Machine learning ------------------------------------------------
    ML_DIR = os.path.join(INSTANCE_DIR, "ml")
    FORECAST_HORIZON_DAYS = 7
    MIN_HISTORY_DAYS = 14                # minimum days of data to train
    STOCK_SAFETY_FACTOR = 1.10           # +10% buffer on recommended stock

    # ---- Business rules --------------------------------------------------
    LOW_STOCK_THRESHOLD = 10
    LOYALTY_POINT_PER_RS = 100           # 1 loyalty point per Rs. 100 spent

    # ---- Security --------------------------------------------------------
    CSRF_ENABLED = True
    MIN_PASSWORD_LENGTH = 6

    # ---- Default admin (auto-created on first run) -----------------------
    DEFAULT_ADMIN_EMAIL = "admin@fyp.com"
    DEFAULT_ADMIN_PASSWORD = "Admin@123"
    DEFAULT_ADMIN_NAME = "System Admin"


class TestConfig(Config):
    TESTING = True
    CSRF_ENABLED = False
    AUTO_BACKUP_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
