from app import create_app
from app.extensions import db
from app.services.seed import seed_default_admin

app = create_app(overrides={"AUTO_BACKUP_ENABLED": False})
with app.app_context():
    db.drop_all()
    db.create_all()
    seed_default_admin()
    print("All data removed. Only the admin account remains.")