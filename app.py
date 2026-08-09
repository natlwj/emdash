"""
EMDASH :: app.py   (v6)

THE DASHBOARD. Reads ONLY through core.py; math via signals.py / event_study.py
/ mrc.py; tagging via news_ingest.py. Styling: assets/emdash.css (v5).
Editable settings: config.py (v2).

==============================================================================
WHAT CHANGED IN v6  --  chart sizing only. No behaviour changes elsewhere.
==============================================================================

THE BUG: every chart collapsed to a strip, or overflowed its white card with
the "Source:" line pushed out underneath it.

THE CAUSE: this app sets an explicit pixel height on every figure inside
_fig() -- 320 by default, 215 for the mini grid, 380 for the event-study path,
210 for the regime ribbon, 340 for the gauges. v5 then ALSO set
dcc.Graph(responsive=True) on every graph, which tells Plotly the opposite:
"ignore the figure's height, take your size from the parent element instead".

Dash's `responsive` prop defaults to 'auto', which means "be responsive only
if the figure has no explicit height". v5 overrode that default to True
everywhere, so every carefully chosen height was thrown away and sizing was
handed to .emd-card -- which has only padding, no height. The result was
whatever the container happened to produce, which is why it looked erratic
rather than uniformly wrong.

THE FIX: delete the override. Every dcc.Graph now passes only its config dict,
so `responsive` returns to 'auto', Dash sees the explicit layout.height, and
the figure renders at exactly that height. The card grows to fit it and the
header / plot / source line stack normally.

  ** ALSO DELETE FROM assets/emdash.css (added during debugging, now harmful):
       .emd-card .js-plotly-plot,
       .emd-card .plot-container { min-height: 180px; width: 100%; }
     A min-height floor fighting a layout height is a third source of truth.
     KEEP the `.emd-chart-titlewrap { flex: 1 1 240px; }` fix -- unrelated
     and correct. Hard-refresh (Ctrl+Shift+R) or the old CSS stays cached. **

TRADE-OFF, stated plainly: charts no longer reflow on window resize. That was
v5's goal and it is what broke them. Fixed heights that fit correctly beat
responsive heights that overflow. If resize behaviour is wanted later, the
correct way is to drop `height` from _fig() AND give .emd-card a height, so
there is exactly ONE source of truth -- never both.

Everything else in this file is unchanged: same functions, same logic, same
callbacks, same outputs. Formatting, indentation and comment layout tidied
only; dead commented-out graph lines removed.

------------------------------------------------------------------------------
CARRIED OVER FROM v5
------------------------------------------------------------------------------

NEWS
  * FIRST LOAD IS ~12x FASTER. v4 was slower than v3, not faster. Measured on
    4,000 rows: re-tagging with ~250 separate compiled regexes cost 1,557 ms and
    formatting timestamps one row at a time (pd.to_datetime per row) cost
    1,934 ms -- ~3.7 s of work before a single card was drawn. Both are now
    vectorised: ONE combined alternation regex (in news_ingest.py) and a single
    vectorised .dt.strftime(). Same output, ~0.3 s.
  * TIMESTAMPS ARE NOW CONVERTED AND LABELLED. They were never SGT: feedparser
    normalises published_parsed to UTC and GDELT's seendate ends in "Z", so a
    card reading 07:29 was really 15:29 in Singapore. Now shifted by
    config.NEWS_TZ_OFFSET_HOURS and stamped "SGT", so the label is true.
  * PUBLISHER FAVICONS next to the source name (config.SHOW_FAVICONS). Served
    from a favicon proxy and browser-cached, so it costs zero Python time. If
    your office network blocks it, set SHOW_FAVICONS = False.
  * Column widths are uniform (CSS: the columns used to stretch to fill a row,
    so a 2-column row looked fatter than a 5-column row).
  * TOPIC TAGGING FIXED in news_ingest.py -- "Goldman" no longer reads as
    commodities, "coalition" no longer as energy. Topics drive the Kanban
    columns, so this was visible on every screen.

COUNTRY
  * FX CHART NO LONGER CLIPS. The CSS grid used `1fr`, which is really
    `minmax(auto, 1fr)`, and `auto` refuses to shrink below the chart's
    intrinsic minimum width -- fixed in emdash.css v5 with `minmax(0, 1fr)`.
  * MINI CHARTS: explicit tick counts (they were auto-thinned to 2-3 ticks at
    215px), and they can now OVERLAY COMPARE COUNTRIES -- toggleable via the
    "Compare countries in grid" checkbox.
  * NORMALISE NOW REBASES AT A COMMON START DATE. Rebasing each series at its
    own first observation compared "US CPI since 1955" with "HK CPI since 1980"
    -- most of that gap was a 25-year head start, not inflation. All compared
    series are now trimmed to the latest common start before rebasing.
  * PROVENANCE CHIP on every chart: RAW (straight from the warehouse) vs
    CALC (transformed by signals.py), so you always know what you're looking at.
  * "Source: ..." under EVERY chart, including the mini grid and all Event
    Study / MRC charts. v4 only had it on the two big country charts.

CHARTS (global, every tab)
  * TITLES AND SOURCE LINES ARE HTML, NOT DRAWN INSIDE THE PLOT. Plotly
    renders SVG <text>, which cannot be selected or copied. They are real
    HTML, so you can select and copy them.
  * RANGE BUTTONS LIVE IN THE CARD HEADER, not the figure, so screenshotting
    a chart no longer captures the 1Y/5Y/10Y/Max row.
  * LEGENDS CENTRED (they were hard-left).
  * Horizontal gridlines only, black axis lines/ticks/labels, y-axis title
    held clear of the tick labels.

EVENT STUDY
  * PER-EVENT BREAKDOWN TABLE: the individual event outcomes are shown BEFORE
    they are averaged, with each event's date and its move at every horizon.
  * OUTCOME SPREAD CHART REDRAWN FOR SMALL SAMPLES. With 4 events a density
    histogram is unreadable. With <= 12 events the baseline is drawn as a
    smooth density and each event becomes a labelled DOT with its date, so
    "3 crashed, 1 spiked" is obvious.
  * PLAIN-ENGLISH WALKTHROUGH built into the tab, using the live numbers.

MRC
  * FEATURE FLAGS ARE ACTUALLY READ. Every tab is gated on
    config.FEATURE_FLAGS["module_*"].
  * EM_FX gauge removed (see mrc.py v2 for the arithmetic), MOVE/Brent votes
    added, credit spreads + BTC supported, anti-flicker window settable in UI.
  * "Why is today X?" table: the per-gauge vote breakdown behind the label.

RUN
    python -m pip install dash plotly pandas feedparser requests
    python app.py            # -> http://127.0.0.1:9001
    (or just double-click EMDASH.bat)
"""
from __future__ import annotations

import re
import json
import math
import datetime as dt
import urllib.parse

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, ALL, MATCH

import config
import core
import database_tab
import runner
import signals as sig

import core
import database_tab

# --- tagging lives in news_ingest.py (single source of truth, ingest + display)
try:
    from news_ingest import topics_of, topics_of_many, tag_countries_many
except Exception:                                    # pragma: no cover
    def topics_of(_):
        return ["general"]

    def topics_of_many(xs):
        return [["general"] for _ in xs]

    def tag_countries_many(xs):
        return ["" for _ in xs]

try:
    import event_study as es
except Exception:
    es = None

try:
    import mrc
except Exception:
    mrc = None


# ===================================================================
# CONSTANTS
# ===================================================================
P = config.PALETTE
F = config.FONTS

PORT = 9001
CARDS_PER_COL = 15
EXPAND_EXTRA = 45          # max EXTRA cards built behind "+N more" (perf guard)
NEWS_READ_LIMIT = 4000
MAX_SPAGHETTI = 40
MAX_COMPARE = 5

DOMAIN_TIER = getattr(config, "DOMAIN_TIER", {})
FLAGS = getattr(config, "FEATURE_FLAGS", {})

# Cross-section bar: clip the DRAWN bar to this percentile band so one freak
# outlier can't squash every other bar. TRUE value stays in label + hover.
CROSS_CLIP = (2, 98)

# Below this many events, a density histogram is meaningless -- draw dots.
HIST_DOT_LIMIT = 12

COMPARE_COLORS = [P["navy1"], P["gold"], P["navy3"], P["good"], P["brown"]]

# ---- chart styling constants (GLOBAL RULE: horizontal gridlines only) -------
AXIS_BLACK = "#1A1A1A"
GRID_H = "#E6E9EF"
Y_TITLE_STANDOFF = 14      # pushes y-axis title clear of the tick labels
MARGIN_L = 92              # room for tick labels + title

# ---- news display (timezone + icons) ---------------------------------------
TZ_OFFSET_H = float(getattr(config, "NEWS_TZ_OFFSET_HOURS", 0) or 0)
TZ_LABEL = str(getattr(config, "NEWS_TZ_LABEL", "") or "")
SHOW_TZ_BADGE = bool(getattr(config, "NEWS_SHOW_TZ_BADGE", True))
SHOW_FAVICONS = bool(getattr(config, "SHOW_FAVICONS", False))
FAVICON_URL = getattr(config, "FAVICON_URL",
                      "https://icons.duckduckgo.com/ip3/{domain}.ico")

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

RANGE_OPTS = [("1Y", "1Y"), ("5Y", "5Y"), ("10Y", "10Y"), ("Max", "Max")]
RANGE_YEARS = {"1Y": 1, "5Y": 5, "10Y": 10}

NAME_BY_ISO = {i: n for i, n, *_ in config.COUNTRIES}
DESK_BY_ISO = {i: d for i, n, d, *_ in config.COUNTRIES}

# USA has no LCY-per-USD ticker (the dollar IS the base) but it DOES have a
# usable FX proxy via DXY -- see fx_frame(). v4 filtered on `if fx`, which
# silently dropped the US from the Event Study cross-section.
FX_ISOS = [i for i, n, d, dm, fx in config.COUNTRIES if fx or i == "USA"]

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

ES_SORTS = [("Excess (high -> low)", "edge_desc"),
            ("Excess (low -> high)", "edge_asc"),
            ("Biggest |excess|", "abs"), ("Mean", "mean"),
            ("Hit rate", "hit"), ("Country A-Z", "name")]

_PCT_LEVEL_INDS = {"GDP_YOY", "CPI_YOY", "CURR_ACC_GDP", "GOV_DEBT_GDP",
                   "UNEMPLOYMENT", "EXPORTS_GDP", "FDI_GDP", "POLICY_RATE"}
_GLOBAL_DIFF = {"US10Y", "VIX", "MOVE"}


# ===================================================================
# SOURCE ATTRIBUTION  ::  which provider does each series come from?
# Derived from config so it stays correct when you add indicators.
# ===================================================================
SOURCE_WB = "World Bank (WDI)"
SOURCE_DBN = "IMF / DBnomics"
SOURCE_YF = "Yahoo Finance"
SOURCE_FRED = "FRED / ICE BofA"


def source_for_indicator(indicator: str) -> str:
    if indicator in getattr(config, "WB_INDICATORS", {}):
        return SOURCE_WB
    if indicator in getattr(config, "DBN_SERIES", {}):
        return SOURCE_DBN
    return "-"


def source_for_global(key: str) -> str:
    if key in getattr(config, "FRED_SERIES", {}):
        return SOURCE_FRED
    return SOURCE_YF


def unit_for(indicator: str, transform: str) -> str:
    """What the THRESHOLD is measured in, given the signal + transform."""
    if isinstance(indicator, str) and ":" in indicator:
        return "pts"                    # prefixed global / commodity level
    if transform.startswith("Z-score"):
        return "sigma"
    if transform == "YoY" or transform.startswith("Momentum"):
        return "%"
    if indicator in _PCT_LEVEL_INDS:
        return "%"
    if indicator == "RESERVES_USD":
        return "USD"
    return "pts"


