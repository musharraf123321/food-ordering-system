"""Plotly figure builders. Each function returns a JSON string that the
templates hand to Plotly.js (served locally, so charts also work offline)."""
import plotly.graph_objects as go

PALETTE = ["#ff6b35", "#f7c548", "#2ec4b6", "#3a86ff", "#8338ec", "#ef476f",
           "#06d6a0", "#118ab2", "#ffd166", "#9b5de5"]
LAYOUT = dict(
    template="plotly_white",
    margin=dict(l=45, r=20, t=50, b=45),
    font=dict(family="Segoe UI, Arial, sans-serif", size=13),
    height=360,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
)


def _finish(fig, title, **extra):
    layout = {**LAYOUT, **extra}          # per-chart settings override the defaults
    fig.update_layout(title=dict(text=title, x=0.02, font=dict(size=16)), **layout)
    return fig.to_json()


def _empty(title):
    fig = go.Figure()
    fig.add_annotation(text="No data for the selected period", showarrow=False,
                       font=dict(size=15, color="#888"), x=0.5, y=0.5, xref="paper", yref="paper")
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _finish(fig, title)


def most_ordered_items(top):
    if top.empty:
        return _empty("Most Ordered Items")
    top = top.sort_values("quantity")
    fig = go.Figure(go.Bar(
        x=top["quantity"], y=top["item"], orientation="h",
        marker_color=PALETTE[0], text=top["quantity"], textposition="outside",
        hovertemplate="%{y}<br>Units sold: %{x}<extra></extra>",
    ))
    fig.update_xaxes(title="Units sold")
    return _finish(fig, "Most Ordered Items", margin=dict(l=150, r=30, t=50, b=45))


def peak_order_times(hours):
    labels = [f"{h:02d}:00" for h in hours.index]
    colors = [PALETTE[0] if v == hours.max() and v > 0 else PALETTE[3] for v in hours.values]
    fig = go.Figure(go.Bar(
        x=labels, y=hours.values, marker_color=colors,
        hovertemplate="%{x}<br>Orders: %{y}<extra></extra>",
    ))
    fig.update_xaxes(title="Hour of day", tickangle=-45)
    fig.update_yaxes(title="Orders")
    return _finish(fig, "Peak Order Times")


def weekday_chart(days):
    fig = go.Figure(go.Bar(x=list(days.index), y=days.values, marker_color=PALETTE[2]))
    fig.update_yaxes(title="Orders")
    return _finish(fig, "Orders by Day of Week")


def popular_categories(cat):
    if cat.empty:
        return _empty("Popular Categories")
    fig = go.Figure(go.Pie(
        labels=cat["category"], values=cat["quantity"], hole=0.45,
        marker=dict(colors=PALETTE), textinfo="label+percent",
        hovertemplate="%{label}<br>Units: %{value}<extra></extra>",
    ))
    return _finish(fig, "Popular Categories")


def order_trend(rep, x_col, title):
    """Orders (bars) and revenue (line) over time - used for daily & monthly."""
    if rep.empty:
        return _empty(title)
    fig = go.Figure()
    fig.add_bar(x=rep[x_col].astype(str), y=rep["orders"], name="Orders", marker_color=PALETTE[3])
    fig.add_scatter(x=rep[x_col].astype(str), y=rep["revenue"], name="Revenue (Rs.)",
                    yaxis="y2", mode="lines+markers", line=dict(color=PALETTE[0], width=3))
    fig.update_layout(
        yaxis=dict(title="Orders"),
        yaxis2=dict(title="Revenue (Rs.)", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", y=1.12, x=0.55),
    )
    return _finish(fig, title)


def forecast_chart(item_name, history, forecast):
    """history / forecast: lists of (date, qty)."""
    fig = go.Figure()
    if history:
        fig.add_scatter(x=[d for d, _ in history], y=[q for _, q in history],
                        mode="lines+markers", name="Actual", line=dict(color=PALETTE[3]))
    if forecast:
        xs = ([history[-1][0]] if history else []) + [d for d, _ in forecast]
        ys = ([history[-1][1]] if history else []) + [q for _, q in forecast]
        fig.add_scatter(x=xs, y=ys, mode="lines+markers", name="Predicted",
                        line=dict(color=PALETTE[0], dash="dash", width=3))
    fig.update_yaxes(title="Units per day")
    return _finish(fig, f"Demand Forecast - {item_name}", legend=dict(orientation="h", y=1.12, x=0.6))


def forecast_totals(rows):
    """Bar chart: predicted units for next N days per item."""
    if not rows:
        return _empty("Predicted Demand (next 7 days)")
    rows = sorted(rows, key=lambda r: r["forecast_total"])[-12:]
    fig = go.Figure()
    fig.add_bar(y=[r["name"] for r in rows], x=[r["forecast_total"] for r in rows],
                orientation="h", name="Predicted demand", marker_color=PALETTE[0])
    fig.add_bar(y=[r["name"] for r in rows], x=[r["stock"] for r in rows],
                orientation="h", name="Current stock", marker_color=PALETTE[2])
    fig.update_layout(barmode="group", legend=dict(orientation="h", y=1.12, x=0.5))
    fig.update_xaxes(title="Units")
    return _finish(fig, "Predicted Demand vs Current Stock (next 7 days)",
                   margin=dict(l=150, r=30, t=60, b=45), height=420)
