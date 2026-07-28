"""
EMDASH :: app.py

THE DASHBOARD. Reads ONLY through core.py; math via signals.py.
Styling lives in /assets/emdash.css (Dash auto-loads it). This file holds
STRUCTURE + LOGIC; the CSS holds LOOK. Change colours/spacing in the CSS,
change behaviour here.

TABS
    1. NEWS     -- Kanban board (group by Country / Topic / Tier), de-duped,
                   with source domain shown on each card.
    2. COUNTRY  -- stat tiles + FX & indicator charts + a small-multiples
                   grid of every macro indicator, with a transform toggle.

RUN
    pip install dash plotly pandas
    python news_ingest.py
    python app.py            # -> http://127.0.0.1:9001
"""
from __future__ import annotations

import re
import urllib.parse

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output

import config
import core
import signals as sig

try:
    from news_ingest import topic_of
except Exception:
    def topic_of(_):
        return "general"

P = config.PALETTE
F = config.FONTS
PORT = 9001

TOPIC_LABELS = {
    "monetary_policy": "Monetary Policy", "inflation": "Inflation",
    "growth": "Growth", "politics": "Politics", "markets": "Markets",
    "general": "General",
}
TRANSFORMS = ["Level", "YoY", "Momentum (20)", "Z-score (20)"]
NAME_BY_ISO = {i: n for i, n, *_ in config.COUNTRIES}


# ===================================================================
# DATA HELPERS  (all reads via core.py)
# ===================================================================
def _domain(url: str) -> str:
    """Turn a URL into a clean site name: 'reuters.com', 'bankofcanada.ca'."""
    try:
        net = urllib.parse.urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


def _norm(text: str) -> str:
    """Normalise a headline for de-dup: lowercase, collapse spaces/punct."""
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def load_news(limit: int = 1500) -> pd.DataFrame:
    """Read headlines, add topic + source domain, and DE-DUPLICATE near
    -identical headlines (same story wired by many sites). Keeps the first
    and records how many duplicates were folded in (`dupes`)."""
    try:
        conn = core.get_conn()
        df = pd.read_sql(
            "SELECT ts, source_id, tier, iso3_tags, headline, url "
            "FROM news ORDER BY ts DESC LIMIT ?", conn, params=(limit,))
        conn.close()
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return df

    df["topic"] = df["headline"].map(topic_of)
    df["domain"] = df["url"].map(_domain)
    df["_key"] = df["iso3_tags"].fillna("") + "|" + df["headline"].map(_norm)

    # collapse duplicates: keep first (most recent), count the rest
    counts = df.groupby("_key")["url"].transform("size")
    df["dupes"] = counts - 1
    df = df.drop_duplicates("_key", keep="first").drop(columns="_key")
    return df


def macro_indicators() -> list[str]:
    return list(config.WB_INDICATORS.keys()) + list(config.DBN_SERIES.keys())


def _periods_per_year(s: pd.Series) -> int:
    if len(s) < 3:
        return 1
    gap = s.index.to_series().diff().dt.days.median()
    if gap <= 2:   return 252
    if gap <= 10:  return 52
    if gap <= 45:  return 12
    if gap <= 120: return 4
    return 1


def apply_transform(s: pd.Series, name: str) -> pd.Series:
    if name == "YoY":
        return sig.yoy(s, periods=_periods_per_year(s))
    if name.startswith("Momentum"):
        return sig.momentum(s, periods=20)
    if name.startswith("Z-score"):
        return sig.zscore(s, window=20)
    return s


# ===================================================================
# FIGURES
# ===================================================================
def _fig(title: str, height: int = 320) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color=P["navy1"])),
        template="plotly_white",
        font=dict(family=F["ui"], color=P["ink"], size=11),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=44, r=16, t=42, b=32), height=height,
        colorway=[P["navy2"], P["gold"], P["navy3"], P["good"], P["bad"]],
        xaxis=dict(gridcolor="#EEF0F4"), yaxis=dict(gridcolor="#EEF0F4"),
    )
    return fig


def macro_fig(iso3, indicator, transform):
    df = core.get_series(iso3, indicator)
    fig = _fig(f"{indicator} · {transform}")
    if df is None or df.empty:
        fig.add_annotation(text="no data — run ingest.py", showarrow=False,
                           font=dict(color=P["muted"]))
        return fig
    s = df.set_index("date")["value"]
    y = apply_transform(s, transform)
    fig.add_trace(go.Scatter(x=y.index, y=y.values, mode="lines",
                             line=dict(width=2), fill="tozeroy",
                             fillcolor="rgba(4,25,140,.06)"))
    if transform.startswith("Z-score"):
        fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    return fig