def _target_options():
    opts = [
        {"label": "- This country -", "value": "ctry:FX", "disabled": True},
        {"label": "This country - FX", "value": "ctry:FX"},
        {"label": "This country - Policy rate", "value": "ctry:POLICY_RATE"},
        {"label": "- Global markets -", "value": "glob:EMB", "disabled": True},
    ]
    for k in config.MARKET_TICKERS:
        opts.append({"label": f"Global - {k}", "value": f"glob:{k}"})
    for k in getattr(config, "FRED_SERIES", {}):
        opts.append({"label": f"Credit - {k}", "value": f"glob:{k}"})
    opts.append({"label": "- Commodities -", "value": "cmdty:BRENT",
                 "disabled": True})
    for k in config.COMMODITIES:
        opts.append({"label": f"Commodity - {k}", "value": f"cmdty:{k}"})
    return opts


TARGET_OPTS = _target_options()


def _signal_ind_options():
    """Signal choices: country indicators PLUS globals PLUS commodities.

    Country indicators stay BARE names (back-compat with saved state); globals
    and commodities use the target prefix scheme ('glob:VIX', 'cmdty:BRENT').
    """
    opts = [{"label": "- Country indicators -", "value": "GDP_YOY",
             "disabled": True}]
    opts += INDICATOR_OPTS
    opts.append({"label": "- Global markets (country ignored) -",
                 "value": "glob:VIX", "disabled": True})
    for k in config.MARKET_TICKERS:
        opts.append({"label": f"Global - {k}", "value": f"glob:{k}"})
    for k in getattr(config, "FRED_SERIES", {}):
        opts.append({"label": f"Credit - {k}", "value": f"glob:{k}"})
    opts.append({"label": "- Commodities (country ignored) -",
                 "value": "cmdty:BRENT", "disabled": True})
    for k in config.COMMODITIES:
        opts.append({"label": f"Commodity - {k}", "value": f"cmdty:{k}"})
    return opts


SIGNAL_IND_OPTS = _signal_ind_options()


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
        return "-"
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


def fx_frame(iso3):
    """FX for a country. USA has no LCY-per-USD series (the dollar IS the base),
    so we substitute DXY -- the dollar's own trade-weighted index -- which makes
    the USA row behave like every other country instead of showing 'no FX'."""
    df = cached_market(iso3, "FX")
    if (df is None or df.empty) and iso3 == "USA":
        g = cached_global("DXY")
        if g is not None and not g.empty:
            return g, "DXY (dollar index)"
    return df, "LCY per USD"


# ===================================================================
# NEWS LOADING
#
# PERFORMANCE NOTE (this is what made v4 slow):
# every heavy per-row operation here is now VECTORISED or delegated to a single
# combined regex in news_ingest.py. The two offenders were
#   * re-tagging with ~250 individually compiled regexes  (1,557 ms / 4k rows)
#   * pd.to_datetime called once PER ROW to format the timestamp (1,934 ms)
# Both are now one pass each. "Vectorised" = act on the whole column at once
# instead of asking pandas the same question row by row.
# ===================================================================
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_news_cache: dict = {"df": None}


