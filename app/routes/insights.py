"""Analytics, reports, demand prediction and data export.

Shared by restaurant owners (their own restaurants only) and admins (all
restaurants, optionally filtered).
"""
from datetime import timedelta

from flask import (
    Blueprint, Response, abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user

from app.extensions import db
from app.models import ExportLog, MenuItem, Restaurant
from app.services import analytics, charts, exporter, forecasting
from app.utils import default_range, parse_date, roles_required

insights_bp = Blueprint("insights", __name__)
staff_only = roles_required("admin", "owner")


# ----------------------------------------------------------------------
# Scope helpers
# ----------------------------------------------------------------------
def _allowed_restaurants():
    if current_user.is_admin:
        return Restaurant.query.order_by(Restaurant.name).all()
    return Restaurant.query.filter_by(owner_id=current_user.id).order_by(Restaurant.name).all()


def _scope():
    """Returns (allowed, selected_id, ids_filter).

    ids_filter is None for 'all restaurants' (admin only) or a list of ids.
    """
    allowed = _allowed_restaurants()
    allowed_ids = [r.id for r in allowed]
    selected = request.args.get("restaurant", type=int)
    if selected and selected not in allowed_ids:
        abort(403)
    if selected:
        return allowed, selected, [selected]
    if current_user.is_admin:
        return allowed, None, None
    return allowed, None, allowed_ids


def _date_range(days=30):
    d_start, d_end = default_range(days)
    start = parse_date(request.args.get("start"), d_start)
    end = parse_date(request.args.get("end"), d_end)
    if start > end:
        start, end = end, start
    return start, end


# ----------------------------------------------------------------------
# Order visualisation
# ----------------------------------------------------------------------
@insights_bp.route("/analytics")
@staff_only
def analytics_view():
    allowed, selected, ids = _scope()
    start, end = _date_range(30)

    df = analytics.order_lines(ids, start, end)
    summary = analytics.summary(df)
    top = analytics.top_items(df, 10)

    trend_df = analytics.order_lines(ids, end - timedelta(days=13), end)
    trending = analytics.trending_items(trend_df, window=7)

    figs = {
        "top_items": charts.most_ordered_items(top),
        "peak": charts.peak_order_times(analytics.peak_hours(df)),
        "categories": charts.popular_categories(analytics.category_share(df)),
        "weekday": charts.weekday_chart(analytics.weekday_pattern(df)),
        "daily": charts.order_trend(analytics.daily_report(df), "date", "Daily Orders & Revenue"),
        "monthly": charts.order_trend(analytics.monthly_report(df), "month", "Monthly Orders & Revenue"),
    }
    peak = analytics.peak_hours(df)
    peak_hour = f"{int(peak.idxmax()):02d}:00" if peak.max() > 0 else "—"
    cats = analytics.category_share(df)
    return render_template(
        "insights/analytics.html", figs=figs, summary=summary, trending=trending,
        top=top, allowed=allowed, selected=selected, start=start, end=end,
        peak_hour=peak_hour, top_category=cats.iloc[0]["category"] if not cats.empty else "—",
    )


# ----------------------------------------------------------------------
# Daily / monthly reports
# ----------------------------------------------------------------------
@insights_bp.route("/reports")
@staff_only
def reports():
    allowed, selected, ids = _scope()
    kind = request.args.get("type", "daily")
    if kind not in ("daily", "monthly"):
        kind = "daily"
    start, end = _date_range(30 if kind == "daily" else 180)

    df = analytics.order_lines(ids, start, end)
    rep = analytics.daily_report(df) if kind == "daily" else analytics.monthly_report(df)
    key = "date" if kind == "daily" else "month"

    if request.args.get("format") == "csv":
        if rep.empty:
            flash("No order data is available for this period, so no report was generated.", "warning")
            return redirect(url_for("insights.reports", type=kind))
        out = rep.rename(columns={key: kind.capitalize() + " Period", "orders": "Orders", "items": "Items Sold",
                                  "revenue": "Revenue (Rs.)", "avg_order": "Average Order (Rs.)"})
        data = exporter.to_csv_bytes(out.round(2))
        return Response(data, mimetype="text/csv", headers={
            "Content-Disposition": f"attachment; filename={kind}_report_{start}_{end}.csv"})

    if rep.empty:
        flash("No order data is available for the selected period.", "warning")
    return render_template(
        "insights/reports.html", kind=kind, key=key, rows=rep.to_dict("records"),
        summary=analytics.summary(df),
        figure=charts.order_trend(rep, key, f"{kind.capitalize()} Orders & Revenue"),
        top=analytics.top_items(df, 5).to_dict("records"),
        allowed=allowed, selected=selected, start=start, end=end,
    )


# ----------------------------------------------------------------------
# Demand prediction
# ----------------------------------------------------------------------
def _prediction_scope():
    """Forecasts are made per restaurant (or for all restaurants, admin only)."""
    allowed = _allowed_restaurants()
    allowed_ids = [r.id for r in allowed]
    selected = request.values.get("restaurant", type=int)
    if selected and selected not in allowed_ids:
        abort(403)
    if not selected and not current_user.is_admin and allowed_ids:
        selected = allowed_ids[0]
    return allowed, selected


@insights_bp.route("/predictions")
@staff_only
def predictions():
    allowed, selected = _prediction_scope()
    run = forecasting.latest_success(selected)
    last_attempt = forecasting.latest_run(selected)
    rows = forecasting.forecast_rows(run)

    chosen_id = request.args.get("item", type=int)
    chosen = next((r for r in rows if r["item_id"] == chosen_id), rows[0] if rows else None)
    item_fig = None
    if chosen:
        history = forecasting.item_history(selected, chosen["item_id"], 30)
        item_fig = charts.forecast_chart(chosen["name"], history, chosen["daily"])

    return render_template(
        "insights/predictions.html", allowed=allowed, selected=selected, run=run,
        last_attempt=last_attempt, rows=rows, chosen=chosen, item_fig=item_fig,
        totals_fig=charts.forecast_totals(rows),
        restock=[r for r in rows if r["status"] == "Restock needed"],
    )


@insights_bp.route("/predictions/train", methods=["POST"])
@staff_only
def train_model():
    allowed, selected = _prediction_scope()
    if not allowed and not current_user.is_admin:
        flash("You have no restaurant to train a model for.", "warning")
        return redirect(url_for("insights.predictions"))
    run = forecasting.train_and_forecast(selected, current_user.id)
    if run.status == "Success":
        msg = f"Model trained successfully. {run.message}"
        if run.mae is not None and run.baseline_mae is not None:
            msg += f" (hold-out MAE {run.mae} vs. moving-average baseline {run.baseline_mae})"
        flash(msg, "success")
    else:
        flash(run.message, "danger")
    return redirect(url_for("insights.predictions", restaurant=selected or ""))


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------
@insights_bp.route("/export")
@staff_only
def export_page():
    allowed = _allowed_restaurants()
    start, end = _date_range(30)
    q = ExportLog.query
    if not current_user.is_admin:
        q = q.filter_by(user_id=current_user.id)
    logs = q.order_by(ExportLog.id.desc()).limit(10).all()
    return render_template("insights/export.html", allowed=allowed, start=start, end=end, logs=logs)


@insights_bp.route("/export/download")
@staff_only
def export_download():
    _, selected, ids = _scope()
    start, end = _date_range(30)
    fmt = request.args.get("format", "csv").lower()
    try:
        data, filename, mimetype = exporter.build_export(fmt, ids, start, end, current_user.id)
    except exporter.ExportError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("insights.export_page"))
    return Response(data, mimetype=mimetype,
                    headers={"Content-Disposition": f"attachment; filename={filename}"})
