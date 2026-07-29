"""
EMDASH :: app.py

THE DASHBOARD. Reads ONLY through core.py; math via signals.py / event_study.py.
Styling: assets/emdash.css. Editable settings: config.py. This file = logic.

WHAT'S NEW IN THIS VERSION
--------------------------
1. AUTO-SAVE  ->  emdash_state.json (in the EMDASH folder, like GEMBI/GEMPAD).
   Every control change writes the whole dashboard state (active tab + every
   filter/dropdown on all three tabs) to a small JSON file.

   FIX (this version): the layout is now a FUNCTION (serve_layout), so the app
   re-reads emdash_state.json on EVERY browser refresh -- previously the layout
   was built once at server start, so a refresh showed stale defaults AND the
   auto-save then overwrote your good JSON with those defaults. The auto-save
   callback also now has prevent_initial_call=True, so simply loading/refreshing
   the page never overwrites your saved state -- only a real control change does.

2. NEWS FEED SPEED  ->  desks/topics pre-computed ONCE at load; date/tier/desk/
   topic filters are vectorised pandas masks applied BEFORE any cards are built.

3. EVENT STUDY REDESIGN  ->  sentence layout + unit-aware threshold + live helper
   + plain-English headline (full stats behind an expander).

RUN
    python -m pip install dash plotly pandas feedparser
    python news_ingest.py
    python app.py            # -> http://127.0.0.1:9001
"""
from __future__ import annotations

import re
import json
import math
import datetime as dt
import urllib.parse

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output

import config
import core
import signals as sig

try:
    from news_ingest import topics_of
except Exception:
    def topics_of(_):
        return ["general"]

try:
    import event_study as es
except Exception:
    es = None

P = config.PALETTE
F = config.FONTS
PORT = 9001
CARDS_PER_COL = 15
NEWS_READ_LIMIT = 4000
DOMAIN_TIER = getattr(config, "DOMAIN_TIER", {})

TOPIC_LABELS = {
    "monetary_policy": "Monetary Policy", "inflation": "Inflation",
    "growth": "Growth", "trade": "Trade", "commodities": "Commodities",
    "credit_debt": "Credit & Debt", "fx_markets": "FX & Flows",
    "equities": "Equities", "geopolitics": "Geopolitics",
    "energy": "Energy", "tech": "Tech", "china": "China", "general": "General",
}
LABEL_TO_TOPIC = {v: k for k, v in TOPIC_LABELS.items()}

TRANSFORMS = ["Level", "YoY", "Momentum (20)", "Z-score (20)"]

DAY_OPTS = [("1 day", 1), ("2 days", 2), ("3 days", 3), ("4 days", 4),
            ("5 days", 5), ("6 days", 6), ("1 week", 7), ("2 weeks", 14),
            ("3 weeks", 21), ("4 weeks", 28), ("2 months", 60),
            ("3 months", 90), ("6 months", 180), ("All", 100000)]

NAME_BY_ISO = {i: n for i, n, *_ in config.COUNTRIES}
DESK_BY_ISO = {i: d for i, n, d, *_ in config.COUNTRIES}

DESK_SHORT = {
    "SEA": "SEA", "EASTASIA": "EAS", "CSASIA": "CSA", "LATAM": "LAT",
    "MEA": "MEA", "EMEUROPE": "EUR", "G10": "G10",
}
DESK_ORDER = list(config.DESK_LABELS)

COUNTRY_OPTS = sorted(
    [{"label": f"{n} ({i})", "value": i} for i, n, *_ in config.COUNTRIES],
    key=lambda o: o["label"])
INDICATOR_OPTS = sorted(
    [{"label": k, "value": k}
     for k in list(config.WB_INDICATORS) + list(config.DBN_SERIES)],
    key=lambda o: o["label"])

ES_RULES = [
    ("crosses ABOVE", "cross_above"),
    ("crosses BELOW", "cross_below"),
    ("is ABOVE",      "above"),
    ("is BELOW",      "below"),
    ("z-score ABOVE", "z_above"),
    ("z-score BELOW", "z_below"),
]
RULE_VERB = {k: lbl for lbl, k in ES_RULES}