def _format_times(ts_series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(local datetime, display string) for a whole column at once.

    Stored timestamps are UTC (feedparser normalises published_parsed to UTC;
    GDELT's seendate ends in 'Z'), so we shift by config.NEWS_TZ_OFFSET_HOURS
    before formatting. This is why v4's clock looked 8 hours out.
    """
    utc = pd.to_datetime(ts_series, errors="coerce")
    local = utc + pd.Timedelta(hours=TZ_OFFSET_H)
    disp = local.dt.strftime("%d %b %Y - %H:%M")
    return local, disp.fillna("")


def load_news(limit: int = NEWS_READ_LIMIT, force: bool = False) -> pd.DataFrame:
    """Processed news table, cached for the session."""
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

    heads = df["headline"].fillna("").tolist()
    df["topics"] = topics_of_many(heads)              # one combined regex
    df["domain"] = df["url"].map(_domain)
    df["tier"] = [DOMAIN_TIER.get(d, t)
                  for d, t in zip(df["domain"], df["tier"])]

    # --- re-derive country tags at DISPLAY time (repairs rows already in the
    # DB that were written by the old substring matcher -- no re-ingest needed)
    origin = getattr(config, "FEED_ORIGIN_ISO", {})
    tags = tag_countries_many(heads)                  # one combined regex
    df["iso3_tags"] = [t if t else (origin.get(s, "") or "")
                       for t, s in zip(tags, df["source_id"])]

    df["_dt"], df["_tsfmt"] = _format_times(df["ts"])  # vectorised
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
    out["_hay"] = (out["headline"].fillna("").str.lower() + " "
                   + out["domain"].fillna("").str.lower() + " "
                   + out["iso3_tags"].fillna("").str.lower())
    _news_cache["df"] = out
    return out


# ===================================================================
# SERIES TRANSFORMS
# ===================================================================
def _downsample(s, cap=800):
    return s.resample("W").last().dropna() if len(s) > cap else s


def _periods_per_year(s):
    if len(s) < 3:
        return 1
    gap = s.index.to_series().diff().dt.days.median()
    if gap <= 2:
        return 252
    if gap <= 10:
        return 52
    if gap <= 45:
        return 12
    if gap <= 120:
        return 4
    return 1


def apply_transform(s, name):
    if name == "YoY":
        return sig.yoy(s, periods=_periods_per_year(s))
    if name.startswith("Momentum"):
        return sig.momentum(s, periods=20)
    if name.startswith("Z-score"):
        return sig.zscore(s, window=20)
    return s


def rebase100(s: pd.Series) -> pd.Series:
    """Normalise a series to 100 at its first valid point."""
    s = s.dropna()
    if s.empty:
        return s
    base = s.iloc[0]
    if base == 0 or pd.isna(base):
        return s
    return s / base * 100.0


def _common_start(series_list):
    """Latest first-observation across a set of series.

    WHY: rebasing each series at its OWN start compares different time spans.
    US CPI starts ~1955 and HK CPI ~1980, so 'US 1200 vs HK 550' was mostly a
    25-year head start, not an inflation difference. Trimming everything to the
    latest common start makes the comparison honest.
    """
    starts = [s.index[0] for s in series_list if s is not None and not s.empty]
    return max(starts) if starts else None


def _apply_range(fig, rng, series_list):
    """Apply the HTML range pills to the figure's x-axis."""
    if not rng or rng == "Max":
        return fig
    yrs = RANGE_YEARS.get(rng)
    if not yrs:
        return fig
    ends = [s.index[-1] for s in series_list if s is not None and not s.empty]
    if not ends:
        return fig
    hi = max(ends)
    lo = hi - pd.DateOffset(years=yrs)
    fig.update_xaxes(range=[lo, hi])
    return fig


# ===================================================================
# FIGURES
#
# GLOBAL CHART RULE -- applies to EVERY chart in this app:
#   * horizontal gridlines ONLY (x gridlines off)
#   * black axis lines, ticks and tick labels
#   * y-axis title pushed clear of the tick labels (standoff + left margin)
#   * legend CENTRED
#
# HEIGHT IS OWNED HERE AND NOWHERE ELSE (v6). _fig() sets layout.height and
# that is the single source of truth. Do NOT add responsive=True or a style
# height to dcc.Graph, and do NOT add a min-height in CSS -- three competing
# height rules is exactly what broke every chart in v5.
#
# Chart TITLES and SOURCE lines are not drawn inside the figure -- they are
# HTML in the card header, so the text can be selected and copied, and so a
# screenshot of the plot doesn't include the range buttons.
# ===================================================================
def _ytick_format(unit: str) -> str:
    if unit in ("%", "pp", "sigma"):
        return ".1f"
    if unit == "USD":
        return "~s"
    return ""


def _fig(height=320, ytitle="", yunit="", xtitle="",
         nticks_x=None, nticks_y=None):
    fig = go.Figure()

    xaxis = dict(showgrid=False, zeroline=False,
                 showline=True, linecolor=AXIS_BLACK, linewidth=1,
                 ticks="outside", tickcolor=AXIS_BLACK,
                 tickfont=dict(color=AXIS_BLACK, size=10.5),
                 automargin=True, showspikes=True, spikethickness=1,
                 spikedash="dot", spikecolor=P["muted"], spikemode="across")
    if xtitle:
        xaxis["title"] = dict(text=xtitle,
                              font=dict(size=10.5, color=AXIS_BLACK),
                              standoff=10)
    if nticks_x:
        xaxis["nticks"] = nticks_x

    yaxis = dict(showgrid=True, gridcolor=GRID_H, gridwidth=1,
                 zeroline=True, zerolinecolor="#C9CED8", zerolinewidth=1,
                 showline=True, linecolor=AXIS_BLACK, linewidth=1,
                 ticks="outside", tickcolor=AXIS_BLACK,
                 tickfont=dict(color=AXIS_BLACK, size=10.5),
                 automargin=True)
    if ytitle:
        yaxis["title"] = dict(text=ytitle,
                              font=dict(size=10.5, color=AXIS_BLACK),
                              standoff=Y_TITLE_STANDOFF)
    if nticks_y:
        yaxis["nticks"] = nticks_y

    fmt = _ytick_format(yunit)
    if fmt:
        yaxis["tickformat"] = fmt

    fig.update_layout(
        template="plotly_white", hovermode="x unified",
        font=dict(family=F["ui"], color=P["ink"], size=11),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=MARGIN_L, r=22, t=42, b=46), height=height,
        colorway=[P["navy2"], P["gold"], P["navy3"], P["good"], P["bad"]],
        xaxis=xaxis, yaxis=yaxis, showlegend=False,
    )
    return fig


def _legend(fig, on=True):
    """Centred horizontal legend, sitting fully ABOVE the plot -- the global
    convention. yanchor='bottom' pins the legend's bottom edge just over the
    plot so it never dips into the data, however many series there are."""
    if on:
        fig.update_layout(showlegend=True,
                          legend=dict(orientation="h", yanchor="bottom",
                                      y=1.02, x=0.5, xanchor="center"))
    return fig


def _empty(fig, msg):
    fig.add_annotation(text=msg, showarrow=False, font=dict(color=P["muted"]))
    return fig


def _ytitle_for(indicator, transform, unit, normalise=False):
    if normalise:
        return "Index (common start = 100)"
    if transform == "YoY":
        return "% YoY"
    if transform.startswith("Momentum"):
        return "% (20d)"
    if transform.startswith("Z-score"):
        return "sigma (z-score)"
    if unit == "%":
        return "%"
    if unit == "USD":
        return "USD"
    return "level"


def _last_marker(fig, s, color, unit=""):
    if s is None or s.empty:
        return
    x, y = s.index[-1], float(s.iloc[-1])
    fig.add_trace(go.Scatter(
        x=[x], y=[y], mode="markers", showlegend=False,
        marker=dict(size=7, color=color),
        hovertemplate=f"latest {_human(y)}{unit}<extra></extra>"))
    fig.add_annotation(x=x, y=y, text=f"  {_human(y)}{unit}", showarrow=False,
                       xanchor="left", font=dict(size=10, color=color))


def _as_iso_list(isos):
    if isinstance(isos, str):
        isos = [isos]
    out = []
    for i in (isos or []):
        if i and i not in out:
            out.append(i)
    return out[:MAX_COMPARE]


# ===================================================================
# CHART CARD FURNITURE  (HTML title / provenance chip / range pills / source)
# ===================================================================
def _prov_chip(transform, normalise=False):
    """RAW = straight from the warehouse. CALC = computed by signals.py."""
    calc = (transform != "Level") or normalise
    if not calc:
        return html.Span("RAW", className="emd-prov emd-prov--raw",
                         title="Values exactly as stored in emdash.sqlite")
    bits = []
    if transform != "Level":
        bits.append(transform)
    if normalise:
        bits.append("normalised")
    return html.Span(f"CALC - {' + '.join(bits)}",
                     className="emd-prov emd-prov--calc",
                     title="Computed on the fly by signals.py (not stored)")


def _range_pills(rid, value="Max"):
    return dcc.RadioItems(
        id=rid, value=value, className="emd-range", inline=True,
        options=[{"label": lbl, "value": v} for lbl, v in RANGE_OPTS])


def _graph(graph_id=None, figure=None):
    """The ONE place a dcc.Graph is constructed.

    v6: config dict only. No responsive flag, no style height -- the figure's
    own layout.height (set in _fig) is the single source of truth. Routing
    every graph through here means a future sizing change is a one-line edit
    instead of six scattered ones.
    """
    kwargs = {"config": {"displayModeBar": False}}
    if graph_id is not None:
        kwargs["id"] = graph_id
    if figure is not None:
        kwargs["figure"] = figure
    return dcc.Graph(**kwargs)


def chart_card(graph_id, *, title_id=None, sub_id=None, source_id=None,
               prov_id=None, range_id=None, range_value="Max", height=None):
    """A chart island: HTML header (selectable text, screenshot-safe) + figure.

    Everything except the plot itself is HTML so it can be selected and copied,
    and so screenshotting the chart doesn't capture the range buttons.

    NOTE: `height` is accepted but unused -- figure height is owned by _fig().
    Kept so existing call sites keep working unchanged.
    """
    head_left = [html.Div(id=title_id, className="emd-chart-title")]
    if sub_id:
        head_left.append(html.Div(id=sub_id, className="emd-chart-sub"))

    head = [html.Div(head_left, className="emd-chart-titlewrap")]
    if prov_id:
        head.append(html.Div(id=prov_id))

    kids = []
    if range_id:
        kids.append(html.Div(_range_pills(range_id, range_value),
                             className="emd-range-row"))
    kids.append(html.Div(head, className="emd-chart-head"))
    kids.append(_graph(graph_id))

    if source_id:
        kids.append(html.Div(id=source_id, className="emd-chart-source"))
    return html.Div(kids, className="emd-card")


def source_line(src) -> str:
    if not src:
        return ""
    if isinstance(src, (list, tuple, set)):
        txt = ", ".join(dict.fromkeys([s for s in src if s and s != "-"]))
    else:
        txt = str(src)
    return f"Source: {txt}" if txt else ""


# ===================================================================
# COUNTRY FIGURES
# ===================================================================
def macro_fig(isos, indicator, transform, normalise=False, rng="Max"):
    isos = _as_iso_list(isos)
    unit = unit_for(indicator, transform)
    multi = len(isos) > 1
    fig = _fig(ytitle=_ytitle_for(indicator, transform, unit, normalise),
               yunit=("" if normalise else unit))

    series = []
    for iso3 in isos:
        df = cached_series(iso3, indicator)
        if df is None or df.empty:
            series.append((iso3, None))
            continue
        s = apply_transform(df.set_index("date")["value"], transform).dropna()
        series.append((iso3, s if not s.empty else None))

    live = [s for _, s in series if s is not None]
    if not live:
        return _empty(fig, "no data - run ingest.py")

    # common-start rebasing (see _common_start for why)
    cut = _common_start(live) if (normalise and multi) else None
    for k, (iso3, s) in enumerate(series):
        if s is None:
            continue
        if cut is not None:
            s = s[s.index >= cut]
        y = _downsample(s)
        if normalise:
            y = rebase100(y)
        if y.empty:
            continue
        mode = "lines+markers" if len(y) < 60 else "lines"
        color = COMPARE_COLORS[k % len(COMPARE_COLORS)]
        nm = NAME_BY_ISO.get(iso3, iso3)
        suffix = "" if normalise else unit
        fig.add_trace(go.Scatter(
            x=y.index, y=y.values, mode=mode,
            line=dict(width=2, color=color), marker=dict(size=5),
            fill=("tozeroy" if (not multi and not normalise) else None),
            fillcolor="rgba(31,73,125,.06)", name=nm,
            hovertemplate=f"{nm}<br>%{{y:.2f}}{suffix}<extra></extra>"))
        if not multi:
            _last_marker(fig, y, color, unit=suffix)

    _legend(fig, multi)
    if transform.startswith("Z-score"):
        fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    _apply_range(fig, rng, live)
    return fig


def fx_fig(isos, transform, normalise=False, rng="Max"):
    isos = _as_iso_list(isos)
    multi = len(isos) > 1
    pct = transform in ("YoY",) or transform.startswith("Momentum")
    unit = "%" if pct else "level"
    ytitle = ("Index (common start = 100)" if normalise
              else ("% change" if pct else "LCY per USD"))
    fig = _fig(ytitle=ytitle, yunit=("" if normalise else unit))

    series, notes = [], set()
    for iso3 in isos:
        df, note = fx_frame(iso3)
        if df is None or df.empty:
            series.append((iso3, None))
            continue
        notes.add(note)
        s = apply_transform(df.set_index("date")["value"], transform).dropna()
        series.append((iso3, s if not s.empty else None))

    live = [s for _, s in series if s is not None]
    if not live:
        return _empty(fig, "no FX (peg / n.a.)")

    cut = _common_start(live) if (normalise and multi) else None
    for k, (iso3, s) in enumerate(series):
        if s is None:
            continue
        if cut is not None:
            s = s[s.index >= cut]
        y = _downsample(s)
        if normalise:
            y = rebase100(y)
        if y.empty:
            continue
        color = COMPARE_COLORS[k % len(COMPARE_COLORS)] if multi else P["gold"]
        nm = NAME_BY_ISO.get(iso3, iso3)
        fig.add_trace(go.Scatter(
            x=y.index, y=y.values, mode="lines",
            line=dict(width=2, color=color), name=nm,
            hovertemplate=f"{nm}<br>%{{y:.3f}}<extra></extra>"))
        if not multi:
            _last_marker(fig, y, P["brown"])

    _legend(fig, multi)
    _apply_range(fig, rng, live)
    return fig


def mini_fig(isos, indicator, transform="Level", normalise=False):
    """Small multiple. Explicit tick counts (Plotly auto-thinned them to
    2-3 at this height) and optional multi-country overlay."""
    isos = _as_iso_list(isos)
    unit = unit_for(indicator, transform)
    multi = len(isos) > 1
    fig = _fig(height=270,
               ytitle=_ytitle_for(indicator, transform, unit, normalise),
               yunit=("" if normalise else unit), nticks_x=6, nticks_y=5)
    fig.update_layout(margin=dict(l=78, r=14, t=72, b=34)) 

    series = []
    for iso3 in isos:
        df = cached_series(iso3, indicator)
        if df is None or df.empty:
            continue
        s = apply_transform(df.set_index("date")["value"], transform).dropna()
        if not s.empty:
            series.append((iso3, s))
    if not series:
        return _empty(fig, "-")

    cut = _common_start([s for _, s in series]) if (normalise and multi) else None
    for k, (iso3, s) in enumerate(series):
        if cut is not None:
            s = s[s.index >= cut]
        y = _downsample(s)
        if normalise:
            y = rebase100(y)
        if y.empty:
            continue
        mode = "lines+markers" if len(y) < 60 else "lines"
        color = COMPARE_COLORS[k % len(COMPARE_COLORS)]
        nm = NAME_BY_ISO.get(iso3, iso3)
        fig.add_trace(go.Scatter(
            x=y.index, y=y.values, mode=mode,
            line=dict(width=1.6, color=color), marker=dict(size=4), name=nm,
            hovertemplate=f"{nm}<br>%{{y:.2f}}<extra></extra>"))

    _legend(fig, multi)
    if transform.startswith("Z-score"):
        fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    return fig


# ===================================================================
# NEWS RENDERING
# ===================================================================
def _favicon(domain):
    if not (SHOW_FAVICONS and domain):
        return None
    return html.Img(src=FAVICON_URL.format(domain=domain),
                    className="emd-favicon", title=domain)


def _slim_row(r):
    """Minimal JSON-safe row for lazy-loaded cards (no Timestamps)."""
    return {k: r.get(k) for k in ("tier", "source_id", "domain", "_tsfmt",
            "_desks", "iso3_tags", "headline", "url", "dupes", "sources")}

def _news_card(row):
    tier = row["tier"] or "?"
    tcls = tier if tier in ("A", "B", "C") else "U"
    src = row["domain"] or row["source_id"] or ""

    meta = []
    ico = _favicon(row.get("domain"))
    if ico is not None:
        meta.append(ico)
    meta.append(html.Span(src, className="emd-news-src"))
    meta.append(html.Span("-", className="emd-news-dot"))
    meta.append(html.Span(row.get("_tsfmt") or "", className="emd-news-time"))
    if SHOW_TZ_BADGE and TZ_LABEL:
        meta.append(html.Span(TZ_LABEL, className="emd-news-tz",
                              title=f"Stored in UTC, shown in {TZ_LABEL} "
                                    f"(UTC{TZ_OFFSET_H:+.0f})"))

    top = [html.Span(tier, className=f"emd-tier emd-tier--{tcls}",
                     title=f"Source Tier: {tier}")]
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
        links = [html.A(f"{dom or 'source'}", href=url, target="_blank")
                 for dom, url in row["sources"][1:]]
        children.append(html.Details([
            html.Summary(f"+{dupes} more source{'s' if dupes > 1 else ''}"),
            html.Div(links, className="emd-src-list"),
        ], className="emd-more"))
    return html.Div(children, className="emd-news")


def _column_keys(row, columns_by):
    if columns_by == "Topic":
        return [TOPIC_LABELS.get(t, t) for t in row["topics"]]
    if columns_by == "Source Tier":
        return [f"Source Tier {row['tier']}" if row["tier"]
                else "Source Tier ?"]
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
        return f"{col} - {NAME_BY_ISO[col]}"
    return col


def news_board(columns_by, desks, tiers, topics, days, search=""):
    df = load_news()
    if df.empty:
        return html.Div("No news yet - run  python news_ingest.py",
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

    q = (search or "").strip().lower()
    if q:
        sub = sub[sub["_hay"].str.contains(re.escape(q), na=False)]
    if sub.empty:
        msg = (f"No headlines match '{search}'." if q
               else "No headlines match these filters / date range.")
        return html.Div(msg, style={"padding": "28px", "color": P["muted"]})

    cols: dict[str, list] = {}
    for row in sub.to_dict("records"):
        for key in _column_keys(row, columns_by):
            cols.setdefault(key, []).append(row)

    board = []
    for col in _order_columns(cols, columns_by):
        items = cols[col]
        total = len(items)
        cards = [_news_card(r) for r in items[:CARDS_PER_COL]]
        if total > CARDS_PER_COL:
            rest = items[CARDS_PER_COL:CARDS_PER_COL + EXPAND_EXTRA]
            hidden = total - CARDS_PER_COL - len(rest)
            cards.append(html.Div([
                html.Button(f"+ {total - CARDS_PER_COL} more - click to load",
                            id={"type": "news-more-btn", "col": col},
                            n_clicks=0, className="emd-btn emd-btn--ghost"),
                dcc.Store(id={"type": "news-more-store", "col": col},
                          data=[_slim_row(r) for r in rest]),
                html.Div(id={"type": "news-more-wrap", "col": col}),
                (html.Div(f"...{hidden} more beyond that - narrow the filter.",
                          className="emd-col-hint") if hidden > 0
                 else html.Div()),
            ], className="emd-col-more"))
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
            val, date = "-", ""
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


def indicator_grid(isos, transform="Level", normalise=False, compare=False):
    use = isos if compare else isos[:1]
    cards = []
    for ind in config.WB_INDICATORS:
        cards.append(html.Div([
            html.Div([
                html.Div([html.Div(ind, className="emd-chart-title")],
                         className="emd-chart-titlewrap"),
                _prov_chip(transform, normalise),
            ], className="emd-chart-head"),
            _graph(figure=mini_fig(use, ind, transform, normalise)),
            html.Div(source_line(source_for_indicator(ind)),
                     className="emd-chart-source"),
        ], className="emd-card"))
    return html.Div(cards, className="emd-grid-mini")


# ===================================================================
# EVENT STUDY RENDERING
# ===================================================================
def _signal_series(iso3, indicator, transform):
    if isinstance(indicator, str) and ":" in indicator:
        grp, _, key = indicator.partition(":")
        df = cached_global(key) if grp == "glob" else cached_commodity(key)
        if df is None or df.empty:
            return pd.Series(dtype=float)
        return apply_transform(df.set_index("date")["value"], transform).dropna()
    df = cached_series(iso3, indicator)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    return apply_transform(df.set_index("date")["value"], transform).dropna()


def _signal_name(iso3, indicator):
    if isinstance(indicator, str) and ":" in indicator:
        grp, _, key = indicator.partition(":")
        return f"{key} ({'global' if grp == 'glob' else 'commodity'})"
    return f"{NAME_BY_ISO.get(iso3, iso3)} - {indicator}"


def _signal_source(indicator):
    if isinstance(indicator, str) and ":" in indicator:
        grp, _, key = indicator.partition(":")
        return source_for_global(key) if grp == "glob" else SOURCE_YF
    return source_for_indicator(indicator)


def resolve_target(target_value, country):
    grp, _, key = (target_value or "ctry:FX").partition(":")
    cname = NAME_BY_ISO.get(country, country)

    if grp == "ctry" and key == "FX":
        df, note = fx_frame(country)
        s = (df.set_index("date")["value"].dropna()
             if (df is not None and not df.empty) else pd.Series(dtype=float))
        return s, "pct", f"{cname} FX", "%", SOURCE_YF

    if grp == "ctry" and key == "POLICY_RATE":
        df = cached_series(country, "POLICY_RATE")
        s = (df.set_index("date")["value"].dropna()
             if not df.empty else pd.Series(dtype=float))
        return s, "diff", f"{cname} policy rate", "pp", SOURCE_DBN

    if grp == "glob":
        df = cached_global(key)
        s = (df.set_index("date")["value"].dropna()
             if not df.empty else pd.Series(dtype=float))
        kind = "diff" if key in _GLOBAL_DIFF else "pct"
        return (s, kind, f"{key}", ("pt" if kind == "diff" else "%"),
                source_for_global(key))

    if grp == "cmdty":
        df = cached_commodity(key)
        s = (df.set_index("date")["value"].dropna()
             if not df.empty else pd.Series(dtype=float))
        return s, "pct", f"{key}", "%", SOURCE_YF

    return pd.Series(dtype=float), "pct", str(target_value), "%", "-"


def es_helper(signal, unit, sig_name, transform, rule, threshold):
    if signal.empty:
        return html.Div("No data for this signal - pick another indicator, or "
                        "run ingest.py.", className="emd-es-helper emd-es-warn")

    cur = float(signal.iloc[-1])
    lo, hi, med = float(signal.min()), float(signal.max()), float(signal.median())

    n_fired = 0
    if es is not None:
        try:
            n_fired = int(es.make_events(signal, rule=rule,
                                         threshold=float(threshold)).sum())
        except Exception:
            n_fired = 0

    def f(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "-"
        return f"{v:,.0f}" if unit == "USD" else f"{v:,.1f}{unit}"

    return html.Div([
        html.Span(f"{sig_name} - {transform}", className="emd-es-helper-lead"),
        html.Span(f"  Current {f(cur)}", className="emd-es-cur"),
        html.Span(f"  -  Range {f(lo)} to {f(hi)}"),
        html.Span(f"  -  Median {f(med)}"),
        html.Span("  -  this threshold fires "),
        html.Span(f"{n_fired} events",
                  className="emd-es-fires"
                            + ("" if n_fired >= 5 else " emd-es-few")),
    ], className="emd-es-helper")


def es_path_fig(res, unit):
    yfac = 100 if unit == "%" else 1
    ytitle = "Cumulative %" if unit == "%" else f"Cumulative move ({unit})"
    fig = _fig(height=380, ytitle=ytitle, xtitle="Trading days after event")
    fig.update_layout(hovermode="x")
    _legend(fig, True)

    if res is None or res.path.empty:
        return _empty(fig, "no events - loosen the rule / move the threshold")

    paths = res.paths
    for c in list(paths.columns)[:MAX_SPAGHETTI]:
        fig.add_trace(go.Scatter(
            x=list(paths.index), y=(paths[c].values * yfac), mode="lines",
            line=dict(width=0.6, color="rgba(101,147,196,.28)"),
            showlegend=False, hoverinfo="skip"))

    med, lo, hi = es.path_band(paths, 25, 75)
    fig.add_trace(go.Scatter(x=list(hi.index), y=(hi.values * yfac),
                             mode="lines", line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=list(lo.index), y=(lo.values * yfac),
                             mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor="rgba(31,73,125,.10)",
                             name="25-75% band", hoverinfo="skip"))

    if not res.base_path.empty:
        fig.add_trace(go.Scatter(
            x=list(res.base_path.index), y=(res.base_path.values * yfac),
            mode="lines", name="Baseline (any day)",
            line=dict(width=1.5, color=P["grey"], dash="dot")))

    fig.add_trace(go.Scatter(
        x=list(res.path.index), y=(res.path.values * yfac),
        mode="lines", name="Mean after event",
        line=dict(width=2.8, color=P["navy2"])))
    fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    return fig


def es_headline(res, tgt_label, unit, pval=None):
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
    med20 = res.summary.loc[20, "median"]
    if mean20 is None or math.isnan(mean20):
        return html.Div("Not enough forward data at the 20-day horizon.",
                        className="emd-es-headline")

    edge = mean20 - base20
    fac = 100 if unit == "%" else 1
    up = mean20 > 0
    consistent = round(hit * n) if up else round((1 - hit) * n)
    verb = "rose" if up else "fell"

    main = (f"{tgt_label} {verb} ~{abs(mean20)*fac:.1f}{unit} over the next "
            f"20 trading days - {consistent} of {n} times.")
    sub = (f"vs a normal 20-day move of {base20*fac:+.1f}{unit}  ->  "
           f"excess vs baseline {edge*fac:+.1f}{unit}   "
           f"(this excess is the signal; everything else is context)")
    kids = [html.Div(main, className="emd-es-head-main"),
            html.Div(sub, className="emd-es-head-sub")]

    if pval and pval.get("n"):
        beat = pval.get("pct_beaten")
        p1 = pval.get("p_one_sided")
        if beat is not None and not math.isnan(beat):
            strong = (p1 is not None and p1 <= 0.10)
            kids.append(html.Div(
                f"Permutation test: this beat {beat*100:.0f}% of random "
                f"same-size draws (one-sided p={p1:.2f}). "
                + ("Unlikely to be luck." if strong else
                   "Could easily be luck - treat as weak."),
                className="emd-es-head-p" + ("" if strong else " emd-es-weak")))

    # mean-vs-median divergence: the single most useful sanity check
    if med20 is not None and not math.isnan(med20) and n >= 2:
        gap = abs(mean20 - med20) * fac
        if gap > abs(mean20 * fac) * 0.5 and gap > 0.5:
            kids.append(html.Div(
                f"Note: the MEDIAN outcome ({med20*fac:+.1f}{unit}) is far from "
                f"the MEAN ({mean20*fac:+.1f}{unit}). One or two extreme events "
                f"are pulling the average - the median is the more honest read "
                f"here.", className="emd-es-head-p emd-es-weak"))

    if n < 5:
        kids.append(html.Div(
            f"Only {n} event{'s' if n != 1 else ''} - this is an ANECDOTE, "
            "not a signal. Loosen the rule for more events before trusting it.",
            className="emd-es-warn-big"))
    return html.Div(kids, className="emd-es-headline")


def es_walkthrough(res, tgt_label, sig_name, unit, horizon=20):
    """The arithmetic, in words, using the live numbers.

    The plain-English explanation lives IN the tab so other people can read
    this without you narrating it.
    """
    if res is None or res.n_events == 0:
        return html.Div()

    fac = 100 if unit == "%" else 1
    try:
        n = int(res.summary.loc[horizon, "n"])
        mean = float(res.summary.loc[horizon, "mean"]) * fac
        base = float(res.baseline.loc[horizon, "mean"]) * fac
        med = float(res.summary.loc[horizon, "median"]) * fac
    except Exception:
        return html.Div()

    def eq(t):
        return html.Span(t, className="emd-explain-eq")

    return html.Details([
        html.Summary("How this number was worked out (click)"),
        html.Div([
            html.Div("Three questions, in order. Everything on this page is one "
                     "of the three.", className="emd-explain-lead"),
            html.Div([html.B("1. Did something unusual happen? "),
                      f"Your rule was applied to {sig_name} across its whole "
                      f"history. Every date where the rule was true is an "
                      f"'event'. It fired ", eq(f"{n} times"), "."],
                     className="emd-explain-step"),
            html.Div([html.B("2. What happened next? "),
                      f"From each of those {n} dates we look forward {horizon} "
                      f"steps at {tgt_label} and measure the move. That gives "
                      f"{n} numbers (listed in the table below). Their average "
                      f"is ", eq(f"{mean:+.2f}{unit}"),
                      ", and the middle one is ", eq(f"{med:+.2f}{unit}"), "."],
                     className="emd-explain-step"),
            html.Div([html.B("3. Is that actually unusual? "),
                      "We repeat the exact same measurement starting from EVERY "
                      "day in history, not just event days. That average is the "
                      "baseline: ", eq(f"{base:+.2f}{unit}"),
                      ". It is what a random ", f"{horizon}-step ",
                      "period looks like."],
                     className="emd-explain-step"),
            html.Div([html.B("The answer. "), "Subtract: ",
                      eq(f"{mean:+.2f} - ({base:+.2f}) = {mean-base:+.2f}{unit}"),
                      ". That is the 'Excess vs baseline' - the only number that "
                      "matters. If it were near zero, the event told you nothing."],
                     className="emd-explain-step"),
            html.Div("Everything else on this page exists to stop you fooling "
                     "yourself: the event count (small = fragile), the band "
                     "(did events behave alike?), the mean-vs-median gap (is one "
                     "freak event driving the average?) and the permutation "
                     "p-value (could luck do this?).",
                     className="emd-explain-foot"),
        ], className="emd-explain-body"),
    ], className="emd-explain", open=False)


def es_events_table(res, unit, horizons=ES_HORIZONS):
    """The individual event outcomes, BEFORE they are averaged."""
    if res is None or res.detail is None or res.detail.empty:
        return html.Div()

    fac = 100 if unit == "%" else 1
    d = res.detail
    heads = ["#", "Event date"] + [f"{h}d {unit}" for h in horizons]
    thead = html.Thead(html.Tr([html.Th(h) for h in heads]))

    body = []
    for i, (_, r) in enumerate(d.iterrows(), start=1):
        cells = [html.Td(str(i)),
                 html.Td(str(pd.to_datetime(r["event_date"]).date()))]
        for h in horizons:
            v = r.get(f"h{h}")
            if v is None or (isinstance(v, float) and math.isnan(v)):
                cells.append(html.Td("-"))
            else:
                val = v * fac
                cls = "emd-pos" if val > 0 else ("emd-neg" if val < 0 else "")
                cells.append(html.Td(f"{val:+.2f}", className=cls))
        body.append(html.Tr(cells))

    return html.Div([
        html.Div("Every event, before averaging", className="emd-events-title"),
        html.Table([thead, html.Tbody(body)], className="emd-table"),
        html.Div("These are the raw numbers the 'Mean' row averages. If they "
                 "disagree wildly with each other, the average is not telling "
                 "you much - look at the median instead.",
                 className="emd-events-note"),
    ], className="emd-events")


def _col_legend(cross=False):
    items = [
        ("Events", "how many times the signal fired (small = fragile)"),
        ("Mean", "average target move after the event"),
        ("Base", "average move on any random day (the benchmark)"),
        ("Excess", "Mean minus Base - the signal (what the event added over normal)"),
        ("Hit %", "how often the move was positive after the event"),
    ]
    if not cross:
        items += [("Base hit %", "how often positive on any random day"),
                  ("Median", "the middle outcome (robust to one weird event)"),
                  ("p (perm)", "permutation p-value: how often random draws beat "
                               "this (small = unlikely luck)")]
    return html.Div(
        [html.Span("How to read: ", className="emd-legend-lead")]
        + [html.Span([html.B(k + " "), v + "   -  "],
                     className="emd-legend-item") for k, v in items],
        className="emd-legend")


def es_table(res, unit, pvals=None):
    if res is None or res.n_events == 0:
        return html.Div("No events.",
                        style={"padding": "14px", "color": P["muted"]})

    pvals = pvals or {}
    fac = 100 if unit == "%" else 1
    cmp = res.compare()
    heads = ["Horizon", "Events", f"Mean {unit}", f"Base {unit}",
             f"Excess {unit}", "Hit %", "Base hit %", f"Median {unit}",
             "p (perm)"]
    thead = html.Thead(html.Tr([html.Th(h) for h in heads]))

    body = []
    for h, r in cmp.iterrows():
        edge = r["edge"] * fac
        cls = "emd-pos" if edge > 0 else ("emd-neg" if edge < 0 else "")
        pv = pvals.get(int(h))
        pcell = ("-" if (pv is None or (isinstance(pv, float) and math.isnan(pv)))
                 else f"{pv:.2f}")
        pcls = "emd-pos" if (isinstance(pv, float) and pv <= 0.10) else ""
        body.append(html.Tr([
            html.Td(f"{h}d"), html.Td(f"{int(r['n_events'])}"),
            html.Td(f"{r['mean']*fac:+.2f}"),
            html.Td(f"{r['base_mean']*fac:+.2f}"),
            html.Td(f"{edge:+.2f}", className=cls),
            html.Td(f"{r['hit_rate']*100:.0f}"),
            html.Td(f"{r['base_hit_rate']*100:.0f}"),
            html.Td(f"{r['median']*fac:+.2f}"),
            html.Td(pcell, className=pcls),
        ]))

    return html.Div([_col_legend(cross=False),
                     html.Table([thead, html.Tbody(body)],
                                className="emd-table")])


def es_hist_fig(res, ev_out, base_out, unit, horizon):
    """Outcome spread.

    With a handful of events a density histogram is unreadable -- v4 drew
    three spikes at 0.6 / 0.25 with no context. Below HIST_DOT_LIMIT events the
    baseline is drawn as a smooth density and each event becomes a labelled DOT
    at its own outcome, so you can see "3 crashed, 1 spiked" immediately.
    """
    yfac = 100 if unit == "%" else 1
    xt = "outcome %" if unit == "%" else f"outcome ({unit})"
    n_ev = 0 if ev_out is None else len(ev_out)
    fig = _fig(height=320, xtitle=xt,
               ytitle=("density" if n_ev > HIST_DOT_LIMIT else "each event"))
    fig.update_layout(hovermode="closest")
    _legend(fig, True)
    if n_ev == 0:
        return _empty(fig, "no events to plot")

    if base_out is not None and len(base_out):
        b = pd.Series([v * yfac for v in base_out])
        if n_ev > HIST_DOT_LIMIT:
            fig.add_trace(go.Histogram(
                x=b, name="Baseline (any day)", marker_color=P["grey"],
                opacity=0.45, histnorm="probability density", nbinsx=40))
        else:
            # smooth-ish density via a fine histogram, drawn as a filled area
            cnt, edges = np.histogram(b.values, bins=60, density=True)
            centres = [(edges[i] + edges[i + 1]) / 2
                       for i in range(len(edges) - 1)]
            mx = max(cnt) if len(cnt) else 1
            ys = [c / mx for c in cnt]
            fig.add_trace(go.Scatter(
                x=centres, y=ys, mode="lines", name="Baseline (any day)",
                line=dict(width=1.4, color=P["grey"]), fill="tozeroy",
                fillcolor="rgba(147,157,170,.25)", hoverinfo="skip"))

    if n_ev > HIST_DOT_LIMIT:
        fig.add_trace(go.Histogram(
            x=[v * yfac for v in ev_out], name="After event",
            marker_color=P["navy2"], opacity=0.65,
            histnorm="probability density", nbinsx=40))
    else:
        try:
            dates = [str(pd.to_datetime(d).date())
                     for d in res.detail["event_date"]]
        except Exception:
            dates = [""] * n_ev
        xs = [v * yfac for v in ev_out]
        ys = [0.5] * n_ev
        cols = [P["good"] if x > 0 else P["bad"] for x in xs]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text", name="Each event",
            marker=dict(size=15, color=cols, line=dict(width=1.5, color="#fff")),
            text=[d[:7] for d in dates], textposition="top center",
            textfont=dict(size=9.5, color=P["ink"]), customdata=dates,
            hovertemplate="%{customdata}<br>%{x:+.2f}" + unit + "<extra></extra>"))
        fig.update_yaxes(range=[0, 1.25], showticklabels=False)

    fig.add_vline(x=float(pd.Series(ev_out).mean() * yfac), line_dash="dash",
                  line_color=P["navy1"], annotation_text="event mean",
                  annotation_font=dict(size=9, color=P["navy1"]))
    fig.add_vline(x=0, line_dash="dot", line_color=P["muted"])
    return fig


def es_explain_panel():
    def item(term, body):
        return html.Div([html.B(term + " - "), body],
                        className="emd-explain-item")

    return html.Details([
        html.Summary("What am I looking at? (click)"),
        html.Div([
            html.Div("One question: when your SIGNAL fires, what did the TARGET "
                     "typically do next - and is that any different from a "
                     "normal day?", className="emd-explain-lead"),
            item("Signal", "any series plus a rule, e.g. 'US policy rate crosses "
                           "above 5%'. Every date where the rule is true is an "
                           "event."),
            item("Target", "the thing you want to watch afterwards - an FX rate, "
                           "a commodity, a global index."),
            item("Mean after event (navy line)",
                 "the average path of the target in the days after the signal "
                 "fired."),
            item("Baseline (grey dotted)",
                 "the average path starting from ANY random day in history. It "
                 "is the boring 'normal drift'. The GAP between navy and grey "
                 "is the whole point - that gap is the 'Excess vs baseline'. If "
                 "the two lines sit together, the event added nothing."),
            item("25-75% band (shaded)",
                 "the middle 50% of individual events. Narrow = events behaved "
                 "alike (trust the average). Wide = wildly mixed (the average "
                 "means little)."),
            item("Faint lines", "each individual event's own path."),
            item("Permutation p-value",
                 "instead of a t-stat (which overstates significance when event "
                 "windows overlap), we draw random 'fake events' thousands of "
                 "times and ask how often luck beats the real result. Small p = "
                 "unlikely luck."),
            html.Div("Descriptive, not predictive: this generates hypotheses. "
                     "Always check the event count (small = fragile) and the "
                     "dispersion before trusting a headline.",
                     className="emd-explain-foot"),
        ], className="emd-explain-body"),
    ], className="emd-explain", open=False)


def _cross_targets(kind_key):
    out = {}
    for iso in FX_ISOS:
        if kind_key == "FX":
            df, _ = fx_frame(iso)
        else:
            df = cached_series(iso, "POLICY_RATE")
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
    return xs.sort_values("edge", ascending=False)


def es_cross_fig(xs, horizon, xtarget_label, unit="%"):
    """Rate targets are already in percentage POINTS, so multiplying by 100
    turned an 11.7pp move into '+1169.6%'. `unit` drives the scaling."""
    fac = 100 if unit == "%" else 1
    n = len(xs) if xs is not None else 0
    height = max(420, 26 * n + 150)
    fig = _fig(height=height,
               xtitle=f"Excess {unit} (event mean - own baseline)")
    fig.update_layout(margin=dict(l=170, r=84, t=18, b=52),
                      hovermode="closest", uniformtext_minsize=9,
                      uniformtext_mode="hide")
    if xs is None or xs.empty:
        return _empty(fig, "no events / no data - loosen the rule")

    xsb = xs.sort_values("edge")
    isos = list(xsb.index)
    labels = [f"{NAME_BY_ISO.get(i,i)} ({i})" for i in isos]
    edges = (xsb["edge"] * fac).tolist()

    drawn = list(edges)
    clipped = [False] * len(edges)
    if CROSS_CLIP and len(edges) >= 5:
        lo = float(pd.Series(edges).quantile(CROSS_CLIP[0] / 100.0))
        hi = float(pd.Series(edges).quantile(CROSS_CLIP[1] / 100.0))
        for i, e in enumerate(edges):
            if e < lo:
                drawn[i] = lo
                clipped[i] = True
            elif e > hi:
                drawn[i] = hi
                clipped[i] = True

    colors = [P["good"] if e > 0 else P["bad"] for e in edges]
    text = [f"{e:+.1f}{unit}" + (" *" if c else "")
            for e, c in zip(edges, clipped)]
    fig.add_trace(go.Bar(
        x=drawn, y=labels, orientation="h", marker_color=colors,
        text=text, textposition="outside", textfont=dict(size=11),
        cliponaxis=False, customdata=edges,
        hovertemplate="%{y}<br>excess %{customdata:+.2f}" + unit
                      + "<extra></extra>"))
    fig.add_vline(x=0, line_dash="dot", line_color=P["muted"])

    if any(clipped):
        fig.add_annotation(
            text="* = bar clipped for scale; true value in label/hover",
            showarrow=False, xref="paper", yref="paper",
            x=1.0, y=1.02, xanchor="right",
            font=dict(size=9, color=P["muted"]))
    return fig


def es_cross_table(xs, unit="%"):
    if xs is None or xs.empty:
        return html.Div("No events / no data.",
                        style={"padding": "14px", "color": P["muted"]})

    fac = 100 if unit == "%" else 1
    heads = ["Country", "Events", f"Mean {unit}", f"Base {unit}",
             f"Excess {unit}", "Hit %"]
    thead = html.Thead(html.Tr([html.Th(h) for h in heads]))

    body = []
    for iso, r in xs.iterrows():
        edge = r["edge"] * fac
        cls = "emd-pos" if edge > 0 else ("emd-neg" if edge < 0 else "")
        body.append(html.Tr([
            html.Td(f"{NAME_BY_ISO.get(iso, iso)} ({iso})"),
            html.Td(f"{int(r['n'])}"), html.Td(f"{r['mean']*fac:+.2f}"),
            html.Td(f"{r['base_mean']*fac:+.2f}"),
            html.Td(f"{edge:+.2f}", className=cls),
            html.Td(f"{r['hit_rate']*100:.0f}"),
        ]))

    return html.Div([_col_legend(cross=True),
                     html.Table([thead, html.Tbody(body)],
                                className="emd-table")])


# ===================================================================
# MRC RENDERING
# ===================================================================
REGIME_COLORS = getattr(config, "REGIME_COLORS",
                        {"Risk-Off": P["bad"], "Risk-On": P["good"],
                         "Goldilocks": P["gold"], "Neutral": P["grey"]})

_mrc_cache: dict = {}


def mrc_compute(min_days=None, force=False):
    """Daily regime labels + the underlying z-scores. Cached per min_days."""
    if mrc is None:
        return None, None
    key = int(min_days) if min_days else int(getattr(mrc, "DEFAULT_MIN_DAYS", 5))
    if key in _mrc_cache and not force:
        return _mrc_cache[key]
    try:
        raw = mrc.assemble_gauges(get_global=core.get_global,
                                  get_market=core.get_market,
                                  get_commodity=core.get_commodity)
        if raw is None or raw.empty:
            return None, None
        z = pd.DataFrame({c: mrc._zseries(raw[c]) for c in raw.columns})
        z = z.reindex(raw.index)
        reg = mrc.classify(z, min_days=key)
        _mrc_cache[key] = (reg, z)
        return reg, z
    except Exception:
        return None, None


def mrc_ribbon_fig(reg):
    fig = _fig(height=210, ytitle="")
    fig.update_layout(barmode="stack",
                      margin=dict(l=MARGIN_L, r=22, t=42, b=46))
    _legend(fig, True)
    fig.update_yaxes(showticklabels=False, showgrid=False, range=[0, 1])

    if reg is None or reg.empty:
        return _empty(fig, "no regime data - run ingest.py, then "
                           "python mrc.py --live")

    for name in ("Risk-Off", "Neutral", "Risk-On", "Goldilocks"):
        mask = (reg == name)
        if not mask.any():
            continue
        xs = list(reg.index[mask])
        fig.add_trace(go.Bar(
            x=xs, y=[1] * len(xs), name=name,
            marker_color=REGIME_COLORS.get(name, P["grey"]),
            marker_line_width=0, width=86400000,
            hovertemplate="%{x|%d %b %Y}<br>" + name + "<extra></extra>"))
    return fig


def mrc_gauge_fig(z, rng="Max"):
    fig = _fig(height=340, ytitle="sigma (z-score)", yunit="sigma")
    _legend(fig, True)
    if z is None or z.empty:
        return _empty(fig, "no gauge data")

    palette = [P["bad"], P["brown"], P["navy1"], P["good"], P["gold"],
               P["navy3"], P["muted"], P["navy2"]]
    live = []
    for i, g in enumerate(z.columns):
        s = _downsample(z[g].dropna())
        if s.empty:
            continue
        live.append(s)
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, mode="lines", name=g,
            line=dict(width=1.6, color=palette[i % len(palette)]),
            hovertemplate=f"{g} %{{y:.2f}}<extra></extra>"))

    fig.add_hline(y=0, line_dash="dot", line_color=P["muted"])
    hi = float(getattr(mrc, "HI", 0.75)) if mrc else 0.75
    for lvl in (hi, -hi):
        fig.add_hline(y=lvl, line_dash="dot", line_color="#D5DAE3")
    _apply_range(fig, rng, live)
    return fig


