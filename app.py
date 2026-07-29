"""
EMDASH :: app.py   (Event Study v2 + Country polish)  -- fixes pass

FIXES THIS VERSION
    * Country charts: range-selector buttons no longer overlap the title
      (buttons moved to the right, extra top margin).
    * News tier pill: invalid CSS class emd-tier--? replaced with emd-tier--U
      (a '?' in a CSS selector breaks parsing); display still shows "?".
    * Cross-sectional bar: bigger value labels, dynamic height (so 40+ countries
      aren't cramped), wider left margin so country names show.
    * Compare-all horizon is now a TYPED number box (any N days) with a live grey
      "(max NNN)" hint of how far the data allows.
    * Stats tables: plain-English column legend added; compare-all table is now
      SORTABLE via a "sort by" control (edge / |edge| / mean / hit / country).

RUN
    python -m pip install dash plotly pandas feedparser
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
MAX_SPAGHETTI = 40
DOMAIN_TIER = getattr(config, "DOMAIN_TIER", {})

TOPIC_LABELS = {
    "central_bank": "Central Bank", "econ_data": "Econ Data & Releases",
    "trade": "Trade", "rates_credit": "Rates & Credit", "fx": "FX",
    "commodities": "Commodities", "equities": "Equities", "energy": "Energy",
    "technology": "Technology", "geopolitics": "Geopolitics", "china": "China",
    "general": "General",
}
LABEL_TO_TOPIC = {v: k for k, v in TOPIC_LABELS.items()}
TRANSFORMS = ["Level", "YoY", "Momentum (20)", "Z-score (20)"]
DAY_OPTS = [("1 day", 1), ("2 days", 2), ("3 days", 3), ("4 days", 4),
            ("5 days", 5), ("6 days", 6), ("1 week", 7), ("2 weeks", 14),
            ("3 weeks", 21), ("4 weeks", 28), ("2 months", 60),
            ("3 months", 90), ("6 months", 180), ("All", 100000)]

NAME_BY_ISO = {i: n for i, n, *_ in config.COUNTRIES}
DESK_BY_ISO = {i: d for i, n, d, *_ in config.COUNTRIES}
FX_ISOS = [i for i, n, d, dm, fx in config.COUNTRIES if fx]
DESK_SHORT = {d: d for d in config.DESK_LABELS}
DESK_ORDER = list(config.DESK_LABELS)

COUNTRY_OPTS = sorted(
    [{"label": f"{n} ({i})", "value": i} for i, n, *_ in config.COUNTRIES],
    key=lambda o: o["label"])
INDICATOR_OPTS = sorted(
    [{"label": k, "value": k}
     for k in list(config.WB_INDICATORS) + list(config.DBN_SERIES)],
    key=lambda o: o["label"])

ES_RULES = [("crosses ABOVE", "cross_above"), ("crosses BELOW", "cross_below"),
            ("is ABOVE", "above"), ("is BELOW", "below"),
            ("z-score ABOVE", "z_above"), ("z-score BELOW", "z_below")]
ES_HORIZONS = (1, 5, 20, 60)
ES_SORTS = [("Edge (high → low)", "edge_desc"), ("Edge (low → high)", "edge_asc"),
            ("Biggest move |edge|", "abs"), ("Mean", "mean"),
            ("Hit rate", "hit"), ("Country A→Z", "name")]

_PCT_LEVEL_INDS = {"GDP_YOY", "CPI_YOY", "CURR_ACC_GDP", "GOV_DEBT_GDP",
                   "UNEMPLOYMENT", "EXPORTS_GDP", "FDI_GDP", "POLICY_RATE"}
_GLOBAL_DIFF = {"US10Y", "VIX", "MOVE"}


def unit_for(indicator: str, transform: str) -> str:
    if transform.startswith("Z-score"):
        return "σ"
    if transform == "YoY" or transform.startswith("Momentum"):
        return "%"
    if indicator in _PCT_LEVEL_INDS:
        return "%"
    if indicator == "RESERVES_USD":
        return "USD"
    return "pts"


def _target_options():
    opts = [
        {"label": "— This country —", "value": "ctry:FX", "disabled": True},
        {"label": "This country · FX", "value": "ctry:FX"},
        {"label": "This country · Policy rate", "value": "ctry:POLICY_RATE"},
        {"label": "— Global markets —", "value": "glob:EMB", "disabled": True},
    ]
    for k in config.MARKET_TICKERS:
        opts.append({"label": f"Global · {k}", "value": f"glob:{k}"})
    opts.append({"label": "— Commodities —", "value": "cmdty:BRENT", "disabled": True})
    for k in config.COMMODITIES:
        opts.append({"label": f"Commodity · {k}", "value": f"cmdty:{k}"})
    return opts


TARGET_OPTS = _target_options()

# ===================================================================
# AUTO-SAVE
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
        pass


_STATE = load_state()


def sv(key, default):
    v = _STATE.get(key, default)
    return v if v is not None else default


# ===================================================================
# DATA HELPERS
# ===================================================================
def _domain(url: str) -> str:
    try:
        net = urllib.parse.urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return ""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def _desks_for(isos):
    seen = []
    for i in isos:
        d = DESK_BY_ISO.get(i)
        if d and d not in seen:
            seen.append(d)
    return seen


def _human(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    a = abs(v)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{v/div:,.1f}{suf}"
    return f"{v:,.1f}"


_series_cache: dict = {}
_market_cache: dict = {}
_global_cache: dict = {}
_cmdty_cache: dict = {}


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


def cached_global(series):
    if series not in _global_cache:
        try:
            _global_cache[series] = core.get_global(series)
        except Exception:
            _global_cache[series] = pd.DataFrame()
    return _global_cache[series]


def cached_commodity(name):
    if name not in _cmdty_cache:
        try:
            _cmdty_cache[name] = core.get_commodity(name)
        except Exception:
            _cmdty_cache[name] = pd.DataFrame()
    return _cmdty_cache[name]


_news_cache: dict = {"df": None}


def load_news(limit: int = NEWS_READ_LIMIT, force: bool = False) -> pd.DataFrame:
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


def _downsample(s, cap=800):
    return s.resample("W").last().dropna() if len(s) > cap else s


def _periods_per_year(s):
    if len(s) < 3:
        return 1
    gap = s.index.to_series().diff().dt.days.median()
    if gap <= 2:   return 252
    if gap <= 10:  return 52
    if gap <= 45:  return 12
    if gap <= 120: return 4
    return 1


def apply_transform(s, name):
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
def _fig(title, height=320, rangeselector=False):
    fig = go.Figure()
    xaxis = dict(gridcolor="#EEF0F4", automargin=True, showspikes=True,
                 spikethickness=1, spikedash="dot", spikecolor=P["muted"],
                 spikemode="across")
    top = 52
    if rangeselector:
        top = 74                       # extra headroom so buttons clear the title
        xaxis["rangeselector"] = dict(
            buttons=[dict(count=1, label="1Y", step="year", stepmode="backward"),
                     dict(count=5, label="5Y", step="year", stepmode="backward"),
                     dict(count=10, label="10Y", step="year", stepmode="backward"),
                     dict(step="all", label="Max")],
            bgcolor="#F1F4FB", activecolor=P["navy3"],
            font=dict(size=10, color=P["navy1"]),
            x=1.0, xanchor="right", y=1.22, yanchor="top")   # buttons top-RIGHT
        xaxis["rangeslider"] = dict(visible=False)
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color=P["navy1"]),
                   x=0.01, xanchor="left", y=0.99, yanchor="top"),
        template="plotly_white", hovermode="x unified",
        font=dict(family=F["ui"], color=P["ink"], size=11),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=64, r=18, t=top, b=34), height=height,
        colorway=[P["navy2"], P["gold"], P["navy3"], P["good"], P["bad"]],
        xaxis=xaxis, yaxis=dict(gridcolor="#EEF0F4", automargin=True),
    )
    return fig


def _last_marker(fig, s, color, unit=""):
    if s is None or s.empty:
        return
    x, y = s.index[-1], float(s.iloc[-1])
    fig.add_trace(go.Scatter(x=[x], y=[y], mode="markers", showlegend=False,
                             marker=dict(size=7, color=color),
                             hovertemplate=f"latest {_human(y)}{unit}<extra></extra>"))
    fig.add_annotation(x=x, y=y, text=f"  {_human(y)}{unit}", showarrow=False,
                       xanchor="left", font=dict(size=10, color=color))


def macro_fig(iso3, indicator, transform):
    df = cached_series(iso3, indicator)
    fig = _fig(f"{indicator} · {transform}", rangeselector=True)
    if df is None or df.empty:
        fig.add_annotation(text="no data — run ingest.py", showarrow=False,
                           font=dict(color=P["muted"]))
        return fig
    s = df.set_index("date")["value"]
    y = _downsample(apply_transform(s, transform))
    mode = "lines+markers" if len(y) < 60 else "lines"
    fig.add_trace(go.Scatter(x=y.index, y=y.values, mode=mode, line=dict(width=2),
                             marker=dict(size=5), fill="tozeroy",
                             fillcolor="rgba(31,73,125,.06)", name=indicator,
                             hovertemplate="%{y:.2f}<extra></extra>"))
    _last_marker(fig, y, P["navy1"])
    if transform.startswith("Z-score"):
        fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    return fig


def fx_fig(iso3, transform):
    df = cached_market(iso3, "FX")
    fig = _fig(f"FX (LCY per USD) · {transform}", rangeselector=True)
    if df is None or df.empty:
        fig.add_annotation(text="no FX (peg / n.a.)", showarrow=False,
                           font=dict(color=P["muted"]))
        return fig
    s = df.set_index("date")["value"]
    y = _downsample(apply_transform(s, transform))
    fig.add_trace(go.Scatter(x=y.index, y=y.values, mode="lines",
                             line=dict(width=2, color=P["gold"]), name="FX",
                             hovertemplate="%{y:.3f}<extra></extra>"))
    _last_marker(fig, y, P["brown"])
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
    mode = "lines+markers" if len(y) < 60 else "lines"
    fig.add_trace(go.Scatter(x=y.index, y=y.values, mode=mode, line=dict(width=1.6),
                             marker=dict(size=4), hovertemplate="%{y:.2f}<extra></extra>"))
    if transform.startswith("Z-score"):
        fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    return fig


# ===================================================================
# NEWS RENDERING
# ===================================================================
def _news_card(row):
    tier = row["tier"] or "?"
    tcls = tier if tier in ("A", "B", "C") else "U"   # valid CSS class (no '?')
    src = row["domain"] or row["source_id"] or ""
    meta = [html.Span(src, className="emd-news-src"),
            html.Span("·"), html.Span(str(row["ts"])[:16])]
    top = [html.Span(tier, className=f"emd-tier emd-tier--{tcls}")]
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
        return ranked + sorted(k for k in keys if k not in DESK_ORDER)
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
        tk = {LABEL_TO_TOPIC.get(t, t) for t in topics}
        sub = sub[sub["_topicset"].map(lambda ts: bool(ts & tk))]
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
        cards = [_news_card(r) for r in rows]
        if total > CARDS_PER_COL:
            cards.append(html.Div(f"+ {total - CARDS_PER_COL} more · scroll / filter",
                                  style={"fontSize": "11px", "color": P["muted"],
                                         "padding": "8px 0 2px"}))
        board.append(html.Div([
            html.Div([html.Span(_column_title(col, columns_by)),
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
            val = _human(last["value"])
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
# EVENT STUDY RENDERING  (v2)
# ===================================================================
def _signal_series(iso3, indicator, transform):
    df = cached_series(iso3, indicator)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return apply_transform(df.set_index("date")["value"], transform).dropna()


def resolve_target(target_value, country):
    grp, _, key = (target_value or "ctry:FX").partition(":")
    cname = NAME_BY_ISO.get(country, country)
    if grp == "ctry" and key == "FX":
        df = cached_market(country, "FX")
        s = df.set_index("date")["value"].dropna() if not df.empty else pd.Series(dtype=float)
        return s, "pct", f"{cname} FX", "%"
    if grp == "ctry" and key == "POLICY_RATE":
        df = cached_series(country, "POLICY_RATE")
        s = df.set_index("date")["value"].dropna() if not df.empty else pd.Series(dtype=float)
        return s, "diff", f"{cname} policy rate", "pp"
    if grp == "glob":
        df = cached_global(key)
        s = df.set_index("date")["value"].dropna() if not df.empty else pd.Series(dtype=float)
        kind = "diff" if key in _GLOBAL_DIFF else "pct"
        return s, kind, f"{key}", ("pt" if kind == "diff" else "%")
    if grp == "cmdty":
        df = cached_commodity(key)
        s = df.set_index("date")["value"].dropna() if not df.empty else pd.Series(dtype=float)
        return s, "pct", f"{key}", "%"
    return pd.Series(dtype=float), "pct", target_value, "%"


def es_helper(signal, unit, sig_name, transform, rule, threshold):
    if signal.empty:
        return html.Div("No data for this signal — pick another indicator, or "
                        "run ingest.py.", className="emd-es-helper emd-es-warn")
    cur = float(signal.iloc[-1])
    lo, hi, med = float(signal.min()), float(signal.max()), float(signal.median())
    n_fired = 0
    if es is not None:
        try:
            n_fired = int(es.make_events(signal, rule=rule, threshold=float(threshold)).sum())
        except Exception:
            n_fired = 0

    def f(v):
        return "—" if v is None or math.isnan(v) else (f"{v:,.0f}" if unit == "USD" else f"{v:,.1f}{unit}")

    return html.Div([
        html.Span(f"{sig_name} · {transform}", className="emd-es-helper-lead"),
        html.Span(f"  Current {f(cur)}", className="emd-es-cur"),
        html.Span(f"  ·  Range {f(lo)} to {f(hi)}"),
        html.Span(f"  ·  Median {f(med)}"),
        html.Span("  ·  this threshold fires "),
        html.Span(f"{n_fired} events",
                  className="emd-es-fires" + ("" if n_fired >= 5 else " emd-es-few")),
    ], className="emd-es-helper")


def es_path_fig(res, tgt_label, unit):
    yfac = 100 if unit == "%" else 1
    ytitle = "Cumulative %" if unit == "%" else f"Cumulative move ({unit})"
    fig = _fig(f"After event · {tgt_label} · typical path + dispersion", height=360)
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.14, x=0.0),
                      xaxis_title="Trading days after event", yaxis_title=ytitle,
                      hovermode="x")
    if res is None or res.path.empty:
        fig.add_annotation(text="no events — loosen the rule / move the threshold",
                           showarrow=False, font=dict(color=P["muted"]))
        return fig
    paths = res.paths
    for c in list(paths.columns)[:MAX_SPAGHETTI]:
        fig.add_trace(go.Scatter(x=list(paths.index), y=(paths[c].values * yfac),
                                 mode="lines", line=dict(width=0.6, color="rgba(101,147,196,.28)"),
                                 showlegend=False, hoverinfo="skip"))
    med, lo, hi = es.path_band(paths, 25, 75)
    fig.add_trace(go.Scatter(x=list(hi.index), y=(hi.values * yfac), mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=list(lo.index), y=(lo.values * yfac), mode="lines",
                             line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(31,73,125,.10)", name="25–75% band",
                             hoverinfo="skip"))
    if not res.base_path.empty:
        fig.add_trace(go.Scatter(x=list(res.base_path.index), y=(res.base_path.values * yfac),
                                 mode="lines", name="Baseline (any day)",
                                 line=dict(width=1.5, color=P["grey"], dash="dot")))
    fig.add_trace(go.Scatter(x=list(res.path.index), y=(res.path.values * yfac),
                             mode="lines", name="Mean after event",
                             line=dict(width=2.8, color=P["navy2"])))
    fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    return fig


def es_headline(res, tgt_label, unit):
    if res is None or res.n_events == 0:
        return html.Div([
            html.Div("No events fired.", className="emd-es-head-main"),
            html.Div("Loosen the rule or move the threshold "
                     "(the helper above shows how many events each value fires).",
                     className="emd-es-head-sub"),
        ], className="emd-es-headline")
    n = int(res.summary.loc[20, "n"]) or res.n_events
    mean20 = res.summary.loc[20, "mean"]
    base20 = res.baseline.loc[20, "mean"]
    hit = res.summary.loc[20, "hit_rate"]
    if mean20 is None or math.isnan(mean20):
        return html.Div("Not enough forward data at the 20-day horizon.",
                        className="emd-es-headline")
    edge = mean20 - base20
    fac = 100 if unit == "%" else 1
    up = mean20 > 0
    icon = "📈" if up else "📉"
    consistent = round(hit * n) if up else round((1 - hit) * n)
    verb = "rose" if up else "fell"
    main = (f"{icon} {tgt_label} {verb} ~{abs(mean20)*fac:.1f}{unit} over the next "
            f"20 trading days — {consistent} of {n} times.")
    sub = (f"vs a normal 20-day move of {base20*fac:+.1f}{unit}  →  "
           f"edge {edge*fac:+.1f}{unit}   (edge is the signal; everything else is context)")
    return html.Div([html.Div(main, className="emd-es-head-main"),
                     html.Div(sub, className="emd-es-head-sub")],
                    className="emd-es-headline")


def _col_legend(cross=False):
    """Plain-English meaning of the stats columns."""
    items = [
        ("Events", "how many times the signal fired (small = fragile)"),
        ("Mean", "average target move after the event"),
        ("Base", "average move on any random day (benchmark)"),
        ("Edge", "Mean − Base — the signal (how much the event added)"),
        ("Hit %", "how often the move was positive after the event"),
    ]
    if not cross:
        items += [("Base hit %", "how often positive on any random day"),
                  ("Median", "the middle outcome (robust to one weird event)"),
                  ("t-stat", "rough strength; |t|>2 notable — but ignore when Events is small")]
    return html.Div([html.Span("How to read: ", className="emd-legend-lead")] +
                    [html.Span([html.B(k + " "), v + "   ·  "], className="emd-legend-item")
                     for k, v in items], className="emd-legend")


def es_table(res, unit):
    if res is None or res.n_events == 0:
        return html.Div("No events.", style={"padding": "14px", "color": P["muted"]})
    fac = 100 if unit == "%" else 1
    cmp = res.compare()
    heads = ["Horizon", "Events", f"Mean {unit}", f"Base {unit}", f"Edge {unit}",
             "Hit %", "Base hit %", f"Median {unit}", "t-stat"]
    thead = html.Thead(html.Tr([html.Th(h) for h in heads]))
    body = []
    for h, r in cmp.iterrows():
        edge = r["edge"] * fac
        cls = "emd-pos" if edge > 0 else ("emd-neg" if edge < 0 else "")
        body.append(html.Tr([
            html.Td(f"{h}d"), html.Td(f"{int(r['n_events'])}"),
            html.Td(f"{r['mean']*fac:+.2f}"), html.Td(f"{r['base_mean']*fac:+.2f}"),
            html.Td(f"{edge:+.2f}", className=cls),
            html.Td(f"{r['hit_rate']*100:.0f}"), html.Td(f"{r['base_hit_rate']*100:.0f}"),
            html.Td(f"{r['median']*fac:+.2f}"),
            html.Td("—" if pd.isna(r['t_stat']) else f"{r['t_stat']:+.2f}"),
        ]))
    return html.Div([_col_legend(cross=False),
                     html.Table([thead, html.Tbody(body)], className="emd-table")])


def _cross_targets(kind_key):
    out = {}
    for iso in FX_ISOS:
        df = cached_market(iso, "FX") if kind_key == "FX" else cached_series(iso, "POLICY_RATE")
        if df is not None and not df.empty:
            out[iso] = df.set_index("date")["value"].dropna()
    return out


def _sort_cross(xs, how):
    if xs is None or xs.empty:
        return xs
    if how == "edge_asc":
        return xs.sort_values("edge", ascending=True)
    if how == "abs":
        return xs.reindex(xs["edge"].abs().sort_values(ascending=False).index)
    if how == "mean":
        return xs.sort_values("mean", ascending=False)
    if how == "hit":
        return xs.sort_values("hit_rate", ascending=False)
    if how == "name":
        return xs.sort_index()
    return xs.sort_values("edge", ascending=False)   # edge_desc default


def es_cross_fig(xs, horizon, xtarget_label):
    n = len(xs)
    height = max(420, 26 * n + 150)            # dynamic: room per country
    fig = _fig(f"Edge by country · {xtarget_label} · {horizon}d after event", height=height)
    fig.update_layout(margin=dict(l=150, r=70, t=60, b=44),
                      xaxis_title="Edge % (conditional − baseline)", yaxis_title="",
                      hovermode="closest",
                      uniformtext_minsize=9, uniformtext_mode="hide")
    if xs is None or xs.empty:
        fig.add_annotation(text="no events / no data — loosen the rule",
                           showarrow=False, font=dict(color=P["muted"]))
        return fig
    xsb = xs.sort_values("edge")               # bar always ranked by edge
    isos = list(xsb.index)
    labels = [f"{NAME_BY_ISO.get(i,i)} ({i})" for i in isos]
    edges = (xsb["edge"] * 100).tolist()
    colors = [P["good"] if e > 0 else P["bad"] for e in edges]
    text = [f"{e:+.1f}%" for e in edges]
    fig.add_trace(go.Bar(x=edges, y=labels, orientation="h", marker_color=colors,
                         text=text, textposition="outside", textfont=dict(size=11),
                         cliponaxis=False,
                         hovertemplate="%{y}<br>edge %{x:+.2f}%<extra></extra>"))
    fig.add_vline(x=0, line_dash="dot", line_color=P["muted"])
    return fig


def es_cross_table(xs):
    if xs is None or xs.empty:
        return html.Div("No events / no data.", style={"padding": "14px", "color": P["muted"]})
    heads = ["Country", "Events", "Mean %", "Base %", "Edge %", "Hit %"]
    thead = html.Thead(html.Tr([html.Th(h) for h in heads]))
    body = []
    for iso, r in xs.iterrows():
        edge = r["edge"] * 100
        cls = "emd-pos" if edge > 0 else ("emd-neg" if edge < 0 else "")
        body.append(html.Tr([
            html.Td(f"{NAME_BY_ISO.get(iso, iso)} ({iso})"),
            html.Td(f"{int(r['n'])}"), html.Td(f"{r['mean']*100:+.2f}"),
            html.Td(f"{r['base_mean']*100:+.2f}"),
            html.Td(f"{edge:+.2f}", className=cls),
            html.Td(f"{r['hit_rate']*100:.0f}"),
        ]))
    return html.Div([_col_legend(cross=True),
                     html.Table([thead, html.Tbody(body)], className="emd-table")])


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
    global _STATE
    _STATE = load_state()
    return html.Div([
        dcc.Store(id="_persist_sink"),
        html.Div([
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
            dcc.Tab(label="News Feed", value="news", className="emd-tab",
                    selected_className="emd-tab--selected", children=[
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
                        value=sv("f_topic", []), style={"minWidth": "200px"},
                        options=[{"label": v, "value": v}
                                 for k, v in TOPIC_LABELS.items() if k != "general"])),
                    html.Button("🔄 Refresh news", id="refresh-news", n_clicks=0,
                                className="emd-btn"),
                ], className="emd-controls"),
                dcc.Loading(html.Div(id="news-board"), type="default", color=P["navy2"]),
            ]),

            # ---------------- COUNTRY ----------------
            dcc.Tab(label="Country Indicators", value="country", className="emd-tab",
                    selected_className="emd-tab--selected", children=[
                html.Div([
                    _filter("Country", dcc.Dropdown(
                        id="country", clearable=False, style={"width": "230px"},
                        value=sv("country", COUNTRY_OPTS[0]["value"]), options=COUNTRY_OPTS)),
                    _filter("Indicator", dcc.Dropdown(
                        id="indicator", clearable=False, style={"width": "220px"},
                        value=sv("indicator", INDICATOR_OPTS[0]["value"]), options=INDICATOR_OPTS)),
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
                    html.Div(dcc.Graph(id="macro-graph", config={"displayModeBar": False}),
                             className="emd-card"),
                    html.Div(dcc.Graph(id="fx-graph", config={"displayModeBar": False}),
                             className="emd-card"),
                ], className="emd-grid-2"), type="default", color=P["navy2"]),
                dcc.Loading(html.Div(id="indicator-grid"), type="default", color=P["navy2"]),
            ]),

            # ---------------- EVENT STUDY (v2) ----------------
            dcc.Tab(label="Event Study", value="eventstudy", className="emd-tab",
                    selected_className="emd-tab--selected", children=[
                html.Div([
                    dcc.RadioItems(
                        id="es-mode", value=sv("es_mode", "one"),
                        options=[{"label": " One country", "value": "one"},
                                 {"label": " Compare all countries", "value": "cross"}],
                        className="emd-es-mode", inline=True),
                ], className="emd-es-modebar"),

                html.Div([
                    html.Div([
                        _word("When"),
                        _inline(dcc.Dropdown(
                            id="es-sig-country", clearable=False,
                            value=sv("es_sig_country", "USA"),
                            options=COUNTRY_OPTS, style={"width": "180px"})),
                        _word("’s"),
                        _inline(dcc.Dropdown(
                            id="es-sig-ind", clearable=False,
                            value=sv("es_sig_ind", INDICATOR_OPTS[0]["value"]),
                            options=INDICATOR_OPTS, style={"width": "170px"})),
                        _word("("),
                        _inline(dcc.Dropdown(
                            id="es-transform", clearable=False,
                            value=sv("es_transform", "Level"),
                            options=[{"label": t, "value": t} for t in TRANSFORMS],
                            style={"width": "150px"})),
                        _word(")"),
                        _inline(dcc.Dropdown(
                            id="es-rule", clearable=False,
                            value=sv("es_rule", "cross_above"),
                            options=[{"label": lbl, "value": key} for lbl, key in ES_RULES],
                            style={"width": "160px"})),
                        _inline(dcc.Input(id="es-threshold", type="number",
                                          value=sv("es_threshold", 0), debounce=True,
                                          className="emd-input", style={"width": "80px"})),
                        html.Span(id="es-unit", className="emd-s-unit"),
                    ], className="emd-sentence"),

                    html.Div([
                        _word("→ show what"),
                        _inline(dcc.Dropdown(
                            id="es-target", clearable=False,
                            value=sv("es_target", "ctry:FX"),
                            options=TARGET_OPTS, style={"width": "260px"})),
                        _word("did over the next 1 / 5 / 20 / 60 trading days."),
                    ], id="es-row-one", className="emd-sentence"),

                    html.Div([
                        _word("→ rank every country’s"),
                        _inline(dcc.Dropdown(
                            id="es-xtarget", clearable=False,
                            value=sv("es_xtarget", "FX"),
                            options=[{"label": "FX", "value": "FX"},
                                     {"label": "Policy rate", "value": "POLICY_RATE"}],
                            style={"width": "150px"})),
                        _word("response at"),
                        _inline(dcc.Input(id="es-horizon", type="number", min=1,
                                          value=sv("es_horizon", 20), debounce=True,
                                          className="emd-input", style={"width": "72px"})),
                        _word("days"),
                        html.Span(id="es-horizon-max", className="emd-s-hint"),
                        _word("· sort by"),
                        _inline(dcc.Dropdown(
                            id="es-xsort", clearable=False,
                            value=sv("es_xsort", "edge_desc"),
                            options=[{"label": lbl, "value": v} for lbl, v in ES_SORTS],
                            style={"width": "175px"})),
                    ], id="es-row-cross", className="emd-sentence"),

                    html.Div(id="es-helper-wrap"),
                ], className="emd-es-builder"),

                html.Div(id="es-headline-wrap"),
                dcc.Loading(html.Div(dcc.Graph(id="es-graph",
                                               config={"displayModeBar": False}),
                                     className="emd-card"),
                            type="default", color=P["navy2"]),
                html.Details([
                    html.Summary("▸ Show full stats"),
                    html.Div(id="es-table-wrap", className="emd-card"),
                ], className="emd-es-details", open=True),
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


@app.callback(Output("es-row-one", "style"), Output("es-row-cross", "style"),
              Input("es-mode", "value"))
def _es_rows(mode):
    show, hide = {}, {"display": "none"}
    return (hide, show) if mode == "cross" else (show, hide)


@app.callback(Output("es-unit", "children"), Output("es-helper-wrap", "children"),
              Output("es-headline-wrap", "children"), Output("es-graph", "figure"),
              Output("es-table-wrap", "children"), Output("es-horizon-max", "children"),
              Input("es-mode", "value"),
              Input("es-sig-country", "value"), Input("es-sig-ind", "value"),
              Input("es-transform", "value"), Input("es-rule", "value"),
              Input("es-threshold", "value"), Input("es-target", "value"),
              Input("es-xtarget", "value"), Input("es-horizon", "value"),
              Input("es-xsort", "value"))
def _eventstudy(mode, sig_iso, sig_ind, transform, rule, threshold,
                target_value, xtarget, horizon, xsort):
    unit = unit_for(sig_ind, transform)
    sig_name = NAME_BY_ISO.get(sig_iso, sig_iso)
    signal = _signal_series(sig_iso, sig_ind, transform)
    thr = float(threshold) if threshold is not None else 0.0
    helper = es_helper(signal, unit, sig_name, transform, rule, thr)

    if es is None:
        f = _fig("Event Study"); f.add_annotation(text="event_study.py not found",
                                                   showarrow=False, font=dict(color=P["bad"]))
        return unit, helper, "", f, html.Div("event_study.py missing."), ""

    if signal.empty:
        f = _fig("Event Study")
        f.add_annotation(text="No signal data — run ingest.py", showarrow=False,
                         font=dict(color=P["muted"]))
        return (unit, helper, html.Div("No signal data.", className="emd-es-headline"),
                f, "", "")

    if mode == "cross":
        targets = _cross_targets(xtarget)
        # dynamic max horizon = shortest available target series (so all have data)
        maxh = min((len(s) for s in targets.values()), default=250)
        maxh = max(1, maxh - 1)
        h = int(horizon) if horizon else 20
        h = max(1, min(h, maxh))
        kind = "diff" if xtarget == "POLICY_RATE" else "pct"
        xs = es.cross_sectional(signal, targets, rule=rule, threshold=thr,
                                window=20, horizon=h, kind=kind)
        xs_sorted = _sort_cross(xs, xsort)
        xlabel = "FX" if xtarget == "FX" else "policy rate"
        n_ev = int(es.make_events(signal, rule=rule, threshold=thr).sum())
        head = html.Div([
            html.Div(f"🌐 Cross-section: {len(xs)} countries ranked by {h}-day "
                     f"{xlabel} edge after the signal fired ({n_ev} events).",
                     className="emd-es-head-main"),
            html.Div("Green = that country's FX/rate moved MORE than its own baseline "
                     "when the signal fired; red = less. Longer bar = more exposed.",
                     className="emd-es-head-sub"),
        ], className="emd-es-headline")
        return (unit, helper, head, es_cross_fig(xs, h, xlabel),
                es_cross_table(xs_sorted), f"(max {maxh})")

    target, kind, tgt_label, tunit = resolve_target(target_value, sig_iso)
    if target.empty:
        f = _fig("Event Study")
        f.add_annotation(text=f"No data for target: {tgt_label}", showarrow=False,
                         font=dict(color=P["muted"]))
        head = html.Div(f"No data for target: {tgt_label} "
                        "(e.g. USA/pegs have no FX — try a Global target).",
                        className="emd-es-headline")
        return unit, helper, head, f, "", ""
    res = es.event_study(target, signal, rule=rule, threshold=thr,
                         horizons=ES_HORIZONS, kind=kind)
    return (unit, helper, es_headline(res, tgt_label, tunit),
            es_path_fig(res, tgt_label, tunit), es_table(res, tunit), "")


@app.callback(Output("_persist_sink", "data"),
              Input("tabs", "value"),
              Input("columns-by", "value"), Input("f-days", "value"),
              Input("f-desk", "value"), Input("f-tier", "value"), Input("f-topic", "value"),
              Input("country", "value"), Input("indicator", "value"),
              Input("transform", "value"), Input("show-grid", "value"),
              Input("es-mode", "value"),
              Input("es-sig-country", "value"), Input("es-sig-ind", "value"),
              Input("es-transform", "value"), Input("es-rule", "value"),
              Input("es-threshold", "value"), Input("es-target", "value"),
              Input("es-xtarget", "value"), Input("es-horizon", "value"),
              Input("es-xsort", "value"),
              prevent_initial_call=True)
def _persist(tab, columns_by, f_days, f_desk, f_tier, f_topic,
             country, indicator, transform, show_grid, es_mode,
             es_sig_country, es_sig_ind, es_transform, es_rule,
             es_threshold, es_target, es_xtarget, es_horizon, es_xsort):
    save_state({
        "tab": tab, "columns_by": columns_by, "f_days": f_days, "f_desk": f_desk,
        "f_tier": f_tier, "f_topic": f_topic, "country": country,
        "indicator": indicator, "transform": transform, "show_grid": show_grid,
        "es_mode": es_mode, "es_sig_country": es_sig_country, "es_sig_ind": es_sig_ind,
        "es_transform": es_transform, "es_rule": es_rule, "es_threshold": es_threshold,
        "es_target": es_target, "es_xtarget": es_xtarget, "es_horizon": es_horizon,
        "es_xsort": es_xsort,
    })
    return {}


if __name__ == "__main__":
    core.init_db()
    print(f"[app] EMDASH running -> http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    print(f"[app] state file -> {STATE_PATH}")
    app.run(debug=False, use_reloader=False, port=PORT)