_PCT_LEVEL_INDS = {
    "GDP_YOY", "CPI_YOY", "CURR_ACC_GDP", "GOV_DEBT_GDP", "UNEMPLOYMENT",
    "EXPORTS_GDP", "FDI_GDP", "POLICY_RATE",
}


def unit_for(indicator: str, transform: str) -> str:
    """What the THRESHOLD is measured in, given the signal + transform."""
    if transform.startswith("Z-score"):
        return "σ"
    if transform == "YoY" or transform.startswith("Momentum"):
        return "%"
    if indicator in _PCT_LEVEL_INDS:
        return "%"
    if indicator == "RESERVES_USD":
        return "USD"
    return "pts"


# ===================================================================
# AUTO-SAVE  ::  whole-dashboard state <-> emdash_state.json
# ===================================================================
STATE_PATH = config.ROOT / "emdash_state.json"


def load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            d = json.load(fh)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(d: dict) -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2)
    except Exception:
        pass  # never let a save failure break the UI


# Module-global holding the most recently loaded state. serve_layout() refreshes
# it from disk on every page load; sv() reads it while building components.
_STATE = load_state()


def sv(key, default):
    """Saved-value: initial control value from emdash_state.json, else default."""
    v = _STATE.get(key, default)
    return v if v is not None else default


# ===================================================================
# DATA HELPERS  (+ caching)
# ===================================================================
def _domain(url: str) -> str:
    try:
        net = urllib.parse.urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def _desks_for(isos: list[str]) -> list[str]:
    seen = []
    for i in isos:
        d = DESK_BY_ISO.get(i)
        if d and d not in seen:
            seen.append(d)
    return seen


_series_cache: dict = {}
_market_cache: dict = {}


def cached_series(iso3, indicator):
    k = (iso3, indicator)
    if k not in _series_cache:
        _series_cache[k] = core.get_series(iso3, indicator)
    return _series_cache[k]


def cached_market(iso3, series="FX"):
    k = (iso3, series)
    if k not in _market_cache:
        _market_cache[k] = core.get_market(iso3, series)
    return _market_cache[k]


_news_cache: dict = {"df": None}


def load_news(limit: int = NEWS_READ_LIMIT, force: bool = False) -> pd.DataFrame:
    """Return the processed news table. Heavy per-row work (topics, desks,
    dedup) is done ONCE here and cached for the whole session. The board
    callback then only does fast vectorised filtering on top."""
    if _news_cache["df"] is not None and not force:
        return _news_cache["df"]
    try:
        conn = core.get_conn()
        df = pd.read_sql(
            "SELECT ts, source_id, tier, iso3_tags, headline, url "
            "FROM news ORDER BY ts DESC LIMIT ?", conn, params=(limit,))
        conn.close()
    except Exception:
        return pd.DataFrame()
    if df.empty:
        _news_cache["df"] = df
        return df
    df["topics"] = df["headline"].map(topics_of)
    df["domain"] = df["url"].map(_domain)
    df["tier"] = [DOMAIN_TIER.get(d, t) for d, t in zip(df["domain"], df["tier"])]
    df["_dt"] = pd.to_datetime(df["ts"], errors="coerce")
    df["_key"] = df["iso3_tags"].fillna("") + "|" + df["headline"].map(_norm)
    _rank = {"A": 0, "B": 1, "C": 2}
    records = []
    for _, g in df.groupby("_key", sort=False):
        head = g.iloc[0].to_dict()
        head["dupes"] = len(g) - 1
        head["sources"] = list(zip(g["domain"].tolist(), g["url"].tolist()))
        head["tier"] = min(g["tier"], key=lambda x: _rank.get(x, 3))
        records.append(head)
    out = pd.DataFrame(records).sort_values("ts", ascending=False)
    out["_isos"] = out["iso3_tags"].fillna("").map(
        lambda s: [t for t in s.split(",") if t])
    out["_desks"] = out["_isos"].map(_desks_for)
    out["_topicset"] = out["topics"].map(set)
    out["_deskset"] = out["_desks"].map(set)
    _news_cache["df"] = out
    return out


