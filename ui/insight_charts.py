"""Plotly figures for the F&O insight pages: breadth, overnight/intraday, rotation, gap fills.

Rendering only; every number comes from ``market.breadth``, ``market.session_split``,
``market.rotation`` and ``market.gap_fills``.

Colours: line series use three categorical hues, validated with the dataviz
palette checker against both Streamlit's dark (#0e1117) and light (#ffffff)
surfaces. Up/down polarity uses the repo's existing green/red. The four RRG
quadrants have their own validated set, and every chart also labels its series
(legend or text), so no identity depends on colour alone. One y-scale per panel:
measures with different units get stacked panels, never a second axis.
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from market.gap_fills import BUCKETS
from market.rotation import IMPROVING, LAGGING, LEADING, WEAKENING
from ui.sector_heatmap import DIVERGING_COLOURSCALE

SERIES = ("#3987e5", "#d95926", "#199e70")  # blue, orange, aqua
UP = "#2e9e4f"
DOWN = "#d64545"
QUADRANT_COLOURS = {LEADING: "#199e70", WEAKENING: "#c98500", LAGGING: "#d55181", IMPROVING: "#3987e5"}
REFERENCE = "rgba(137,135,129,0.7)"  # muted ink for 0 / 50% / 100 guides

CONFIG = {"displayModeBar": False}


def _layout(figure: go.Figure, height: int) -> go.Figure:
    figure.update_layout(
        height=height,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        hovermode="x unified",
    )
    return figure


# -- breadth -----------------------------------------------------------------


def breadth_participation(table: pd.DataFrame, short_ma: int, long_ma: int) -> go.Figure:
    """Top: the equal-weight index. Bottom: % of stocks above their short and long averages."""
    figure = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.45, 0.55],
                           subplot_titles=("Equal-weight index (the average stock, start = 100)",
                                           "% of stocks above their moving average"))
    figure.add_trace(go.Scatter(x=table.index, y=table["ew_index"], name="Equal-weight index",
                                line={"color": SERIES[0], "width": 2}, showlegend=False,
                                hovertemplate="%{y:.1f}"), row=1, col=1)
    for column, label, colour in (("pct_above_short", f"Above {short_ma}-day", SERIES[0]),
                                  ("pct_above_long", f"Above {long_ma}-day", SERIES[1])):
        figure.add_trace(go.Scatter(x=table.index, y=table[column], name=label,
                                    line={"color": colour, "width": 2}, hovertemplate="%{y:.0f}%"), row=2, col=1)
    figure.add_hline(y=50, line={"color": REFERENCE, "dash": "dot", "width": 1}, row=2, col=1)
    figure.update_yaxes(range=[0, 100], ticksuffix="%", row=2, col=1)
    return _layout(figure, 560)


def advance_decline(table: pd.DataFrame) -> go.Figure:
    """Top: advances minus declines each day. Bottom: the cumulative A/D line."""
    figure = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                           subplot_titles=("Advances − declines, each day", "A/D line (running total)"))
    net = table["net"]
    figure.add_trace(go.Bar(x=table.index, y=net, name="Net advances", showlegend=False,
                            marker={"color": [UP if v >= 0 else DOWN for v in net]},
                            customdata=table[["advances", "declines"]],
                            hovertemplate="%{y:+d} (%{customdata[0]} up, %{customdata[1]} down)"), row=1, col=1)
    figure.add_trace(go.Scatter(x=table.index, y=table["ad_line"], name="A/D line", showlegend=False,
                                line={"color": SERIES[0], "width": 2}, hovertemplate="%{y:+d}"), row=2, col=1)
    figure.add_hline(y=0, line={"color": REFERENCE, "width": 1}, row=1, col=1)
    return _layout(figure, 480)


def highs_lows(table: pd.DataFrame, days: int) -> go.Figure:
    """New N-day closing highs above the line, new lows below it."""
    figure = go.Figure()
    figure.add_trace(go.Bar(x=table.index, y=table["new_highs"], name=f"New {days}-day highs",
                            marker={"color": UP}, hovertemplate="%{y:.0f} highs"))
    figure.add_trace(go.Bar(x=table.index, y=-table["new_lows"], name=f"New {days}-day lows",
                            marker={"color": DOWN}, customdata=table["new_lows"],
                            hovertemplate="%{customdata:.0f} lows"))
    figure.update_layout(barmode="relative", bargap=0.15)
    figure.add_hline(y=0, line={"color": REFERENCE, "width": 1})
    return _layout(figure, 320)


# -- overnight vs intraday ---------------------------------------------------


def universe_split(frame: pd.DataFrame) -> go.Figure:
    """The average stock's cumulative overnight, intraday and total move."""
    figure = go.Figure()
    for column, colour in zip(("Overnight", "Intraday", "Total"), SERIES):
        figure.add_trace(go.Scatter(x=frame.index, y=frame[column], name=column,
                                    line={"color": colour, "width": 3 if column == "Total" else 2},
                                    hovertemplate="%{y:+.2f}%"))
    figure.add_hline(y=0, line={"color": REFERENCE, "width": 1})
    figure.update_yaxes(ticksuffix="%")
    return _layout(figure, 360)