def mrc_summary(reg):
    if reg is None or reg.empty:
        return html.Div("No regime data.",
                        style={"padding": "14px", "color": P["muted"]})

    latest = str(reg.iloc[-1])
    asof = str(pd.to_datetime(reg.index[-1]).date())
    summ = mrc.regime_summary(reg) if mrc is not None else pd.DataFrame()

    tiles = [html.Div([
        html.Div("CURRENT REGIME", className="emd-stat-label"),
        html.Div(latest, className="emd-stat-value",
                 style={"color": REGIME_COLORS.get(latest, P["navy1"])}),
        html.Div(f"as of {asof}", className="emd-stat-date"),
    ], className="emd-stat")]

    for name, row in summ.iterrows():
        tiles.append(html.Div([
            html.Div(str(name), className="emd-stat-label"),
            html.Div(f"{int(row['days']):,}d", className="emd-stat-value"),
            html.Div(f"{row['share']*100:.0f}% of history",
                     className="emd-stat-date"),
        ], className="emd-stat"))
    return html.Div(tiles, className="emd-stat-row")


def mrc_why(z, reg):
    """Per-gauge vote breakdown for the latest day."""
    if mrc is None or z is None or z.empty or reg is None or reg.empty:
        return html.Div()
    try:
        last = z.index[-1]
        contrib = mrc.contributions(z.loc[last].to_dict())
    except Exception:
        return html.Div()
    if contrib is None or contrib.empty:
        return html.Div()

    thead = html.Thead(html.Tr(
        [html.Th(h) for h in
         ["Gauge", "z-score", "Votes for", "What it reads"]]))

    body = []
    for g, r in contrib.iterrows():
        vote = str(r["votes"])
        cls = ("emd-why-off" if vote == "Risk-Off"
               else ("emd-why-on" if vote == "Risk-On" else ""))
        body.append(html.Tr([
            html.Td(str(g)), html.Td(f"{float(r['z']):+.2f}"),
            html.Td(vote, className="emd-why-vote " + cls),
            html.Td(str(r["meaning"]), style={"textAlign": "left"}),
        ]))

    return html.Div([
        html.Div(f"Why is {str(pd.to_datetime(last).date())} = {reg.iloc[-1]}?",
                 className="emd-events-title"),
        html.Table([thead, html.Tbody(body)], className="emd-table"),
        html.Div("A gauge only votes when its z-score clears the threshold. "
                 "Gauges missing from the warehouse do not vote at all - they "
                 "are never treated as zero.", className="emd-events-note"),
    ], className="emd-events")


