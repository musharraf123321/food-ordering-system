"""Export order data to CSV or Excel."""
import io
from datetime import datetime

import pandas as pd

from app.extensions import db
from app.models import ExportLog
from app.services import analytics

EXPORT_COLUMNS = {
    "order_id": "Order ID",
    "order_date": "Order Date",
    "restaurant": "Restaurant",
    "customer": "Customer",
    "status": "Status",
    "payment_method": "Payment Method",
    "category": "Category",
    "item": "Item",
    "quantity": "Quantity",
    "unit_price": "Unit Price (Rs.)",
    "revenue": "Line Total (Rs.)",
}


class ExportError(Exception):
    pass


def export_frame(restaurant_ids, start, end):
    df = analytics.order_lines(restaurant_ids, start, end, include_cancelled=True)
    if df.empty:
        raise ExportError("There is no order data for the selected filters, so nothing was exported.")
    out = df[list(EXPORT_COLUMNS)].rename(columns=EXPORT_COLUMNS)
    out["Order Date"] = out["Order Date"].dt.strftime("%Y-%m-%d %H:%M")
    return out


def to_csv_bytes(frame):
    # utf-8-sig so Excel opens the file with the right encoding
    return frame.to_csv(index=False).encode("utf-8-sig")


def to_xlsx_bytes(frame):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Orders", index=False)
        summary = (
            frame.groupby("Item")
            .agg(Units=("Quantity", "sum"), Revenue=("Line Total (Rs.)", "sum"))
            .sort_values("Units", ascending=False)
            .reset_index()
        )
        summary.to_excel(writer, sheet_name="Item Summary", index=False)
        for sheet in writer.sheets.values():
            for col in sheet.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                sheet.column_dimensions[col[0].column_letter].width = min(width + 3, 40)
    return buf.getvalue()


def build_export(fmt, restaurant_ids, start, end, user_id):
    """Returns (bytes, filename, mimetype) and writes an export log row."""
    if fmt not in ("csv", "xlsx"):
        raise ExportError("Unsupported export format.")
    frame = export_frame(restaurant_ids, start, end)
    try:
        data = to_csv_bytes(frame) if fmt == "csv" else to_xlsx_bytes(frame)
    except Exception as exc:  # pragma: no cover - defensive
        raise ExportError(f"The export could not be created: {exc}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"orders_{stamp}.{fmt}"
    db.session.add(ExportLog(user_id=user_id, format=fmt.upper(), file_name=filename,
                             record_count=len(frame)))
    db.session.commit()
    mimetype = (
        "text/csv" if fmt == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return data, filename, mimetype