def split_scatter(summary: pd.DataFrame, label_top: int = 10) -> go.Figure:
    """Each stock at (overnight %, intraday %), coloured by total. The dotted diagonal is a total of 0."""
    if summary.empty:
        return go.Figure()
    limit = max(1.0, summary["total_pct"].abs().quantile(0.95))
    labelled = set(summary["total_pct"].abs().nlargest(label_top).index)
    labelled |= set((summary["overnight_pct"] - summary["intraday_pct"]).abs().nlargest(label_top // 2).index)
    span = max(summary["overnight_pct"].abs().max(), summary["intraday_pct"].abs().max()) * 1.08
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=[-span, span], y=[span, -span], mode="lines", hoverinfo="skip",
                                line={"color": REFERENCE, "dash": "dot", "width": 1}, showlegend=False))
    figure.add_trace(go.Scatter(
        x=summary["overnight_pct"], y=summary["intraday_pct"], mode="markers+text",
        text=[s if s in labelled else "" for s in summary.index], textposition="top center",
        textfont={"size": 10},
        marker={"size": 9, "color": summary["total_pct"], "colorscale": DIVERGING_COLOURSCALE,
                "cmin": -limit, "cmax": limit, "cmid": 0, "line": {"width": 1, "color": "rgba(0,0,0,0.35)"},
                "colorbar": {"title": {"text": "Total"}, "ticksuffix": "%", "thickness": 12}},
        customdata=summary[["total_pct", "pattern", "days"]].assign(symbol=summary.index),
        hovertemplate=("<b>%{customdata[3]}</b><br>Overnight %{x:+.2f}% · Intraday %{y:+.2f}%"
                       "<br>Total %{customdata[0]:+.2f}% over %{customdata[2]} days<br>%{customdata[1]}<extra></extra>"),
        showlegend=False,
    ))
    figure.add_hline(y=0, line={"color": REFERENCE, "width": 1})
    figure.add_vline(x=0, line={"color": REFERENCE, "width": 1})
    figure.update_xaxes(title="Overnight (gaps), compounded", ticksuffix="%", range=[-span, span], zeroline=False)
    figure.update_yaxes(title="Intraday (open to close), compounded", ticksuffix="%", range=[-span, span],
                        zeroline=False)
    figure.update_layout(height=620, margin={"l": 10, "r": 10, "t": 20, "b": 10}, hovermode="closest")
    return figure


# -- relative rotation -------------------------------------------------------