def _downsample(s: pd.Series, cap: int = 800) -> pd.Series:
    return s.resample("W").last().dropna() if len(s) > cap else s


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
        title=dict(text=title, font=dict(size=13, color=P["navy1"]), x=0.01),
        template="plotly_white",
        font=dict(family=F["ui"], color=P["ink"], size=11),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=64, r=18, t=44, b=34), height=height,
        colorway=[P["navy2"], P["gold"], P["navy3"], P["good"], P["bad"]],
        xaxis=dict(gridcolor="#EEF0F4", automargin=True),
        yaxis=dict(gridcolor="#EEF0F4", automargin=True),
    )
    return fig


def macro_fig(iso3, indicator, transform):
    df = cached_series(iso3, indicator)
    fig = _fig(f"{indicator} · {transform}")
    if df is None or df.empty:
        fig.add_annotation(text="no data — run ingest.py", showarrow=False,
                           font=dict(color=P["muted"]))
        return fig
    s = df.set_index("date")["value"]
    y = _downsample(apply_transform(s, transform))
    fig.add_trace(go.Scatter(x=y.index, y=y.values, mode="lines",
                             line=dict(width=2), fill="tozeroy",
                             fillcolor="rgba(31,73,125,.06)"))
    if transform.startswith("Z-score"):
        fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    return fig


def fx_fig(iso3, transform):
    df = cached_market(iso3, "FX")
    fig = _fig(f"FX (LCY per USD) · {transform}")
    if df is None or df.empty:
        fig.add_annotation(text="no FX (peg / n.a.)", showarrow=False,
                           font=dict(color=P["muted"]))
        return fig
    s = df.set_index("date")["value"]
    y = _downsample(apply_transform(s, transform))
    fig.add_trace(go.Scatter(x=y.index, y=y.values, mode="lines",
                             line=dict(width=2, color=P["gold"])))
    return fig


def mini_fig(iso3, indicator, transform="Level"):
    df = cached_series(iso3, indicator)
    label = indicator if transform == "Level" else f"{indicator} · {transform}"
    fig = _fig(label, height=210)
    fig.update_layout(margin=dict(l=58, r=12, t=32, b=26))
    if df is None or df.empty:
        fig.add_annotation(text="—", showarrow=False, font=dict(color=P["muted"]))
        return fig
    s = df.set_index("date")["value"]
    y = _downsample(apply_transform(s, transform))
    fig.add_trace(go.Scatter(x=y.index, y=y.values, mode="lines",
                             line=dict(width=1.6)))
    if transform.startswith("Z-score"):
        fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    return fig


# ===================================================================
# NEWS RENDERING
# ===================================================================
def _news_card(row):
    tier = row["tier"] or "?"
    src = row["domain"] or row["source_id"] or ""
    meta = [html.Span(src, className="emd-news-src"),
            html.Span("·"), html.Span(str(row["ts"])[:16])]
    top = [html.Span(tier, className=f"emd-tier emd-tier--{tier}")]
    for d in row["_desks"]:
        top.append(html.Span(DESK_SHORT.get(d, d), className="emd-desk",
                             title=config.DESK_LABELS.get(d, d)))
    if row["iso3_tags"]:
        top.append(html.Span(row["iso3_tags"], className="emd-flag"))
    children = [
        html.Div(top, className="emd-news-top"),
        html.A(row["headline"], href=row["url"], target="_blank",
               className="emd-news-title"),
        html.Div(meta, className="emd-news-meta"),
    ]
    dupes = int(row.get("dupes", 0) or 0)
    if dupes > 0:
        links = [html.A(f"{dom or 'source'} ↗", href=url, target="_blank")
                 for dom, url in row["sources"][1:]]
        children.append(html.Details([
            html.Summary(f"+{dupes} more source{'s' if dupes > 1 else ''}"),
            html.Div(links, className="emd-src-list"),
        ], className="emd-more"))
    return html.Div(children, className="emd-news")


def _column_keys(row, columns_by):
    if columns_by == "Topic":
        return [TOPIC_LABELS.get(t, t) for t in row["topics"]]
    if columns_by == "Tier":
        return [f"Tier {row['tier']}" if row["tier"] else "Tier ?"]
    if columns_by == "Desk":
        return row["_desks"] or ["(no desk)"]
    return row["_isos"] or ["(untagged)"]


