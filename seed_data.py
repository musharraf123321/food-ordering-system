"""Fill the database with demo data.

    python seed_data.py            # only if the database has no restaurants
    python seed_data.py --reset    # wipe everything and rebuild demo data
"""
import sys

from app import create_app
from app.extensions import db
from app.services.seed import seed_demo_data

app = create_app()
with app.app_context():
    if "--reset" in sys.argv:
        db.drop_all()
        db.create_all()
    print("Demo data created:", seed_demo_data())