def rotation_chart(latest: pd.DataFrame, trails: pd.DataFrame, label_all: bool = True) -> go.Figure:
    """RRG: a trail per name ending in a labelled dot, coloured by its current quadrant."""
    figure = go.Figure()
    if latest.empty:
        return figure
    x_all = pd.concat([latest["rs_ratio"], trails["rs_ratio"]]) if not trails.empty else latest["rs_ratio"]
    y_all = pd.concat([latest["rs_momentum"], trails["rs_momentum"]]) if not trails.empty else latest["rs_momentum"]
    dx = max(abs(x_all - 100).max() * 1.15, 0.5)
    dy = max(abs(y_all - 100).max() * 1.15, 0.5)
    corners = ((LEADING, 100, 100 + dx, 100, 100 + dy, "right", "top"),
               (WEAKENING, 100, 100 + dx, 100 - dy, 100, "right", "bottom"),
               (LAGGING, 100 - dx, 100, 100 - dy, 100, "left", "bottom"),
               (IMPROVING, 100 - dx, 100, 100, 100 + dy, "left", "top"))
    for name, x0, x1, y0, y1, xanchor, yanchor in corners:
        colour = QUADRANT_COLOURS[name]
        figure.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=colour, opacity=0.07,
                         line={"width": 0}, layer="below")
        figure.add_annotation(x=x1 if xanchor == "right" else x0, y=y1 if yanchor == "top" else y0,
                              text=f"<b>{name}</b>", showarrow=False, xanchor=xanchor, yanchor=yanchor,
                              font={"color": colour, "size": 13})
    for name, group in trails.groupby("name", sort=False):
        if name not in latest.index:
            continue
        colour = QUADRANT_COLOURS[latest.at[name, "quadrant"]]
        figure.add_trace(go.Scatter(x=group["rs_ratio"], y=group["rs_momentum"], mode="lines+markers",
                                    line={"color": colour, "width": 2}, marker={"size": 4, "color": colour},
                                    opacity=0.75, hoverinfo="skip", showlegend=False))
    figure.add_trace(go.Scatter(
        x=latest["rs_ratio"], y=latest["rs_momentum"],
        mode="markers+text" if label_all else "markers",
        text=list(latest.index), textposition="top center", textfont={"size": 11},
        marker={"size": 11, "color": [QUADRANT_COLOURS[q] for q in latest["quadrant"]],
                "line": {"width": 2, "color": "rgba(255,255,255,0.8)"}},
        customdata=latest[["quadrant", "was"]].assign(name=latest.index),
        hovertemplate=("<b>%{customdata[2]}</b>: %{customdata[0]}<br>RS-Ratio %{x:.2f} · RS-Momentum %{y:.2f}"
                       "<br>5 days ago: %{customdata[1]}<extra></extra>"),
        showlegend=False,
    ))
    figure.add_hline(y=100, line={"color": REFERENCE, "width": 1})
    figure.add_vline(x=100, line={"color": REFERENCE, "width": 1})
    figure.update_xaxes(title="RS-Ratio (above 100 = beating the benchmark)", range=[100 - dx, 100 + dx],
                        zeroline=False)
    figure.update_yaxes(title="RS-Momentum (above 100 = edge growing)", range=[100 - dy, 100 + dy], zeroline=False)
    figure.update_layout(height=640, margin={"l": 10, "r": 10, "t": 20, "b": 10}, hovermode="closest")
    return figure


# -- gap fills ---------------------------------------------------------------


def fill_rate_bars(rates: pd.DataFrame) -> go.Figure:
    """Same-day fill rate per gap-size bucket, gap-ups and gap-downs side by side, labelled with n."""
    figure = go.Figure()
    present = set(rates["bucket"].astype(str))
    order = [b[0] for b in BUCKETS if b[0] in present]  # buckets below the chosen threshold are left off
    for direction, colour in (("Gap up", UP), ("Gap down", DOWN)):
        part = rates[rates["direction"] == direction].set_index("bucket").reindex(order)
        figure.add_trace(go.Bar(
            x=order, y=part["filled_pct"], name=direction, marker={"color": colour},
            text=[f"{p:.0f}%<br>n={int(n)}" if n == n else "" for p, n in zip(part["filled_pct"], part["gaps"])],
            textposition="outside", customdata=part["gaps"],
            hovertemplate=f"{direction} %{{x}}: %{{y:.0f}}% filled (%{{customdata}} gaps)<extra></extra>"))
    figure.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08, hovermode="closest")
    figure.update_yaxes(range=[0, 115], ticksuffix="%", title="Filled the same day")
    figure.update_xaxes(title="Gap size")
    return _layout(figure, 380)


def fill_curve_chart(curve: pd.DataFrame) -> go.Figure:
    """Cumulative % of gaps filled by time of day."""
    figure = go.Figure()
    clock = [(pd.Timestamp("2000-01-01 09:15") + pd.Timedelta(minutes=int(m))).strftime("%H:%M") for m in curve.index]
    for direction, colour in (("Gap up", UP), ("Gap down", DOWN)):
        if direction in curve.columns:
            figure.add_trace(go.Scatter(x=clock, y=curve[direction], name=direction,
                                        line={"color": colour, "width": 2}, hovertemplate="%{y:.0f}% filled"))
    figure.update_yaxes(range=[0, 100], ticksuffix="%", title="Filled by this time")
    figure.update_xaxes(title="Time (IST)", nticks=14)
    return _layout(figure, 360)
