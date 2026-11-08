"""Demand prediction module (machine learning).

Approach
--------
* Training data  : daily units sold per menu item, built from past orders
                   (zero-filled for days with no sales).
* Model          : scikit-learn RandomForestRegressor (non-linear regression).
* Features       : item id, day-of-week, weekend flag, month, day-of-month,
                   lag-1, lag-7, rolling 7 / 14-day means and the item's
                   running average  (a classic time-series -> regression setup).
* Validation     : time-based split - the model is trained on the older days
                   and tested on the most recent days. Its MAE is compared
                   against a simple 7-day moving-average baseline.
* Forecasting    : recursive multi-step forecast for the next N days.
* Output         : stored in `demand_predictions`; the model (.joblib) and the
                   training dataset (.json, the "ML training data" store from
                   the architecture diagram) are saved in instance/ml/.
"""
import json
import math
import os
from datetime import date, datetime, timedelta

import joblib
import numpy as np
import pandas as pd
from flask import current_app
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error

from app.extensions import db
from app.models import DemandPrediction, DemandPredictionRun, MenuItem, Restaurant
from app.services.analytics import order_lines

FEATURES = [
    "item_id", "dow", "is_weekend", "month", "dom",
    "lag_1", "lag_7", "roll_7", "roll_14", "item_mean",
]
MODEL_NAME = "RandomForestRegressor"
KEEP_RUNS_PER_SCOPE = 5


class ForecastError(Exception):
    """Raised when a model cannot be trained (e.g. not enough history)."""


# ----------------------------------------------------------------------
# Data preparation
# ----------------------------------------------------------------------
def build_daily_matrix(restaurant_id=None):
    """DataFrame: index = day, columns = item_id, values = units sold."""
    ids = [restaurant_id] if restaurant_id else None
    df = order_lines(restaurant_ids=ids, include_cancelled=False)
    if df.empty:
        return pd.DataFrame()
    df["day"] = df["order_date"].dt.normalize()
    pivot = df.pivot_table(
        index="day", columns="item_id", values="quantity", aggfunc="sum", fill_value=0
    )
    full_range = pd.date_range(pivot.index.min(), pivot.index.max(), freq="D")
    return pivot.reindex(full_range, fill_value=0).astype(float)


def _item_series(matrix, item_id):
    """Series for one item, trimmed to start at the item's first sale."""
    s = matrix[item_id]
    nz = s[s > 0]
    return s.loc[nz.index[0]:] if len(nz) else s.iloc[0:0]


def _feature_frame(series, item_id):
    s = series.astype(float)
    df = pd.DataFrame({"y": s})
    prev = s.shift(1)
    df["lag_1"] = prev
    df["roll_7"] = prev.rolling(7, min_periods=1).mean()
    df["roll_14"] = prev.rolling(14, min_periods=1).mean()
    df["lag_7"] = s.shift(7).fillna(df["roll_7"])
    df["item_mean"] = prev.expanding().mean()
    df["item_id"] = item_id
    idx = df.index
    df["dow"] = idx.dayofweek
    df["is_weekend"] = (idx.dayofweek >= 5).astype(int)
    df["month"] = idx.month
    df["dom"] = idx.day
    return df.dropna(subset=["lag_1", "item_mean"])


def build_training_frame(matrix):
    frames = []
    for item_id in matrix.columns:
        series = _item_series(matrix, item_id)
        if len(series) >= 3:
            f = _feature_frame(series, int(item_id))
            f.index.name = "day"
            frames.append(f.reset_index())
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _next_features(history, item_id, day):
    """Feature row for `day`, given the item's history up to day-1."""
    h = np.asarray(history, dtype=float)
    roll7 = float(h[-7:].mean())
    return {
        "item_id": item_id,
        "dow": day.weekday(),
        "is_weekend": int(day.weekday() >= 5),
        "month": day.month,
        "dom": day.day,
        "lag_1": float(h[-1]),
        "lag_7": float(h[-7]) if len(h) >= 7 else roll7,
        "roll_7": roll7,
        "roll_14": float(h[-14:].mean()),
        "item_mean": float(h.mean()),
    }


def _new_model():
    return RandomForestRegressor(
        n_estimators=200, max_depth=10, min_samples_leaf=2,
        random_state=42, n_jobs=1,
    )


# ----------------------------------------------------------------------
# Training + forecasting
# ----------------------------------------------------------------------
def _train(matrix):
    """Returns (model, mae, baseline_mae, n_samples)."""
    data = build_training_frame(matrix)
    if data.empty or len(data) < 20:
        raise ForecastError("Not enough order history to train the model.")

    days = np.sort(data["day"].unique())
    val_days = max(7, int(len(days) * 0.2))
    mae = baseline_mae = None
    if len(days) >= val_days + 7:
        cutoff = days[-val_days]
        train, test = data[data["day"] < cutoff], data[data["day"] >= cutoff]
        if len(train) >= 20 and len(test) > 0:
            check = _new_model().fit(train[FEATURES], train["y"])
            mae = float(mean_absolute_error(test["y"], check.predict(test[FEATURES])))
            baseline_mae = float(mean_absolute_error(test["y"], test["roll_7"]))

    model = _new_model().fit(data[FEATURES], data["y"])
    return model, mae, baseline_mae, int(len(data)), data


def _forecast(model, matrix, horizon):
    """Recursive forecast. Returns {item_id: [(date, qty), ...]}."""
    last_day = matrix.index.max().date()
    out = {}
    for item_id in matrix.columns:
        series = _item_series(matrix, item_id)
        if len(series) < 3:
            continue
        history = list(series.values)
        preds = []
        for step in range(1, horizon + 1):
            day = last_day + timedelta(days=step)
            row = pd.DataFrame([_next_features(history, int(item_id), day)])[FEATURES]
            qty = max(0.0, float(model.predict(row)[0]))
            qty = round(qty, 1)
            preds.append((day, qty))
            history.append(qty)
        out[int(item_id)] = preds
    return out