def mrc_explain():
    def item(t, b):
        return html.Div([html.B(t + " - "), b], className="emd-explain-item")

    return html.Details([
        html.Summary("How the regime is decided (click)"),
        html.Div([
            html.Div("Each daily gauge is turned into a z-score (how unusual is "
                     "today vs the last ~1 year). Each regime is a scorecard of "
                     "simple threshold conditions; the highest score wins, and a "
                     "weak score falls back to Neutral. Every rule is readable "
                     "in mrc.py - no ML, no hidden state.",
                     className="emd-explain-lead"),
            item("Risk-Off", "VIX high, MOVE high, DXY high, copper weak, Brent "
                             "weak, credit spreads wide."),
            item("Risk-On", "VIX low, MOVE low, DXY soft, copper strong, Brent "
                            "firm, credit spreads tight."),
            item("Goldilocks", "quiet vol AND stable dollar AND a firm growth "
                               "read."),
            item("Neutral", "nothing scored strongly enough - most days."),
            item("VIX vs MOVE", "equity vol (VIX) reads across to INVESTMENT "
                                "GRADE spreads; rates vol (MOVE) reads across "
                                "to HIGH YIELD. High MOVE is bad in general: if "
                                "the path of interest rates is uncertain, "
                                "discount rates are unstable and valuation "
                                "models stop working."),
            item("Oil and copper", "the two big real-economy reads. Weak oil or "
                                   "weak copper usually means the economy is "
                                   "doing badly - the exception is a supply "
                                   "disruption, which this classifier cannot "
                                   "see."),
            item("Hysteresis", "a new regime must hold for N consecutive days "
                               "before it is confirmed. Without it the label "
                               "flickered almost daily, which is not how "
                               "regimes actually behave. Set N below."),
            html.Div("Why it matters: the regime is itself a signal. Feed a "
                     "regime FLIP into the Event Study tab to ask 'when we flip "
                     "into Risk-Off, what did BRL do next?'",
                     className="emd-explain-foot"),
        ], className="emd-explain-body"),
    ], className="emd-explain", open=False)


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

