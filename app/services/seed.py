"""Demo data generator.

Creates restaurants, owners, customers, menus and ~90 days of realistic order
history (weekly patterns, lunch/dinner peaks, a few cancelled orders) so the
dashboards, reports and the demand-prediction model have data to work with.

Usage:
    python seed_data.py            # add demo data to an empty database
    python seed_data.py --reset    # wipe everything and rebuild demo data
"""
from datetime import datetime, timedelta

import numpy as np
from flask import current_app

from app.extensions import db
from app.models import (
    Category, Favorite, MenuItem, Order, OrderItem, Restaurant, User,
)

OWNER_PASSWORD = "Owner@123"
CUSTOMER_PASSWORD = "Customer@123"

RESTAURANTS = [
    {
        "name": "Ranchers Grill", "location": "Islamabad", "cuisine": "Fast Food",
        "description": "Good fellas eat here! Juicy burgers, crispy chicken and loaded fries.",
        "owner": ("Hamza Rauf", "owner1@fyp.com"), "image": "restuarants.jpg", "base": 13,
        "items": [
            ("Bronco Chicken Burger", "Burgers", 650, "Crispy fried chicken, cheese sauce, lettuce."),
            ("Cronco Spicy Burger", "Burgers", 690, "Extra spicy fried fillet with jalapenos."),
            ("Double Beef Smash", "Burgers", 980, "Two smashed beef patties with cheddar."),
            ("Zinger Wrap", "Wraps", 520, "Zinger strips, coleslaw and garlic mayo."),
            ("Loaded Fries", "Sides", 450, "Fries topped with cheese and chicken."),
            ("Crispy Wings (6 pc)", "Starters", 590, "Hot and crispy wings with dip."),
            ("Chicken Nuggets (8 pc)", "Starters", 420, "Golden nuggets with ketchup."),
            ("Cola 500ml", "Drinks", 120, "Chilled soft drink."),
            ("Mint Margarita", "Drinks", 220, "Fresh mint cooler."),
            ("Chocolate Brownie", "Desserts", 320, "Warm brownie with chocolate sauce."),
        ],
    },
    {
        "name": "Spice Bazaar", "location": "Lahore", "cuisine": "Pakistani",
        "description": "Authentic desi flavours - biryani, karahi and fresh naan.",
        "owner": ("Imran Siddiqui", "owner2@fyp.com"), "image": None, "base": 12,
        "items": [
            ("Chicken Biryani", "Desi", 450, "Aromatic basmati rice with spiced chicken."),
            ("Mutton Karahi (Half)", "Desi", 1650, "Slow cooked in a traditional wok."),
            ("Chicken Handi", "Desi", 1100, "Creamy handi with butter naan."),
            ("Daal Mash", "Desi", 380, "Lentils with garlic tadka."),
            ("Seekh Kabab (4 pc)", "BBQ", 560, "Charcoal grilled minced beef kababs."),
            ("Butter Naan", "Sides", 70, "Fresh tandoori naan."),
            ("Raita", "Sides", 90, "Cool yogurt with cucumber."),
            ("Lassi (Sweet)", "Drinks", 180, "Thick Punjabi lassi."),
            ("Kheer", "Desserts", 230, "Rice pudding with pistachios."),
            ("Gulab Jamun (2 pc)", "Desserts", 200, "Warm syrup-soaked dumplings."),
        ],
    },
    {
        "name": "Napoli Pizzeria", "location": "Islamabad", "cuisine": "Italian",
        "description": "Wood-fired pizzas, creamy pasta and garlic bread.",
        "owner": ("Sana Javed", "owner3@fyp.com"), "image": None, "base": 11,
        "items": [
            ("Margherita Pizza", "Pizza", 1150, "Tomato, mozzarella and basil."),
            ("Fajita Pizza", "Pizza", 1350, "Chicken fajita, peppers and onions."),
            ("Pepperoni Pizza", "Pizza", 1450, "Loaded with beef pepperoni."),
            ("Creamy Alfredo Pasta", "Pasta", 890, "Fettuccine in white sauce."),
            ("Penne Arrabbiata", "Pasta", 820, "Spicy tomato penne."),
            ("Garlic Bread", "Starters", 340, "Toasted with herb butter."),
            ("Caesar Salad", "Starters", 480, "Romaine, croutons and parmesan."),
            ("Lasagna", "Pasta", 980, "Baked layers with beef ragu."),
            ("Iced Tea", "Drinks", 190, "Peach iced tea."),
            ("Tiramisu", "Desserts", 520, "Classic Italian coffee dessert."),
        ],
    },
    {
        "name": "Dragon Wok", "location": "Rawalpindi", "cuisine": "Chinese",
        "description": "Sizzling woks, fresh noodles and crispy starters.",
        "owner": ("Kamran Ali", "owner4@fyp.com"), "image": None, "base": 9,
        "items": [
            ("Chicken Chow Mein", "Chinese", 620, "Stir-fried noodles with vegetables."),
            ("Egg Fried Rice", "Chinese", 480, "Wok fried rice with egg."),
            ("Chicken Manchurian", "Chinese", 780, "Crispy chicken in tangy sauce."),
            ("Kung Pao Chicken", "Chinese", 850, "Peanuts, chilli and spring onion."),
            ("Hot & Sour Soup", "Starters", 320, "Classic spicy soup."),
            ("Spring Rolls (4 pc)", "Starters", 360, "Crispy vegetable rolls."),
            ("Dynamite Prawns", "Starters", 990, "Fried prawns in spicy mayo."),
            ("Szechuan Beef", "Chinese", 920, "Beef strips in Szechuan sauce."),
            ("Green Tea", "Drinks", 110, "Hot jasmine tea."),
            ("Fortune Cookies (3 pc)", "Desserts", 150, "Crisp cookies with a note inside."),
        ],
    },
    {
        "name": "Sweet Tooth Cafe", "location": "Karachi", "cuisine": "Desserts & Beverages",
        "description": "Waffles, shakes, cakes and fresh coffee.",
        "owner": ("Nida Hussain", "owner5@fyp.com"), "image": None, "base": 8,
        "items": [
            ("Nutella Waffle", "Desserts", 540, "Belgian waffle with Nutella."),
            ("Red Velvet Slice", "Desserts", 420, "Cream cheese frosting."),
            ("Chocolate Lava Cake", "Desserts", 480, "Molten centre, served warm."),
            ("Oreo Shake", "Drinks", 390, "Thick cookies and cream shake."),
            ("Mango Smoothie", "Drinks", 360, "Fresh mango and yogurt."),
            ("Cappuccino", "Drinks", 330, "Double shot espresso with foam."),
            ("Iced Latte", "Drinks", 360, "Cold espresso with milk."),
            ("Club Sandwich", "Sandwiches", 650, "Triple decker with fries."),
            ("Chicken Croissant", "Sandwiches", 590, "Buttery croissant with chicken filling."),
            ("Cheesecake", "Desserts", 560, "New York style."),
        ],
    },
    {
        "name": "BBQ Tonight", "location": "Lahore", "cuisine": "BBQ",
        "description": "Charcoal grilled tikka, malai boti and rolls.",
        "owner": ("Faisal Mehmood", "owner6@fyp.com"), "image": None, "base": 10,
        "items": [
            ("Chicken Tikka (Leg)", "BBQ", 480, "Smoky charcoal grilled leg piece."),
            ("Malai Boti (8 pc)", "BBQ", 890, "Creamy marinated boneless chicken."),
            ("Mutton Chops (4 pc)", "BBQ", 1650, "Juicy grilled chops."),
            ("Beef Bihari Kabab", "BBQ", 760, "Tender strips, spicy marinade."),
            ("Paratha Roll", "Wraps", 420, "Tikka wrapped in a flaky paratha."),
            ("Reshmi Kabab (4 pc)", "BBQ", 640, "Silky minced chicken kababs."),
            ("Tandoori Roti", "Sides", 40, "Fresh from the tandoor."),
            ("Green Chutney", "Sides", 60, "Mint and coriander dip."),
            ("Lemonade", "Drinks", 160, "Fresh lemon and mint."),
            ("Zarda", "Desserts", 220, "Sweet saffron rice."),
        ],
    },
]