def _scope_key(restaurant_id):
    return str(restaurant_id) if restaurant_id else "all"


def _save_artifacts(model, data, restaurant_id):
    folder = current_app.config["ML_DIR"]
    os.makedirs(folder, exist_ok=True)
    key = _scope_key(restaurant_id)
    joblib.dump(model, os.path.join(folder, f"model_{key}.joblib"), compress=3)
    snapshot = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "scope": key,
        "features": FEATURES,
        "rows": [
            {"day": d.strftime("%Y-%m-%d"), "item_id": int(i), "units": float(y)}
            for d, i, y in zip(data["day"], data["item_id"], data["y"])
        ],
    }
    with open(os.path.join(folder, f"training_{key}.json"), "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh)


def train_and_forecast(restaurant_id=None, user_id=None):
    """Train a model on past orders, forecast the next days and store the result.

    Always returns a DemandPredictionRun. On problems (e.g. too little data)
    the run has status 'Failed' and a human readable message.
    """
    horizon = current_app.config["FORECAST_HORIZON_DAYS"]
    min_days = current_app.config["MIN_HISTORY_DAYS"]

    run = DemandPredictionRun(
        restaurant_id=restaurant_id, trained_by=user_id, model_name=MODEL_NAME
    )
    try:
        matrix = build_daily_matrix(restaurant_id)
        if matrix.empty:
            raise ForecastError("There are no orders yet, so the model cannot be trained.")
        if len(matrix) < min_days:
            raise ForecastError(
                f"Only {len(matrix)} day(s) of order history found. "
                f"At least {min_days} days are needed to train the model."
            )

        model, mae, baseline_mae, n_samples, data = _train(matrix)
        forecasts = _forecast(model, matrix, horizon)

        existing = {
            m.id for m in MenuItem.query.filter(MenuItem.id.in_(list(forecasts))).all()
            if not m.is_deleted
        }
        run.status = "Success"
        run.n_samples = n_samples
        run.n_items = len(existing)
        run.mae = round(mae, 3) if mae is not None else None
        run.baseline_mae = round(baseline_mae, 3) if baseline_mae is not None else None
        run.message = f"Model trained on {len(matrix)} days of history; forecast for {horizon} days."
        db.session.add(run)
        db.session.flush()
        for item_id, preds in forecasts.items():
            if item_id not in existing:
                continue
            for day, qty in preds:
                db.session.add(DemandPrediction(
                    run_id=run.id, item_id=item_id, prediction_date=day, predicted_qty=qty
                ))
        _prune_old_runs(restaurant_id)
        db.session.commit()
        try:
            _save_artifacts(model, data, restaurant_id)
        except OSError:
            pass  # artifacts are optional; the predictions are already in the database
    except ForecastError as exc:
        db.session.rollback()
        run = DemandPredictionRun(
            restaurant_id=restaurant_id, trained_by=user_id, model_name=MODEL_NAME,
            status="Failed", message=str(exc),
        )
        db.session.add(run)
        db.session.commit()
    return run


def _prune_old_runs(restaurant_id):
    q = DemandPredictionRun.query.filter_by(restaurant_id=restaurant_id)
    runs = q.order_by(DemandPredictionRun.id.desc()).all()
    for old in runs[KEEP_RUNS_PER_SCOPE - 1:]:
        db.session.delete(old)


# ----------------------------------------------------------------------
# Reading results
# ----------------------------------------------------------------------
def latest_run(restaurant_id=None):
    return (
        DemandPredictionRun.query.filter_by(restaurant_id=restaurant_id)
        .order_by(DemandPredictionRun.id.desc())
        .first()
    )


def latest_success(restaurant_id=None):
    return (
        DemandPredictionRun.query.filter_by(restaurant_id=restaurant_id, status="Success")
        .order_by(DemandPredictionRun.id.desc())
        .first()
    )


def forecast_rows(run):
    """One row per item with its daily forecast and a stock recommendation."""
    if not run or run.status != "Success":
        return []
    factor = current_app.config["STOCK_SAFETY_FACTOR"]
    by_item = {}
    for p in DemandPrediction.query.filter_by(run_id=run.id).order_by(DemandPrediction.prediction_date):
        by_item.setdefault(p.item_id, []).append(p)

    rows = []
    for item_id, preds in by_item.items():
        item = db.session.get(MenuItem, item_id)
        if item is None or item.is_deleted:
            continue
        total = round(sum(p.predicted_qty for p in preds), 1)
        recommended = math.ceil(total * factor)
        stock = item.stock_qty
        rows.append({
            "item_id": item_id,
            "name": item.name,
            "restaurant": item.restaurant.name,
            "category": item.category_name,
            "stock": stock,
            "daily": [(p.prediction_date, p.predicted_qty) for p in preds],
            "forecast_total": total,
            "avg_daily": round(total / len(preds), 1),
            "recommended_stock": recommended,
            "shortfall": max(0, recommended - stock),
            "status": "Restock needed" if stock < recommended else "Stock OK",
        })
    rows.sort(key=lambda r: r["forecast_total"], reverse=True)
    return rows


def item_history(restaurant_id, item_id, days=30):
    matrix = build_daily_matrix(restaurant_id)
    if matrix.empty or item_id not in matrix.columns:
        return []
    s = _item_series(matrix, item_id).tail(days)
    return [(d.date(), float(v)) for d, v in s.items()]