def _order_columns(keys, columns_by):
    keys = list(keys)
    if columns_by == "Desk":
        ranked = [d for d in DESK_ORDER if d in keys]
        rest = sorted(k for k in keys if k not in DESK_ORDER)
        return ranked + rest
    return sorted(keys)


def _column_title(col, columns_by):
    if columns_by == "Desk" and col in config.DESK_LABELS:
        return config.DESK_LABELS[col]
    if col in NAME_BY_ISO:
        return f"{col} — {NAME_BY_ISO[col]}"
    return col


def news_board(columns_by, desks, tiers, topics, days):
    df = load_news()
    if df.empty:
        return html.Div("No news yet — run  python news_ingest.py",
                        style={"padding": "28px", "color": P["muted"]})

    sub = df
    if days and days < 100000:
        cutoff = dt.datetime.now() - dt.timedelta(days=days)
        sub = sub[sub["_dt"] >= cutoff]
    if tiers:
        sub = sub[sub["tier"].isin(tiers)]
    if desks:
        dset = set(desks)
        sub = sub[sub["_deskset"].map(lambda ds: bool(ds & dset))]
    if topics:
        topic_keys = {LABEL_TO_TOPIC.get(t, t) for t in topics}
        sub = sub[sub["_topicset"].map(lambda ts: bool(ts & topic_keys))]

    if sub.empty:
        return html.Div("No headlines match these filters / date range.",
                        style={"padding": "28px", "color": P["muted"]})

    cols: dict[str, list] = {}
    for row in sub.to_dict("records"):
        for key in _column_keys(row, columns_by):
            cols.setdefault(key, []).append(row)

    board = []
    for col in _order_columns(cols, columns_by):
        total = len(cols[col])
        rows = cols[col][:CARDS_PER_COL]
        title = _column_title(col, columns_by)
        cards = [_news_card(r) for r in rows]
        if total > CARDS_PER_COL:
            cards.append(html.Div(f"+ {total - CARDS_PER_COL} more · scroll / filter",
                                  style={"fontSize": "11px", "color": P["muted"],
                                         "padding": "8px 0 2px"}))
        board.append(html.Div([
            html.Div([html.Span(title),
                      html.Span(str(total), className="count")],
                     className="emd-col-head"),
            html.Div(cards, className="emd-col-body"),
        ], className="emd-col"))
    return html.Div(board, className="emd-board")


# ===================================================================
# COUNTRY RENDERING
# ===================================================================
def stat_tiles(iso3):
    tiles = []
    for ind in config.WB_INDICATORS:
        df = cached_series(iso3, ind)
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


def indicator_grid(iso3, transform="Level"):
    cards = [html.Div(dcc.Graph(figure=mini_fig(iso3, ind, transform),
                                config={"displayModeBar": False}),
                      className="emd-card")
             for ind in config.WB_INDICATORS]
    return html.Div(cards, className="emd-grid-mini")


# ===================================================================
# EVENT STUDY RENDERING
# ===================================================================
def _signal_series(iso3, indicator, transform):
    df = cached_series(iso3, indicator)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    s = df.set_index("date")["value"]
    return apply_transform(s, transform).dropna()


def _target_fx(iso3):
    df = cached_market(iso3, "FX")
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return df.set_index("date")["value"].dropna()


def _fmt(v, unit):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if unit == "USD":
        return f"{v:,.0f}"
    return f"{v:,.1f}{unit}"


def es_helper(signal, unit, sig_name, transform, rule, threshold):
    if signal.empty:
        return html.Div("No data for this signal — pick another indicator, or "
                        "run ingest.py.", className="emd-es-helper emd-es-warn")
    cur = float(signal.iloc[-1])
    lo, hi, med = float(signal.min()), float(signal.max()), float(signal.median())
    n_fired = 0
    if es is not None:
        try:
            ev = es.make_events(signal, rule=rule, threshold=float(threshold))
            n_fired = int(ev.sum())
        except Exception:
            n_fired = 0
    return html.Div([
        html.Span(f"{sig_name} · {transform}", className="emd-es-helper-lead"),
        html.Span(f"  Current {_fmt(cur, unit)}", className="emd-es-cur"),
        html.Span(f"  ·  Range {_fmt(lo, unit)} to {_fmt(hi, unit)}"),
        html.Span(f"  ·  Median {_fmt(med, unit)}"),
        html.Span(f"  ·  this threshold fires "),
        html.Span(f"{n_fired} events",
                  className="emd-es-fires" + ("" if n_fired >= 5 else " emd-es-few")),
    ], className="emd-es-helper")


