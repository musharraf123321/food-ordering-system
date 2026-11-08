import io

import pandas as pd


def test_analytics_page_has_all_charts(admin):
    r = admin.get("/insights/analytics")
    assert r.status_code == 200
    for t in (b"Most Ordered Items", b"Peak Order Times", b"Popular Categories", b"Monthly Orders"):
        assert t in r.data


def test_uc8_dashboard_loads_for_owner_scope(owner):
    assert owner.get("/insights/analytics").status_code == 200
    assert owner.get("/insights/analytics?restaurant=2").status_code == 403


def test_uc8_03_empty_data_handled(empty_app):
    c = empty_app.test_client()
    c.post("/login", data={"email": "admin@fyp.com", "password": "Admin@123"})
    r = c.get("/insights/analytics")
    assert r.status_code == 200 and b"No data for the selected period" in r.data


def test_uc15_daily_monthly_reports(admin):                       # TC_UC15_01-03
    assert b"Daily report" in admin.get("/insights/reports").data
    assert b"Monthly report" in admin.get("/insights/reports?type=monthly").data
    assert b"Daily report" in admin.get("/insights/reports?start=2020-01-01&end=2030-01-01").data
    assert b"No order data is available" in admin.get("/insights/reports?start=2000-01-01&end=2000-01-05").data


def test_report_csv_download(admin):
    r = admin.get("/insights/reports?format=csv")
    assert r.mimetype == "text/csv" and b"Orders" in r.data


def test_uc16_export_csv_and_xlsx(admin):                         # TC_UC16_01-03
    r = admin.get("/insights/export/download?format=csv")
    assert r.mimetype == "text/csv" and r.data.startswith(b"\xef\xbb\xbfOrder ID")
    r = admin.get("/insights/export/download?format=xlsx")
    sheets = pd.read_excel(io.BytesIO(r.data), sheet_name=None)
    assert set(sheets) == {"Orders", "Item Summary"} and len(sheets["Orders"]) > 100
    r = admin.get("/insights/export/download?format=csv&start=2000-01-01&end=2000-01-02", follow_redirects=True)
    assert b"nothing was exported" in r.data
    assert b"CSV" in admin.get("/insights/export").data       # export is logged


def test_owner_export_is_scoped(owner):
    df = pd.read_csv(io.BytesIO(owner.get("/insights/export/download?format=csv").data), encoding="utf-8-sig")
    assert set(df["Restaurant"]) == {"Ranchers Grill"}


def test_uc_prediction_train_and_display(admin):
    r = admin.post("/insights/predictions/train", data={"restaurant": ""}, follow_redirects=True)
    assert b"Model trained successfully" in r.data
    page = admin.get("/insights/predictions")
    assert b"Stock plan" in page.data and b"Recommended stock" in page.data


def test_prediction_needs_enough_data(empty_app):
    c = empty_app.test_client()
    c.post("/login", data={"email": "admin@fyp.com", "password": "Admin@123"})
    r = c.post("/insights/predictions/train", data={"restaurant": ""}, follow_redirects=True)
    assert b"no orders yet" in r.data


def test_forecast_quality_vs_baseline(app):
    from app.services.forecasting import train_and_forecast, forecast_rows
    with app.app_context():
        run = train_and_forecast(None, None)
        assert run.status == "Success" and run.mae is not None
        assert run.mae < run.baseline_mae * 1.25          # not much worse than the naive baseline
        rows = forecast_rows(run)
        assert rows and all(len(r["daily"]) == 7 and r["forecast_total"] >= 0 for r in rows)


def test_plotly_js_served_locally(admin):
    r = admin.get("/plotly.min.js")
    assert r.status_code == 200 and len(r.data) > 100000
