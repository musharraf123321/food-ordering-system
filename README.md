# FoodHub - Online Food Ordering System with Demand Prediction

CS619 Final Year Project · Group **S26PROJECTEE24B** · Supervisor: Dr. Muhammad Salman Bashir

A Flask web application where customers browse restaurants and order food, restaurant owners manage menus
and orders, and admins manage the whole system. Past orders feed charts, reports and a scikit-learn model
that predicts future demand so restaurants can plan their stock.

## 1. Run it (Windows / VS Code)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Open **http://127.0.0.1:5000**. The project already contains a ready database
(`instance/food_ordering.db`) with demo data, so everything works immediately.
No internet is needed for charts (Plotly.js is served locally); Bootstrap and Font Awesome load from a CDN.

> Using the old prototype folder? Do **not** copy its database - the schema changed. Use this folder as is.

## 2. Demo accounts

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@fyp.com | Admin@123 |
| Restaurant owner (Ranchers Grill) | owner1@fyp.com | Owner@123 |
| Owners 2-6 | owner2@fyp.com ... owner6@fyp.com | Owner@123 |
| Customer | customer1@fyp.com ... customer12@fyp.com | Customer@123 |

Demo data: 6 restaurants, 60 menu items, 12 customers and ~6,000 orders over 90 days
(weekend peaks, lunch/dinner rush hours) so analytics and prediction have real patterns to show.
Rebuild it any time with `python seed_data.py --reset` (then train the model again from the Demand Prediction page).

**Test card for online payment:** `4242 4242 4242 4242` (any future expiry, any 3-digit CVV) succeeds;
`4000 0000 0000 0002` is declined (shows the payment-failure message).

## 3. Requirements coverage

| Requirement | Where |
|-------------|-------|
| 1. Registration, login, personalised dashboard (order history + favourites) | `routes/auth.py`, `routes/customer.py` -> *Dashboard*, *Favorites* |
| 2. Browse restaurants/items, cart, place order, order history & status | *Restaurants*, *Cart*, *Checkout*, *Orders* (status tracker, cancel, reorder) |
| 2.4 Restaurant admin adds / edits / deletes menu items | `routes/owner.py` -> *Menu* (soft-delete when an item is in past orders) |
| 3. Daily & monthly reports, most ordered items, peak times, popular categories, trends | *Insights -> Analytics* and *Reports* (Plotly charts) |
| 4. Train ML on past orders, predict demand, show it for stock planning | *Insights -> Demand Prediction* (`services/forecasting.py`) |
| 5. Export to CSV / Excel; backup and restore | *Insights -> Export Data*; *Backup* (admin) |

## 4. How the demand prediction works

* **Data:** units sold per item per day, built from past orders (zero-filled for days without sales).
* **Model:** `RandomForestRegressor` (scikit-learn) with features: item, day of week, weekend, month, day of month,
  yesterday's sales, sales 7 days ago, 7- and 14-day rolling averages and the item's running average.
* **Validation:** time-based split (train on older days, test on the latest ~20%). The page shows the model's error (MAE)
  next to a simple 7-day moving-average baseline, so you can see whether the model adds value.
* **Forecast:** recursive 7-day forecast per item -> *Recommended stock = predicted demand + 10%* compared with current stock
  -> "Restock +N" alerts. Predictions are stored in `demand_predictions`; the model (`.joblib`) and the training
  dataset (`.json`, the "ML training data" store from the architecture diagram) are saved in `instance/ml/`.
* A model needs at least 14 days of order history; otherwise a clear message is shown instead of a forecast.
* Forecast dates start the day after the newest order in the database.

## 5. Backup and restore

* *Backup -> Create backup now* makes a consistent snapshot in `backups/` (safe while the app runs).
* An automatic backup is created every 24 h while the server is running (keeps the latest 10).
* *Restore* validates the file first (integrity check + required tables), takes a `prerestore_` safety copy of the
  current data, then restores. Corrupt or foreign files are rejected without changing anything.
  You can also upload a `.db` backup. Storage-full errors are reported and leave no half-written file.

## 6. Project structure

```
run.py  config.py  seed_data.py  requirements.txt
app/
  __init__.py        app factory, CSRF, error pages, CLI commands
  models.py          database models (match the ERD / database design)
  utils.py           CSRF, role checks, uploads, filters
  routes/            auth, customer, owner, admin, insights
  services/          analytics, charts, forecasting (ML), exporter, backup, orders, payment, seed
  templates/         Jinja2 + Bootstrap pages
  static/            css, js, images, uploads
instance/food_ordering.db   SQLite database (with demo data)      instance/ml/  trained models
backups/                    sample backups
tests/                      64 automated tests (pytest)             docs/TEST_CASES.md
```

Useful commands: `flask --app run seed-demo --reset`, `flask --app run train-model`,
`flask --app run backup`, `flask --app run create-admin`, `python -m pytest`.

## 7. Security notes

Passwords are hashed; every form carries a CSRF token; role checks guard every admin/owner page
(owners can only touch their own restaurants); uploads are type-checked and renamed; redirects are validated;
delete/logout actions are POST-only. For real deployment set the `SECRET_KEY` environment variable.