# Tabs are gated on config.FEATURE_FLAGS, so callbacks may reference components
# that are not in the layout. This tells Dash that is intentional.
app.config.suppress_callback_exceptions = True
server = app.server
database_tab.register(app)
runner.register(app)

database_tab.register(app)


def _filter(label, comp):
    return html.Div([html.Span(label, className="emd-ctrl-label"), comp],
                    className="emd-ctrl-group")


def _plain_card(title, graph_id, source_id, sub=None, range_id=None,
                range_value="Max"):
    """Chart island whose title is STATIC text (MRC / Event Study), as opposed
    to chart_card() whose title is filled in by a callback."""
    head_left = [html.Div(title, className="emd-chart-title")]
    if sub:
        head_left.append(html.Div(sub, className="emd-chart-sub"))
    head = [html.Div(head_left, className="emd-chart-titlewrap")]
    kids = []
    if range_id:
        kids.append(html.Div(_range_pills(range_id, range_value),
                             className="emd-range-row"))
    kids.append(html.Div(head, className="emd-chart-head"))
    kids.append(_graph(graph_id))
    kids.append(html.Div(id=source_id, className="emd-chart-source"))
    return html.Div(kids, className="emd-card")


def _callback_title_card(title_id, graph_id, source_id):
    """Chart island whose title div is filled by a callback."""
    return html.Div([
        html.Div([html.Div([html.Div(id=title_id,
                                     className="emd-chart-title")],
                           className="emd-chart-titlewrap")],
                 className="emd-chart-head"),
        _graph(graph_id),
        html.Div(id=source_id, className="emd-chart-source"),
    ], className="emd-card")


def _tab_news():
    return dcc.Tab(
        label="News Feed", value="news", className="emd-tab",
        selected_className="emd-tab--selected", children=[
            html.Div([
                _filter("Columns by", dcc.Dropdown(
                    id="columns-by", value=sv("columns_by", "Country"),
                    clearable=False, style={"width": "150px"},
                    options=["Country", "Topic", "Source Tier", "Desk"])),
                _filter("Since", dcc.Dropdown(
                    id="f-days", value=sv("f_days", 7), clearable=False,
                    style={"width": "130px"},
                    options=[{"label": lbl, "value": v}
                             for lbl, v in DAY_OPTS])),
                _filter("Desk", dcc.Dropdown(
                    id="f-desk", multi=True, placeholder="All desks",
                    value=sv("f_desk", []), style={"minWidth": "190px"},
                    options=[{"label": config.DESK_LABELS[d], "value": d}
                             for d in config.DESK_LABELS])),
                _filter("Source Tier", dcc.Dropdown(
                    id="f-tier", multi=True, placeholder="All tiers",
                    value=sv("f_tier", []), style={"minWidth": "150px"},
                    options=[{"label": "A - Official", "value": "A"},
                             {"label": "B - Research", "value": "B"},
                             {"label": "C - Firehose", "value": "C"}])),
                _filter("Topic", dcc.Dropdown(
                    id="f-topic", multi=True, placeholder="All topics",
                    value=sv("f_topic", []), style={"minWidth": "190px"},
                    options=[{"label": v, "value": v}
                             for k, v in TOPIC_LABELS.items()
                             if k != "general"])),
                _filter("Search", dcc.Input(
                    id="f-search", type="text", debounce=True,
                    value=sv("f_search", ""),
                    placeholder="headline / source / tag...",
                    className="emd-input emd-search",
                    style={"width": "210px"})),
                html.Button("Refresh news", id="refresh-news", n_clicks=0,
                            className="emd-btn"),
                runner.buttons_bar(["update-news"]),
            ], className="emd-controls"),
            dcc.Loading(html.Div(id="news-board"), type="default",
                        color=P["navy2"]),
        ])