CUSTOMERS = [
    "Ali Raza", "Sara Khan", "Usman Tariq", "Ayesha Malik", "Bilal Ahmed",
    "Hina Farooq", "Zain Abbas", "Maryam Iqbal", "Hassan Sheikh", "Noor Fatima",
    "Danish Qureshi", "Rabia Aslam",
]

CATEGORY_EMOJI_ORDER = [
    "Burgers", "Wraps", "Sides", "Starters", "Drinks", "Desserts", "Desi", "BBQ",
    "Pizza", "Pasta", "Chinese", "Sandwiches",
]

# Weekday multipliers (Mon..Sun) per category - gives the ML model a pattern to learn.
CATEGORY_DOW = {
    "BBQ": [0.8, 0.8, 0.85, 0.95, 1.4, 1.5, 1.4],
    "Desi": [0.9, 0.85, 0.9, 1.0, 1.3, 1.3, 1.5],
    "Pizza": [0.8, 0.8, 0.9, 1.0, 1.4, 1.5, 1.3],
    "Desserts": [0.9, 0.9, 0.9, 1.0, 1.3, 1.4, 1.3],
    "Drinks": [1.0, 1.0, 1.0, 1.05, 1.1, 1.2, 1.1],
}
DOW_ORDERS = [0.85, 0.85, 0.9, 1.0, 1.3, 1.4, 1.25]  # overall order volume Mon..Sun