def fx_fig(iso3, transform):
    df = core.get_market(iso3, "FX")
    fig = _fig(f"FX (LCY per USD) · {transform}")
    if df is None or df.empty:
        fig.add_annotation(text="no FX (peg / n.a.)", showarrow=False,
                           font=dict(color=P["muted"]))
        return fig
    s = df.set_index("date")["value"]
    y = apply_transform(s, transform)
    fig.add_trace(go.Scatter(x=y.index, y=y.values, mode="lines",
                             line=dict(width=2, color=P["gold"])))
    return fig


def mini_fig(iso3, indicator):
    """Small chart for the indicator grid (always Level, compact)."""
    df = core.get_series(iso3, indicator)
    fig = _fig(indicator, height=200)
    fig.update_layout(margin=dict(l=40, r=10, t=30, b=24))
    if df is None or df.empty:
        fig.add_annotation(text="—", showarrow=False, font=dict(color=P["muted"]))
        return fig
    s = df.set_index("date")["value"]
    fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines",
                             line=dict(width=1.6)))
    return fig


# ===================================================================
# NEWS RENDERING
# ===================================================================
def _news_card(row):
    tier = row["tier"] or "?"
    src = row["domain"] or row["source_id"] or ""
    meta = [html.Span(src, className="emd-news-src"),
            html.Span("·"), html.Span(str(row["ts"])[:16])]
    if row.get("dupes", 0) > 0:
        meta.append(html.Span(f"+{int(row['dupes'])} more",
                              className="emd-news-dupe"))
    top = [html.Span(tier, className=f"emd-tier emd-tier--{tier}")]
    if row["iso3_tags"]:
        top.append(html.Span(row["iso3_tags"], className="emd-flag"))
    return html.Div([
        html.Div(top, className="emd-news-top"),
        html.A(row["headline"], href=row["url"], target="_blank",
               className="emd-news-title"),
        html.Div(meta, className="emd-news-meta"),
    ], className="emd-news")


def _kanban_keys(row, group_by):
    if group_by == "Topic":
        return [TOPIC_LABELS.get(row["topic"], "General")]
    if group_by == "Tier":
        return [f"Tier {row['tier']}" if row["tier"] else "Tier ?"]
    tags = [t for t in (row["iso3_tags"] or "").split(",") if t]
    return tags or ["(untagged)"]


def news_board(group_by, desk):
    df = load_news()
    if df.empty:
        return html.Div("No news yet — run  python news_ingest.py",
                        style={"padding": "28px", "color": P["muted"]})
    desk_iso = None
    if desk and desk != "ALL":
        desk_iso = {c[0] for c in config.COUNTRIES if c[2] == desk}

    cols: dict[str, list] = {}
    for _, row in df.iterrows():
        for key in _kanban_keys(row, group_by):
            if desk_iso is not None and group_by == "Country" and key not in desk_iso:
                continue
            cols.setdefault(key, []).append(row)

    board = []
    for col in sorted(cols):
        rows = cols[col][:30]
        title = f"{col} — {NAME_BY_ISO[col]}" if col in NAME_BY_ISO else col
        board.append(html.Div([
            html.Div([html.Span(title),
                      html.Span(str(len(cols[col])), className="count")],
                     className="emd-col-head"),
            html.Div([_news_card(r) for r in rows], className="emd-col-body"),
        ], className="emd-col"))
    return html.Div(board, className="emd-board")


# ===================================================================
# COUNTRY RENDERING
# ===================================================================
def stat_tiles(iso3):
    tiles = []
    for ind in config.WB_INDICATORS:
        df = core.get_series(iso3, ind)
        if df is None or df.empty:
            val, date = "—", ""
        else:
            last = df.dropna().iloc[-1]
            val = f"{last['value']:,.1f}"
            date = str(last["date"])[:10]
        tiles.append(html.Div([
            html.Div(ind, className="emd-stat-label"),
            html.Div(val, className="emd-stat-value"),
            html.Div(date, className="emd-stat-date"),
        ], className="emd-stat"))
    return html.Div(tiles, className="emd-stat-row")