def _tab_country():
    return dcc.Tab(
        label="Country Indicators", value="country", className="emd-tab",
        selected_className="emd-tab--selected", children=[
            html.Div([
                _filter("Country", dcc.Dropdown(
                    id="country", clearable=False, style={"width": "215px"},
                    value=sv("country", COUNTRY_OPTS[0]["value"]),
                    options=COUNTRY_OPTS)),
                _filter(f"Compare (+{MAX_COMPARE-1})", dcc.Dropdown(
                    id="cmp-countries", multi=True, options=COUNTRY_OPTS,
                    value=sv("cmp_countries", []),
                    style={"minWidth": "250px"},
                    placeholder=f"overlay up to {MAX_COMPARE-1} more...")),
                _filter("Indicator", dcc.Dropdown(
                    id="indicator", clearable=False, style={"width": "210px"},
                    value=sv("indicator", INDICATOR_OPTS[0]["value"]),
                    options=INDICATOR_OPTS)),
                _filter("Transform", dcc.Dropdown(
                    id="transform", clearable=False, style={"width": "170px"},
                    value=sv("transform", "Level"),
                    options=[{"label": t, "value": t} for t in TRANSFORMS])),
                _filter("", dcc.Checklist(
                    id="normalise",
                    options=[{"label": " Normalise (common start = 100)",
                              "value": "on"}],
                    value=sv("normalise", []), className="emd-check")),
                _filter("", dcc.Checklist(
                    id="show-grid",
                    options=[{"label": " Show all-indicator grid",
                              "value": "on"}],
                    value=sv("show_grid", []), className="emd-check")),
                _filter("", dcc.Checklist(
                    id="grid-compare",
                    options=[{"label": " Compare countries in grid",
                              "value": "on"}],
                    value=sv("grid_compare", []), className="emd-check")),
            ], className="emd-controls"),

            html.Div(id="stat-tiles"),

            dcc.Loading(html.Div([
                chart_card("macro-graph", title_id="macro-title",
                           sub_id="macro-sub", source_id="macro-source",
                           prov_id="macro-prov", range_id="ctry-range",
                           range_value=sv("ctry_range", "Max")),
                chart_card("fx-graph", title_id="fx-title", sub_id="fx-sub",
                           source_id="fx-source", prov_id="fx-prov"),
            ], className="emd-grid-2"), type="default", color=P["navy2"]),

            dcc.Loading(html.Div(id="indicator-grid"), type="default",
                        color=P["navy2"]),
        ])


def _tab_eventstudy():
    return dcc.Tab(
        label="Event Study", value="eventstudy", className="emd-tab",
        selected_className="emd-tab--selected", children=[
            html.Div([
                html.Div([
                    html.Span("Study mode", className="emd-es-modelabel"),
                    dcc.RadioItems(
                        id="es-mode", value=sv("es_mode", "one"),
                        options=[{"label": " One country", "value": "one"},
                                 {"label": " Compare all countries",
                                  "value": "cross"}],
                        className="emd-es-mode", inline=True),
                ], className="emd-es-moderow"),
                es_explain_panel(),
            ], className="emd-es-modebar"),

            html.Div([
                html.Div([
                    _word("When"),
                    _inline(dcc.Dropdown(
                        id="es-sig-country", clearable=False,
                        value=sv("es_sig_country", "USA"),
                        options=COUNTRY_OPTS, style={"width": "180px"})),
                    _word("'s"),
                    _inline(dcc.Dropdown(
                        id="es-sig-ind", clearable=False,
                        value=sv("es_sig_ind", INDICATOR_OPTS[0]["value"]),
                        options=SIGNAL_IND_OPTS, style={"width": "225px"})),
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
                        options=[{"label": lbl, "value": key}
                                 for lbl, key in ES_RULES],
                        style={"width": "160px"})),
                    _inline(dcc.Input(
                        id="es-threshold", type="number",
                        value=sv("es_threshold", 0), debounce=True,
                        className="emd-input", style={"width": "84px"})),
                    html.Span(id="es-unit", className="emd-s-unit"),
                ], className="emd-sentence"),

                html.Div([
                    _word("-> show what"),
                    _inline(dcc.Dropdown(
                        id="es-target", clearable=False,
                        value=sv("es_target", "ctry:FX"),
                        options=TARGET_OPTS, style={"width": "260px"})),
                    _word("did over the next 1 / 5 / 20 / 60 trading days."),
                ], id="es-row-one", className="emd-sentence"),

                html.Div([
                    _word("-> rank every country's"),
                    _inline(dcc.Dropdown(
                        id="es-xtarget", clearable=False,
                        value=sv("es_xtarget", "FX"),
                        options=[{"label": "FX", "value": "FX"},
                                 {"label": "Policy rate",
                                  "value": "POLICY_RATE"}],
                        style={"width": "150px"})),
                    _word("response at"),
                    _inline(dcc.Input(
                        id="es-horizon", type="number", min=1,
                        value=sv("es_horizon", 20), debounce=True,
                        className="emd-input", style={"width": "76px"})),
                    _word("steps"),
                    html.Span(id="es-horizon-max", className="emd-s-hint"),
                    _word("-  sort by"),
                    _inline(dcc.Dropdown(
                        id="es-xsort", clearable=False,
                        value=sv("es_xsort", "edge_desc"),
                        options=[{"label": lbl, "value": v}
                                 for lbl, v in ES_SORTS],
                        style={"width": "180px"})),
                ], id="es-row-cross", className="emd-sentence"),

                html.Div(id="es-helper-wrap"),
            ], className="emd-es-builder"),

            html.Div(id="es-headline-wrap"),
            html.Div(id="es-walkthrough-wrap", style={"margin": "6px 16px"}),

            dcc.Loading(
                _callback_title_card("es-graph-title", "es-graph",
                                     "es-graph-source"),
                type="default", color=P["navy2"]),
            dcc.Loading(
                _callback_title_card("es-hist-title", "es-hist",
                                     "es-hist-source"),
                type="default", color=P["navy2"]),

            html.Div(id="es-events-wrap"),
            html.Details([
                html.Summary("Show full stats"),
                html.Div(id="es-table-wrap", className="emd-card"),
                html.Div([
                    html.Button("Export events (CSV)", id="es-export",
                                n_clicks=0, className="emd-btn emd-btn--ghost"),
                    dcc.Download(id="es-download"),
                ], className="emd-es-export"),
            ], className="emd-es-details", open=True),
        ])


def _tab_mrc():
    return dcc.Tab(
        label="Regime (MRC)", value="mrc", className="emd-tab",
        selected_className="emd-tab--selected", children=[
            html.Div([
                html.Div([
                    html.Span("Macro Regime Classifier",
                              className="emd-es-modelabel"),
                    html.Span(id="mrc-gaugelist", className="emd-s-hint"),
                    _filter("Confirm after", dcc.Input(
                        id="mrc-days", type="number", min=1, max=120,
                        debounce=True,
                        value=sv("mrc_days",
                                 int(getattr(config, "MRC_MIN_DAYS", 5))),
                        className="emd-input", style={"width": "76px"})),
                    html.Span("consecutive days (anti-flicker)",
                              className="emd-s-hint"),
                ], className="emd-es-moderow"),
                mrc_explain(),
            ], className="emd-es-modebar"),

            html.Div(id="mrc-summary"),

            dcc.Loading(
                _plain_card("Macro regime through time", "mrc-ribbon",
                            "mrc-ribbon-source"),
                type="default", color=P["navy2"]),
            dcc.Loading(
                _plain_card("Gauge z-scores", "mrc-gauges",
                            "mrc-gauges-source",
                            sub="how unusual is today vs the last ~1 year",
                            range_id="mrc-range",
                            range_value=sv("mrc_range", "Max")),
                type="default", color=P["navy2"]),

            html.Div(id="mrc-why-wrap"),
        ])


def serve_layout():
    global _STATE
    _STATE = load_state()

    tabs = []
    if FLAGS.get("module_database", True):
        tabs.append(database_tab.tab())
    if FLAGS.get("module_news", True):
        tabs.append(_tab_news())
    if FLAGS.get("module_country", True):
        tabs.append(_tab_country())
    if FLAGS.get("module_event_study", True):
        tabs.append(_tab_eventstudy())
    if FLAGS.get("module_regime_mrc", True):
        tabs.append(_tab_mrc())

    if not tabs:
        tabs = [dcc.Tab(label="No modules enabled", value="none",
                        className="emd-tab", children=[
            html.Div("Every module_* flag in config.FEATURE_FLAGS is False.",
                     style={"padding": "40px", "color": P["muted"]})])]

    default_tab = sv("tab", tabs[0].value)
    if default_tab not in [t.value for t in tabs]:
        default_tab = tabs[0].value

    return html.Div([
        dcc.Store(id="_persist_sink"),
        runner.status_store(),
        html.Div([
            html.Div("EMDASH", className="emd-logo"),
            html.Div(className="emd-title-sep"),
            html.Div("EM Macro Research OS", className="emd-tagline"),
            html.Div(className="emd-spacer"),
            html.Div([html.Span(className="dot"), "SMU EMERGING MARKETS"],
                     className="emd-badge"),
        ], className="emd-header"),
        dcc.Tabs(id="tabs", value=default_tab, parent_className="emd-tabs",
                 className="emd-tabs", children=tabs),
        html.Div("EMDASH - local build - reads emdash.sqlite - "
                 "state -> emdash_state.json", className="emd-footer"),
    ])


app.layout = serve_layout


# ===================================================================
# CALLBACKS
# ===================================================================
@app.callback(Output("news-board", "children"),
              Input("columns-by", "value"), Input("f-days", "value"),
              Input("f-desk", "value"), Input("f-tier", "value"),
              Input("f-topic", "value"), Input("f-search", "value"),
              Input("refresh-news", "n_clicks"))
def _news(columns_by, days, desks, tiers, topics, search, n_clicks):
    if n_clicks and n_clicks > (_news.__dict__.get("_last", 0)):
        _news.__dict__["_last"] = n_clicks
        load_news(force=True)
    return news_board(columns_by, desks, tiers, topics, days, search)

@app.callback(
    Output({"type": "news-more-wrap", "col": MATCH}, "children"),
    Input({"type": "news-more-btn", "col": MATCH}, "n_clicks"),
    State({"type": "news-more-store", "col": MATCH}, "data"),
    prevent_initial_call=True)
def _news_more(n_clicks, data):
    if not n_clicks or not data:
        return None
    return [_news_card(r) for r in data]

@app.callback(Output("macro-graph", "figure"), Output("fx-graph", "figure"),
              Output("stat-tiles", "children"),
              Output("macro-title", "children"),
              Output("macro-sub", "children"),
              Output("macro-source", "children"),
              Output("macro-prov", "children"),
              Output("fx-title", "children"), Output("fx-sub", "children"),
              Output("fx-source", "children"), Output("fx-prov", "children"),
              Input("country", "value"), Input("cmp-countries", "value"),
              Input("indicator", "value"), Input("transform", "value"),
              Input("normalise", "value"), Input("ctry-range", "value"))
def _country(iso3, cmp_countries, indicator, transform, normalise, rng):
    isos = _as_iso_list([iso3] + list(cmp_countries or []))
    norm = bool(normalise)
    names = ", ".join(NAME_BY_ISO.get(i, i) for i in isos)
    rebased = "  -  rebased to 100 at the common start date" if norm else ""
    sub = f"{transform}{rebased}"
    fxsub = f"{transform}{rebased}"
    _, fxnote = fx_frame(isos[0]) if isos else (None, "LCY per USD")
    return (macro_fig(isos, indicator, transform, norm, rng),
            fx_fig(isos, transform, norm, rng),
            stat_tiles(iso3),
            f"{indicator} - {names}", sub,
            source_line(source_for_indicator(indicator)),
            _prov_chip(transform, norm),
            f"FX ({fxnote}) - {names}", fxsub,
            source_line(SOURCE_YF),
            _prov_chip(transform, norm))


@app.callback(Output("indicator-grid", "children"),
              Input("show-grid", "value"), Input("country", "value"),
              Input("cmp-countries", "value"), Input("transform", "value"),
              Input("normalise", "value"), Input("grid-compare", "value"))