def es_path_fig(res):
    fig = _fig("Average path after event · cumulative % move in FX", height=340)
    fig.update_layout(showlegend=True,
                      legend=dict(orientation="h", y=1.14, x=0.0),
                      xaxis_title="Trading days after event",
                      yaxis_title="Cumulative %")
    if res is None or res.path.empty:
        fig.add_annotation(text="no events — loosen the rule / move the threshold",
                           showarrow=False, font=dict(color=P["muted"]))
        return fig
    if not res.base_path.empty:
        fig.add_trace(go.Scatter(
            x=list(res.base_path.index), y=(res.base_path.values * 100),
            mode="lines", name="Baseline (any day)",
            line=dict(width=1.5, color=P["grey"], dash="dot")))
    fig.add_trace(go.Scatter(
        x=list(res.path.index), y=(res.path.values * 100),
        mode="lines", name="After event",
        line=dict(width=2.6, color=P["navy2"])))
    fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    return fig


def es_headline(res, tgt_iso):
    if res is None or res.n_events == 0:
        return html.Div([
            html.Div("No events fired.", className="emd-es-head-main"),
            html.Div("Loosen the rule or move the threshold "
                     "(the helper above shows how many events each value fires).",
                     className="emd-es-head-sub"),
        ], className="emd-es-headline")
    tgt = NAME_BY_ISO.get(tgt_iso, tgt_iso)
    n = int(res.summary.loc[20, "n"]) or res.n_events
    mean20 = res.summary.loc[20, "mean"]
    base20 = res.baseline.loc[20, "mean"]
    hit = res.summary.loc[20, "hit_rate"]
    if mean20 is None or (isinstance(mean20, float) and math.isnan(mean20)):
        return html.Div("Not enough forward data at the 20-day horizon.",
                        className="emd-es-headline")
    edge20 = mean20 - base20
    strengthened = mean20 < 0
    direction = "strengthened" if strengthened else "weakened"
    icon = "📉" if strengthened else "📈"
    consistent = round((1 - hit) * n) if strengthened else round(hit * n)
    main = (f"{icon} {tgt} FX {direction} ~{abs(mean20)*100:.1f}% over the next "
            f"20 trading days — {consistent} of {n} times.")
    sub = (f"vs a normal 20-day drift of {base20*100:+.1f}%  →  "
           f"edge {edge20*100:+.1f}%   (edge is the signal; everything else "
           f"is context)")
    return html.Div([
        html.Div(main, className="emd-es-head-main"),
        html.Div(sub, className="emd-es-head-sub"),
    ], className="emd-es-headline")


def es_table(res):
    if res is None or res.n_events == 0:
        return html.Div("No events.", style={"padding": "14px", "color": P["muted"]})
    cmp = res.compare()
    heads = ["Horizon", "Events", "Mean %", "Base %", "Edge %",
             "Hit %", "Base hit %", "Median %", "t-stat"]
    thead = html.Thead(html.Tr([html.Th(h) for h in heads]))
    body = []
    for h, r in cmp.iterrows():
        edge = r["edge"] * 100
        edge_cls = "emd-pos" if edge > 0 else ("emd-neg" if edge < 0 else "")
        body.append(html.Tr([
            html.Td(f"{h}d"),
            html.Td(f"{int(r['n_events'])}"),
            html.Td(f"{r['mean']*100:+.2f}"),
            html.Td(f"{r['base_mean']*100:+.2f}"),
            html.Td(f"{edge:+.2f}", className=edge_cls),
            html.Td(f"{r['hit_rate']*100:.0f}"),
            html.Td(f"{r['base_hit_rate']*100:.0f}"),
            html.Td(f"{r['median']*100:+.2f}"),
            html.Td("—" if pd.isna(r['t_stat']) else f"{r['t_stat']:+.2f}"),
        ]))
    return html.Table([thead, html.Tbody(body)], className="emd-table")


# ===================================================================
# SENTENCE-BUILDER helpers
# ===================================================================
def _inline(comp):
    return html.Span(comp, className="emd-inline")