def indicator_grid(iso3):
    cards = [html.Div(dcc.Graph(figure=mini_fig(iso3, ind),
                                config={"displayModeBar": False}),
                      className="emd-card")
             for ind in config.WB_INDICATORS]
    return html.Div(cards, className="emd-grid-mini")


# ===================================================================
# APP
# ===================================================================
app = Dash(__name__, title="EMDASH")
server = app.server

app.layout = html.Div([
    # ---- header ----
    html.Div([
        html.Div(["EMD", html.Span("A", className="dot"), "SH"],
                 className="emd-logo"),
        html.Div("EM Macro Research Flagship Master Dashboard", className="emd-tagline"),
        html.Div(className="emd-spacer"),
        html.Div("SMUEM", className="emd-badge"),
    ], className="emd-header"),

    dcc.Tabs(id="tabs", value="news", parent_className="emd-tabs",
             className="emd-tabs",
             children=[
        dcc.Tab(label="News Feed", value="news",
                className="emd-tab", selected_className="emd-tab--selected",
                children=[
            html.Div([
                html.Div([html.Span("Group by", className="emd-ctrl-label"),
                          dcc.RadioItems(id="group-by", value="Country",
                                         inline=True, className="emd-radio",
                                         options=["Country", "Topic", "Tier"])],
                         className="emd-ctrl-group"),
                html.Div([html.Span("Desk", className="emd-ctrl-label"),
                          dcc.Dropdown(id="desk", value="ALL", clearable=False,
                                       style={"width": "220px"},
                                       options=[{"label": "All desks", "value": "ALL"}] +
                                       [{"label": config.DESK_LABELS[d], "value": d}
                                        for d in config.DESK_LABELS])],
                         className="emd-ctrl-group"),
            ], className="emd-controls"),
            html.Div(id="news-board"),
        ]),
        dcc.Tab(label="Country Indicators", value="country",
                className="emd-tab", selected_className="emd-tab--selected",
                children=[
            html.Div([
                html.Div([html.Span("Country", className="emd-ctrl-label"),
                          dcc.Dropdown(id="country", clearable=False,
                                       style={"width": "230px"},
                                       value=config.COUNTRIES[0][0],
                                       options=[{"label": f"{n} ({i})", "value": i}
                                                for i, n, *_ in config.COUNTRIES])],
                         className="emd-ctrl-group"),
                html.Div([html.Span("Indicator", className="emd-ctrl-label"),
                          dcc.Dropdown(id="indicator", clearable=False,
                                       style={"width": "220px"},
                                       value=macro_indicators()[0],
                                       options=[{"label": k, "value": k}
                                                for k in macro_indicators()])],
                         className="emd-ctrl-group"),
                html.Div([html.Span("Transform", className="emd-ctrl-label"),
                          dcc.Dropdown(id="transform", clearable=False,
                                       style={"width": "180px"}, value="Level",
                                       options=[{"label": t, "value": t}
                                                for t in TRANSFORMS])],
                         className="emd-ctrl-group"),
            ], className="emd-controls"),

            html.Div(id="stat-tiles"),
            html.Div([
                html.Div(dcc.Graph(id="macro-graph",
                                   config={"displayModeBar": False}),
                         className="emd-card"),
                html.Div(dcc.Graph(id="fx-graph",
                                   config={"displayModeBar": False}),
                         className="emd-card"),
            ], className="emd-grid-2"),

            html.Div("All indicators (level)", className="emd-section-title"),
            html.Div(id="indicator-grid"),
        ]),
    ]),
    html.Div("EMDASH · local build · reads emdash.sqlite", className="emd-footer"),
])


# ===================================================================
# CALLBACKS
# ===================================================================
@app.callback(Output("news-board", "children"),
              Input("group-by", "value"), Input("desk", "value"))
def _news(group_by, desk):
    return news_board(group_by, desk)


@app.callback(Output("macro-graph", "figure"), Output("fx-graph", "figure"),
              Output("stat-tiles", "children"), Output("indicator-grid", "children"),
              Input("country", "value"), Input("indicator", "value"),
              Input("transform", "value"))
def _country(iso3, indicator, transform):
    return (macro_fig(iso3, indicator, transform), fx_fig(iso3, transform),
            stat_tiles(iso3), indicator_grid(iso3))


if __name__ == "__main__":
    core.init_db()
    print(f"[app] EMDASH running -> http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    app.run(debug=True, port=PORT)