def _grid(show, iso3, cmp_countries, transform, normalise, compare):
    if not show:
        return html.Div("Tick 'Show all-indicator grid' to render every "
                        "indicator at once (applies the Transform above).",
                        className="emd-section-title",
                        style={"color": P["muted"], "fontWeight": 500})
    isos = _as_iso_list([iso3] + list(cmp_countries or []))
    cmp_on = bool(compare)
    label = (", ".join(NAME_BY_ISO.get(i, i) for i in isos) if cmp_on
             else NAME_BY_ISO.get(iso3, iso3))
    return html.Div([
        html.Div(f"All indicators - {transform} - {label}",
                 className="emd-section-title"),
        indicator_grid(isos, transform, bool(normalise), cmp_on),
    ])


@app.callback(Output("es-row-one", "style"), Output("es-row-cross", "style"),
              Input("es-mode", "value"))
def _es_rows(mode):
    show, hide = {}, {"display": "none"}
    return (hide, show) if mode == "cross" else (show, hide)


def _blank(msg="-", height=320):
    return _empty(_fig(height=height), msg)


@app.callback(Output("es-unit", "children"),
              Output("es-helper-wrap", "children"),
              Output("es-headline-wrap", "children"),
              Output("es-walkthrough-wrap", "children"),
              Output("es-graph", "figure"),
              Output("es-graph-title", "children"),
              Output("es-graph-source", "children"),
              Output("es-hist", "figure"),
              Output("es-hist-title", "children"),
              Output("es-hist-source", "children"),
              Output("es-events-wrap", "children"),
              Output("es-table-wrap", "children"),
              Output("es-horizon-max", "children"),
              Input("es-mode", "value"),
              Input("es-sig-country", "value"), Input("es-sig-ind", "value"),
              Input("es-transform", "value"), Input("es-rule", "value"),
              Input("es-threshold", "value"), Input("es-target", "value"),
              Input("es-xtarget", "value"), Input("es-horizon", "value"),
              Input("es-xsort", "value"))
def _eventstudy(mode, sig_iso, sig_ind, transform, rule, threshold,
                target_value, xtarget, horizon, xsort):
    unit = unit_for(sig_ind, transform)
    sig_name = _signal_name(sig_iso, sig_ind)
    signal = _signal_series(sig_iso, sig_ind, transform)
    thr = float(threshold) if threshold is not None else 0.0
    helper = es_helper(signal, unit, sig_name, transform, rule, thr)
    ssrc = _signal_source(sig_ind)

    if es is None:
        f = _blank("event_study.py not found")
        return (unit, helper, "", "", f, "Event Study", "", _blank(), "", "",
                "", html.Div("event_study.py missing."), "")

    if signal.empty:
        f = _blank("No signal data - run ingest.py")
        return (unit, helper,
                html.Div("No signal data.", className="emd-es-headline"), "",
                f, "Event Study", "", _blank("no signal data"), "", "",
                "", "", "")

    # ---- cross-section mode ------------------------------------------------
    if mode == "cross":
        targets = _cross_targets(xtarget)
        maxh = min((len(s) for s in targets.values()), default=250)
        maxh = max(1, maxh - 1)
        h = int(horizon) if horizon else 20
        h = max(1, min(h, maxh))

        is_rate = (xtarget == "POLICY_RATE")
        kind = "diff" if is_rate else "pct"
        xunit = "pp" if is_rate else "%"

        xs = es.cross_sectional(signal, targets, rule=rule, threshold=thr,
                                window=20, horizon=h, kind=kind)
        xs_sorted = _sort_cross(xs, xsort)
        xlabel = "policy rate" if is_rate else "FX"
        step = "monthly steps" if is_rate else "trading days"
        n_ev = int(es.make_events(signal, rule=rule, threshold=thr).sum())

        head = html.Div([
            html.Div(f"Cross-section: {len(xs)} countries ranked by {h}-{step} "
                     f"{xlabel} excess vs baseline after the signal fired "
                     f"({n_ev} events).", className="emd-es-head-main"),
            html.Div("Green = that country's FX/rate moved MORE than its own "
                     "baseline when the signal fired; red = less. Longer bar = "
                     "more exposed.", className="emd-es-head-sub"),
        ], className="emd-es-headline")

        tsrc = SOURCE_YF if not is_rate else SOURCE_DBN
        return (unit, helper, head, "",
                es_cross_fig(xs, h, xlabel, xunit),
                f"Excess vs baseline by country - {xlabel} - "
                f"{h}{step[0]} after event",
                source_line([ssrc, tsrc]),
                _blank("(histogram shown in 'One country' mode)"),
                "Outcome spread", "",
                "", es_cross_table(xs_sorted, xunit),
                f"(max {maxh} - {step})")

    # ---- single-country mode -----------------------------------------------
    target, kind, tgt_label, tunit, tsrc = resolve_target(target_value, sig_iso)
    if target.empty:
        f = _blank(f"No data for target: {tgt_label}")
        head = html.Div(f"No data for target: {tgt_label} "
                        "(pegged currency - try a Global target).",
                        className="emd-es-headline")
        return (unit, helper, head, "", f, "Event Study", "",
                _blank("no target data"), "", "", "", "", "")

    res = es.event_study(target, signal, rule=rule, threshold=thr,
                         horizons=ES_HORIZONS, kind=kind)
    events = es.make_events(signal, rule=rule, threshold=thr)

    pvals = {}
    for hh in ES_HORIZONS:
        try:
            pvals[int(hh)] = es.empirical_pvalue(
                target, events, horizon=int(hh), kind=kind,
                n_draws=1200)["p_one_sided"]
        except Exception:
            pvals[int(hh)] = float("nan")

    try:
        p20 = es.empirical_pvalue(target, events, horizon=20, kind=kind,
                                  n_draws=1200)
    except Exception:
        p20 = None

    hist_h = 20 if 20 in ES_HORIZONS else max(ES_HORIZONS)
    try:
        ev_out, base_out = es.outcome_distribution(target, events,
                                                   horizon=hist_h, kind=kind)
        hist = es_hist_fig(res, ev_out, base_out, tunit, hist_h)
        n_ev = len(ev_out)
    except Exception:
        hist = _blank("histogram unavailable")
        n_ev = 0

    hist_title = (f"Outcome spread at {hist_h}d - events vs baseline"
                  if n_ev > HIST_DOT_LIMIT else
                  f"Every event at {hist_h}d, against the normal spread")

    return (unit, helper, es_headline(res, tgt_label, tunit, p20),
            es_walkthrough(res, tgt_label, sig_name, tunit, 20),
            es_path_fig(res, tunit),
            f"After event - {tgt_label} - typical path + dispersion",
            source_line([ssrc, tsrc]),
            hist, hist_title, source_line(tsrc),
            es_events_table(res, tunit),
            es_table(res, tunit, pvals), "")


@app.callback(Output("es-download", "data"),
              Input("es-export", "n_clicks"),
              State("es-sig-country", "value"), State("es-sig-ind", "value"),
              State("es-transform", "value"), State("es-rule", "value"),
              State("es-threshold", "value"), State("es-target", "value"),
              prevent_initial_call=True)
def _es_export(n_clicks, sig_iso, sig_ind, transform, rule, threshold,
               target_value):
    if not n_clicks or es is None:
        return None
    signal = _signal_series(sig_iso, sig_ind, transform)
    thr = float(threshold) if threshold is not None else 0.0
    if signal.empty:
        return None
    target, kind, tgt_label, tunit, _src = resolve_target(target_value, sig_iso)
    if target.empty:
        return None
    res = es.event_study(target, signal, rule=rule, threshold=thr,
                         horizons=ES_HORIZONS, kind=kind)
    df = res.event_list()
    if df is None or df.empty:
        return None
    fname = (f"emdash_events_{sig_iso}_"
             f"{str(sig_ind).replace(':','-')}_{rule}.csv")
    return dcc.send_data_frame(df.to_csv, fname, index=False)


@app.callback(Output("mrc-summary", "children"),
              Output("mrc-ribbon", "figure"),
              Output("mrc-gauges", "figure"),
              Output("mrc-why-wrap", "children"),
              Output("mrc-gaugelist", "children"),
              Output("mrc-ribbon-source", "children"),
              Output("mrc-gauges-source", "children"),
              Input("tabs", "value"), Input("mrc-days", "value"),
              Input("mrc-range", "value"))
def _mrc(tab, days, rng):
    if tab != "mrc":
        return "", _blank("", 210), _blank("", 340), "", "", "", ""

    if mrc is None:
        f = _empty(_fig(height=210), "mrc.py not found in the EMDASH folder")
        return (html.Div("mrc.py missing.",
                         style={"padding": "18px", "color": P["bad"]}),
                f, _blank("", 340), "", "", "", "")

    reg, z = mrc_compute(min_days=days)
    gauges = list(z.columns) if z is not None and not z.empty else []
    missing = [g for g in getattr(mrc, "ALL_GAUGES", {}) if g not in gauges]

    note = "rules-based - " + (" - ".join(gauges) if gauges else "no gauges")
    if missing:
        note += f"   (not yet in warehouse: {', '.join(missing)})"

    src = source_line([SOURCE_YF] + ([SOURCE_FRED] if any(
        g in getattr(config, "FRED_SERIES", {}) for g in gauges) else []))

    return (mrc_summary(reg), mrc_ribbon_fig(reg), mrc_gauge_fig(z, rng),
            mrc_why(z, reg), note, src, src)


@app.callback(Output("_persist_sink", "data"),
              Input("tabs", "value"),
              Input("columns-by", "value"), Input("f-days", "value"),
              Input("f-desk", "value"), Input("f-tier", "value"),
              Input("f-topic", "value"), Input("f-search", "value"),
              Input("country", "value"), Input("cmp-countries", "value"),
              Input("indicator", "value"), Input("transform", "value"),
              Input("normalise", "value"), Input("show-grid", "value"),
              Input("grid-compare", "value"), Input("ctry-range", "value"),
              Input("es-mode", "value"),
              Input("es-sig-country", "value"), Input("es-sig-ind", "value"),
              Input("es-transform", "value"), Input("es-rule", "value"),
              Input("es-threshold", "value"), Input("es-target", "value"),
              Input("es-xtarget", "value"), Input("es-horizon", "value"),
              Input("es-xsort", "value"),
              Input("mrc-days", "value"), Input("mrc-range", "value"),
              prevent_initial_call=True)
def _persist(tab, columns_by, f_days, f_desk, f_tier, f_topic, f_search,
             country, cmp_countries, indicator, transform, normalise,
             show_grid, grid_compare, ctry_range, es_mode, es_sig_country,
             es_sig_ind, es_transform, es_rule, es_threshold, es_target,
             es_xtarget, es_horizon, es_xsort, mrc_days, mrc_range):
    save_state({
        "tab": tab, "columns_by": columns_by, "f_days": f_days,
        "f_desk": f_desk, "f_tier": f_tier, "f_topic": f_topic,
        "f_search": f_search,
        "country": country, "cmp_countries": cmp_countries,
        "indicator": indicator, "transform": transform,
        "normalise": normalise, "show_grid": show_grid,
        "grid_compare": grid_compare, "ctry_range": ctry_range,
        "es_mode": es_mode, "es_sig_country": es_sig_country,
        "es_sig_ind": es_sig_ind, "es_transform": es_transform,
        "es_rule": es_rule, "es_threshold": es_threshold,
        "es_target": es_target, "es_xtarget": es_xtarget,
        "es_horizon": es_horizon, "es_xsort": es_xsort,
        "mrc_days": mrc_days, "mrc_range": mrc_range,
    })
    return {}


if __name__ == "__main__":
    core.init_db()
    print(f"[app] EMDASH running -> http://127.0.0.1:{PORT}  (Ctrl+C to stop)")
    print(f"[app] state file -> {STATE_PATH}")
    app.run(debug=False, use_reloader=False, port=PORT)