def _word(txt):
    return html.Span(txt, className="emd-s-word")


# ===================================================================
# APP
# ===================================================================
app = Dash(__name__, title="EMDASH")
server = app.server

_filter = lambda label, comp: html.Div(
    [html.Span(label, className="emd-ctrl-label"), comp], className="emd-ctrl-group")


def serve_layout():
    """Built fresh on EVERY page load. We re-read emdash_state.json here so a
    browser refresh restores your last view (a static layout would only ever
    reflect the state at server-start time)."""
    global _STATE
    _STATE = load_state()
    return html.Div([
        dcc.Store(id="_persist_sink"),   # auto-save target (data ignored)

        html.Div([
            html.Div(className="emd-mark"),
            html.Div("EMDASH", className="emd-logo"),
            html.Div(className="emd-title-sep"),
            html.Div("EM Macro Research OS", className="emd-tagline"),
            html.Div(className="emd-spacer"),
            html.Div([html.Span(className="dot"), "SMU EMERGING MARKETS"],
                     className="emd-badge"),
        ], className="emd-header"),

        dcc.Tabs(id="tabs", value=sv("tab", "news"), parent_className="emd-tabs",
                 className="emd-tabs", children=[

            # ---------------- NEWS ----------------
            dcc.Tab(label="News Feed", value="news",
                    className="emd-tab", selected_className="emd-tab--selected",
                    children=[
                html.Div([
                    _filter("Columns by", dcc.Dropdown(
                        id="columns-by", value=sv("columns_by", "Country"),
                        clearable=False, style={"width": "140px"},
                        options=["Country", "Topic", "Tier", "Desk"])),
                    _filter("Since", dcc.Dropdown(
                        id="f-days", value=sv("f_days", 7), clearable=False,
                        style={"width": "130px"},
                        options=[{"label": lbl, "value": v} for lbl, v in DAY_OPTS])),
                    _filter("Desk", dcc.Dropdown(
                        id="f-desk", multi=True, placeholder="All desks",
                        value=sv("f_desk", []), style={"minWidth": "200px"},
                        options=[{"label": config.DESK_LABELS[d], "value": d}
                                 for d in config.DESK_LABELS])),
                    _filter("Tier", dcc.Dropdown(
                        id="f-tier", multi=True, placeholder="All tiers",
                        value=sv("f_tier", []), style={"minWidth": "140px"},
                        options=[{"label": "A · Official", "value": "A"},
                                 {"label": "B · Research", "value": "B"},
                                 {"label": "C · Firehose", "value": "C"}])),
                    _filter("Topic", dcc.Dropdown(
                        id="f-topic", multi=True, placeholder="All topics",
                        value=sv("f_topic", []), style={"minWidth": "190px"},
                        options=[{"label": v, "value": v}
                                 for k, v in TOPIC_LABELS.items() if k != "general"])),
                    html.Button("🔄 Refresh news", id="refresh-news", n_clicks=0,
                                className="emd-btn"),
                ], className="emd-controls"),
                dcc.Loading(html.Div(id="news-board"), type="default", color=P["navy2"]),
            ]),

            # ---------------- COUNTRY ----------------
            dcc.Tab(label="Country Indicators", value="country",
                    className="emd-tab", selected_className="emd-tab--selected",
                    children=[
                html.Div([
                    _filter("Country", dcc.Dropdown(
                        id="country", clearable=False, style={"width": "230px"},
                        value=sv("country", COUNTRY_OPTS[0]["value"]),
                        options=COUNTRY_OPTS)),
                    _filter("Indicator", dcc.Dropdown(
                        id="indicator", clearable=False, style={"width": "220px"},
                        value=sv("indicator", INDICATOR_OPTS[0]["value"]),
                        options=INDICATOR_OPTS)),
                    _filter("Transform", dcc.Dropdown(
                        id="transform", clearable=False, style={"width": "180px"},
                        value=sv("transform", "Level"),
                        options=[{"label": t, "value": t} for t in TRANSFORMS])),
                    _filter("", dcc.Checklist(
                        id="show-grid",
                        options=[{"label": " Show all-indicator grid", "value": "on"}],
                        value=sv("show_grid", []), style={"fontSize": "13px"})),
                ], className="emd-controls"),
                html.Div(id="stat-tiles"),
                dcc.Loading(html.Div([
                    html.Div(dcc.Graph(id="macro-graph",
                                       config={"displayModeBar": False}),
                             className="emd-card"),
                    html.Div(dcc.Graph(id="fx-graph",
                                       config={"displayModeBar": False}),
                             className="emd-card"),
                ], className="emd-grid-2"), type="default", color=P["navy2"]),
                dcc.Loading(html.Div(id="indicator-grid"), type="default", color=P["navy2"]),
            ]),

            # ---------------- EVENT STUDY ----------------
            dcc.Tab(label="Event Study", value="eventstudy",
                    className="emd-tab", selected_className="emd-tab--selected",
                    children=[
                html.Div([
                    html.Div([
                        _word("When"),
                        _inline(dcc.Dropdown(
                            id="es-sig-country", clearable=False,
                            value=sv("es_sig_country", COUNTRY_OPTS[0]["value"]),
                            options=COUNTRY_OPTS, style={"width": "185px"})),
                        _word("’s"),
                        _inline(dcc.Dropdown(
                            id="es-sig-ind", clearable=False,
                            value=sv("es_sig_ind", INDICATOR_OPTS[0]["value"]),
                            options=INDICATOR_OPTS, style={"width": "175px"})),
                        _word("("),
                        _inline(dcc.Dropdown(
                            id="es-transform", clearable=False,
                            value=sv("es_transform", "Level"),
                            options=[{"label": t, "value": t} for t in TRANSFORMS],
                            style={"width": "155px"})),
                        _word(")"),
                        _inline(dcc.Dropdown(
                            id="es-rule", clearable=False,
                            value=sv("es_rule", "cross_above"),
                            options=[{"label": lbl, "value": key}
                                     for lbl, key in ES_RULES],
                            style={"width": "165px"})),
                        _inline(dcc.Input(
                            id="es-threshold", type="number",
                            value=sv("es_threshold", 0), debounce=True,
                            className="emd-input", style={"width": "82px"})),
                        html.Span(id="es-unit", className="emd-s-unit"),
                    ], className="emd-sentence"),
                    html.Div([
                        _word("→ show what"),
                        _inline(dcc.Dropdown(
                            id="es-tgt-country", clearable=False,
                            value=sv("es_tgt_country", COUNTRY_OPTS[0]["value"]),
                            options=COUNTRY_OPTS, style={"width": "185px"})),
                        _word("’s FX did over the next 1 / 5 / 20 / 60 trading days."),
                    ], className="emd-sentence"),
                    html.Div(id="es-helper-wrap"),
                ], className="emd-es-builder"),

                html.Div(id="es-headline-wrap"),
                dcc.Loading(html.Div(dcc.Graph(id="es-graph",
                                               config={"displayModeBar": False}),
                                     className="emd-card"),
                            type="default", color=P["navy2"]),
                html.Details([
                    html.Summary("▸ Show full stats (all horizons)"),
                    html.Div(id="es-table-wrap", className="emd-card"),
                ], className="emd-es-details"),
            ]),
        ]),

        html.Div("EMDASH · local build · reads emdash.sqlite · state → emdash_state.json",
                 className="emd-footer"),
    ])