HOUR_WEIGHTS = {  # bimodal: lunch + dinner peaks
    11: 3, 12: 8, 13: 12, 14: 8, 15: 4, 16: 3, 17: 4, 18: 6,
    19: 11, 20: 14, 21: 12, 22: 7, 23: 3,
}


def seed_default_admin():
    cfg = current_app.config
    if User.query.filter_by(role="admin").first():
        return
    admin = User(name=cfg["DEFAULT_ADMIN_NAME"], email=cfg["DEFAULT_ADMIN_EMAIL"], role="admin")
    admin.set_password(cfg["DEFAULT_ADMIN_PASSWORD"])
    db.session.add(admin)
    db.session.commit()


def _get_category(name, cache):
    if name not in cache:
        cat = Category.query.filter_by(name=name).first() or Category(name=name)
        db.session.add(cat)
        db.session.flush()
        cache[name] = cat
    return cache[name]


def seed_demo_data(days=90, seed=42):
    """Populate the database. Returns a dict with counts."""
    rng = np.random.default_rng(seed)
    seed_default_admin()
    if Restaurant.query.count():
        raise RuntimeError("The database already has restaurants. Use --reset to rebuild it.")

    # ---- customers ------------------------------------------------------
    customers = []
    for i, name in enumerate(CUSTOMERS, start=1):
        u = User(name=name, email=f"customer{i}@fyp.com", role="customer",
                 phone=f"0300-{1000000 + i * 7919:07d}"[:12],
                 address=f"House {10 + i}, Street {i}, Islamabad")
        u.set_password(CUSTOMER_PASSWORD)
        customers.append(u)
    db.session.add_all(customers)

    # ---- restaurants, owners, menus ------------------------------------
    cat_cache, restaurants, item_weights = {}, [], {}
    for r in RESTAURANTS:
        owner = User(name=r["owner"][0], email=r["owner"][1], role="owner")
        owner.set_password(OWNER_PASSWORD)
        db.session.add(owner)
        db.session.flush()
        rest = Restaurant(name=r["name"], description=r["description"], location=r["location"],
                          cuisine_type=r["cuisine"], image=r["image"], owner_id=owner.id)
        db.session.add(rest)
        db.session.flush()
        weights = rng.lognormal(mean=0, sigma=0.55, size=len(r["items"]))
        for (name, cat, price, desc), w in zip(r["items"], weights):
            item = MenuItem(
                restaurant_id=rest.id, category_id=_get_category(cat, cat_cache).id,
                name=name, description=desc, price=float(price),
                stock_qty=int(rng.integers(20, 110)), is_available=True,
                created_at=datetime.now() - timedelta(days=days + 1),
            )
            db.session.add(item)
            db.session.flush()
            item_weights[item.id] = float(w)
        restaurants.append((rest, r["base"]))
    db.session.commit()

    # a couple of items intentionally low / out of stock for the demo
    items_by_rest = {rest.id: MenuItem.query.filter_by(restaurant_id=rest.id).all()
                     for rest, _ in restaurants}
    first = items_by_rest[restaurants[0][0].id]
    first[-1].stock_qty = 0
    first[-2].stock_qty = 6
    db.session.commit()

    # ---- orders ---------------------------------------------------------
    now = datetime.now()
    today = now.date()
    hours = np.array(list(HOUR_WEIGHTS))
    hour_p = np.array(list(HOUR_WEIGHTS.values()), dtype=float)
    hour_p /= hour_p.sum()

    order_count = 0
    for offset in range(days, -1, -1):
        day = today - timedelta(days=offset)
        is_today = offset == 0
        growth = 0.85 + 0.3 * ((days - offset) / days)          # slow upward trend
        for rest, base in restaurants:
            lam = base * DOW_ORDERS[day.weekday()] * growth
            n_orders = int(rng.poisson(lam * (0.25 if is_today else 1.0)))
            items = items_by_rest[rest.id]
            for _ in range(n_orders):
                hour = int(rng.choice(hours, p=hour_p))
                when = datetime.combine(day, datetime.min.time()).replace(
                    hour=hour, minute=int(rng.integers(0, 60)), second=int(rng.integers(0, 60)))
                if is_today:  # never create orders in the future
                    when = min(when, now - timedelta(minutes=int(rng.integers(1, 90))))
                    if when.date() != today:
                        continue

                probs = np.array([
                    item_weights[i.id] * CATEGORY_DOW.get(i.category.name, [1] * 7)[day.weekday()]
                    for i in items
                ])
                probs /= probs.sum()
                n_lines = int(rng.choice([1, 2, 3, 4], p=[0.35, 0.35, 0.2, 0.1]))
                chosen = rng.choice(len(items), size=min(n_lines, len(items)), replace=False, p=probs)

                customer = customers[int(rng.integers(0, len(customers)))]
                online = rng.random() < 0.35
                order = Order(
                    user_id=customer.id, restaurant_id=rest.id, order_date=when,
                    payment_method="Online" if online else "COD",
                    delivery_address=customer.address,
                )
                total = 0.0
                for idx in chosen:
                    it = items[int(idx)]
                    qty = int(rng.choice([1, 2, 3], p=[0.62, 0.28, 0.10]))
                    order.items.append(OrderItem(menu_item_id=it.id, quantity=qty, unit_price=it.price))
                    total += qty * it.price
                order.total_amount = total

                age_hours = (now - when).total_seconds() / 3600
                if age_hours < 2:
                    order.status = str(rng.choice(["Pending", "Confirmed", "Preparing"]))
                elif age_hours < 4:
                    order.status = "Out for Delivery"
                elif rng.random() < 0.06:
                    order.status = "Cancelled"
                else:
                    order.status = "Delivered"

                if order.status == "Cancelled":
                    order.payment_status = "Refunded" if online else "Pending"
                elif online or order.status == "Delivered":
                    order.payment_status = "Paid"
                else:
                    order.payment_status = "Pending"

                if order.status == "Delivered":
                    points = int(total // current_app.config["LOYALTY_POINT_PER_RS"])
                    customer.loyalty_points += points
                    order.loyalty_awarded = True
                db.session.add(order)
                order_count += 1
        if offset % 15 == 0:
            db.session.flush()
    db.session.commit()

    # ---- favourites -----------------------------------------------------
    all_items = MenuItem.query.all()
    for c in customers:
        picks = rng.choice(len(all_items), size=int(rng.integers(3, 7)), replace=False)
        for p in picks:
            db.session.add(Favorite(user_id=c.id, menu_item_id=all_items[int(p)].id))
    db.session.commit()

    return {
        "restaurants": len(restaurants), "customers": len(customers),
        "menu_items": len(all_items), "orders": order_count,
    }