app.layout = serve_layout


# ===================================================================
# CALLBACKS
# ===================================================================
@app.callback(Output("news-board", "children"),
              Input("columns-by", "value"), Input("f-days", "value"),
              Input("f-desk", "value"), Input("f-tier", "value"),
              Input("f-topic", "value"), Input("refresh-news", "n_clicks"))
def _news(columns_by, days, desks, tiers, topics, n_clicks):
    if n_clicks and n_clicks > (_news.__dict__.get("_last", 0)):
        _news.__dict__["_last"] = n_clicks
        load_news(force=True)
    return news_board(columns_by, desks, tiers, topics, days)


@app.callback(Output("macro-graph", "figure"), Output("fx-graph", "figure"),
              Output("stat-tiles", "children"),
              Input("country", "value"), Input("indicator", "value"),
              Input("transform", "value"))
def _country(iso3, indicator, transform):
    return (macro_fig(iso3, indicator, transform), fx_fig(iso3, transform),
            stat_tiles(iso3))


@app.callback(Output("indicator-grid", "children"),
              Input("show-grid", "value"), Input("country", "value"),
              Input("transform", "value"))
def _grid(show, iso3, transform):
    if not show:
        return html.Div("Tick “Show all-indicator grid” to render every "
                        "indicator at once (applies the Transform above).",
                        className="emd-section-title",
                        style={"color": P["muted"], "fontWeight": 500})
    return html.Div([
        html.Div(f"All indicators · {transform}", className="emd-section-title"),
        indicator_grid(iso3, transform),
    ])


@app.callback(Output("es-unit", "children"),
              Output("es-helper-wrap", "children"),
              Output("es-headline-wrap", "children"),
              Output("es-graph", "figure"),
              Output("es-table-wrap", "children"),
              Input("es-sig-country", "value"), Input("es-sig-ind", "value"),
              Input("es-transform", "value"), Input("es-rule", "value"),
              Input("es-threshold", "value"), Input("es-tgt-country", "value"))
def _eventstudy(sig_iso, sig_ind, transform, rule, threshold, tgt_iso):
    unit = unit_for(sig_ind, transform)
    sig_name = NAME_BY_ISO.get(sig_iso, sig_iso)
    signal = _signal_series(sig_iso, sig_ind, transform)
    thr = float(threshold) if threshold is not None else 0.0

    helper = es_helper(signal, unit, sig_name, transform, rule, thr)

    if es is None:
        fig = _fig("Event Study")
        fig.add_annotation(text="event_study.py not found in folder",
                           showarrow=False, font=dict(color=P["bad"]))
        return unit, helper, "", fig, html.Div("event_study.py missing.")

    target = _target_fx(tgt_iso)
    if signal.empty or target.empty:
        fig = _fig("Event Study")
        msg = ("No FX for this target (peg / n.a.)" if target.empty
               else "No signal data — run ingest.py")
        fig.add_annotation(text=msg, showarrow=False, font=dict(color=P["muted"]))
        head = html.Div(msg, className="emd-es-headline")
        return unit, helper, head, fig, html.Div(msg, style={"color": P["muted"]})

    res = es.event_study(target, signal, rule=rule, threshold=thr,
                         horizons=(1, 5, 20, 60), kind="pct")
    return (unit, helper, es_headline(res, tgt_iso),
            es_path_fig(res), es_table(res))


# ---- AUTO-SAVE: a REAL control change writes the whole state to JSON. ----
# prevent_initial_call=True is critical: without it this fires on every page
# load/refresh and would overwrite your saved JSON with the just-restored values
# before you touch anything.
@app.callback(Output("_persist_sink", "data"),
              Input("tabs", "value"),
              Input("columns-by", "value"), Input("f-days", "value"),
              Input("f-desk", "value"), Input("f-tier", "value"),
              Input("f-topic", "value"),
              Input("country", "value"), Input("indicator", "value"),
              Input("transform", "value"), Input("show-grid", "value"),
              Input("es-sig-country", "value"), Input("es-sig-ind", "value"),
              Input("es-transform", "value"), Input("es-rule", "value"),
              Input("es-threshold", "value"), Input("es-tgt-country", "value"),
              prevent_initial_call=True)
def _persist(tab, columns_by, f_days, f_desk, f_tier, f_topic,
             country, indicator, transform, show_grid,
             es_sig_country, es_sig_ind, es_transform, es_rule,
             es_threshold, es_tgt_country):
    save_state({
        "tab": tab,
        "columns_by": columns_by, "f_days": f_days, "f_desk": f_desk,
        "f_tier": f_tier, "f_topic": f_topic,
        "country": country, "indicator": indicator, "transform": transform,
        "show_grid": show_grid,
        "es_sig_country": es_sig_country, "es_sig_ind": es_sig_ind,
        "es_transform": es_transform, "es_rule": es_rule,
        "es_threshold": es_threshold, "es_tgt_country": es_tgt_country,
    })
    return {}


if __name__ == "__main__":
    core.init_db()
    print(f"[app] EMDASH running -> http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    print(f"[app] state file -> {STATE_PATH}")
    app.run(debug=False, use_reloader=False, port=PORT)
