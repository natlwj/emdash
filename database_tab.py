"""
EMDASH :: database_tab.py   (v3)  -- the "SQLite Store" tab
===================================================================
A live map of everything in emdash.sqlite + a news panel.

v3 CHANGES (speed)
  * warm_cache()  -- compute the coverage snapshot ONCE, callable from a
    startup background thread in app.py so the FIRST open is instant instead
    of a 20-30s wait. The heavy GROUP BY runs while you look at other tabs.
  * RENDER CACHE -- v2 cached the DATA but still rebuilt the ~2000-cell HTML
    table on every click (~3s). v3 also caches the RENDERED output, so a
    re-open of the tab is instant. Both caches invalidate only on Refresh.

v2 (kept): news panel + data caching.

Reads ONLY through core.py:
    core.coverage() / core.news_coverage() / core.ingest_log_df() /
    core.table_counts()

Public API:
    database_tab.tab()            -> the dcc.Tab
    database_tab.register(app)    -> wires the callback
    database_tab.warm_cache()     -> pre-compute at startup (background thread)
===================================================================
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
from dash import dcc, html, Input, Output

import config
import core

P = config.PALETTE

_MACRO_ORDER = list(getattr(config, "WB_INDICATORS", {})) + \
    list(getattr(config, "DBN_SERIES", {}))
_MARKET_ORDER = ["FX", "EQUITY", "Y2", "Y5", "Y10", "Y30", "FX_FRED"]

_FRESH_DAYS = 30
_STALE_DAYS = 90

# caches. "data" = the four DataFrames/dicts; "rendered" = the finished html.Div;
# "clicks" = the Refresh count the caches were built at.
_CACHE = {"cov": None, "counts": None, "log": None, "news": None,
          "rendered": None, "clicks": 0}


# -------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------
def _days_since(date_str):
    try:
        d = pd.to_datetime(date_str).date()
        return (dt.date.today() - d).days
    except Exception:
        return None


def _cell(n, first, last, source, daily=False):
    if not n or n == 0:
        return html.Td("·", style={"color": "#C9CED8", "textAlign": "center"})
    title = f"{n:,} rows | {str(first)[:10]} -> {str(last)[:10]} | {source}"
    bg, fg = "#EAF0F9", P["navy1"]
    if daily:
        ds = _days_since(last)
        if ds is not None:
            if ds <= _FRESH_DAYS:
                bg, fg = "#E4F0E6", P["good"]
            elif ds <= _STALE_DAYS:
                bg, fg = "#FBF3E2", "#8A6D1B"
            else:
                bg, fg = "#F7E4E1", P["bad"]
    return html.Td(f"{n:,}", title=title,
                   style={"background": bg, "color": fg, "fontSize": "11px",
                          "textAlign": "center", "whiteSpace": "nowrap"})


def _matrix(cov, scope, field_order, daily=False):
    sub = cov[cov["scope"] == scope]
    if sub.empty:
        return html.Div("No data yet in this scope - run python ingest.py.",
                        style={"padding": "16px", "color": P["muted"]})
    idx = {(r["key"], r["field"]): r for _, r in sub.iterrows()}
    present_fields = list(dict.fromkeys(
        [f for f in field_order if f in set(sub["field"])]
        + sorted(set(sub["field"]) - set(field_order))))

    head = [html.Th("Country", style={"position": "sticky", "left": 0,
                                       "background": P["card"], "zIndex": 2})]
    head += [html.Th(f, style={"fontSize": "10.5px",
                               "writingMode": "vertical-rl",
                               "transform": "rotate(180deg)", "padding": "4px"})
             for f in present_fields]
    thead = html.Thead(html.Tr(head))

    rows = []
    for iso3, name, desk, dmem, *_ in config.COUNTRIES:
        if not any((iso3, f) in idx for f in present_fields):
            continue
        tds = [html.Td(f"{iso3}  {name}",
                       title=f"{desk} | {config.DMEM_LABELS.get(dmem, dmem)}",
                       style={"position": "sticky", "left": 0,
                              "background": P["card"], "fontSize": "11px",
                              "fontWeight": 600, "whiteSpace": "nowrap"})]
        for f in present_fields:
            r = idx.get((iso3, f))
            tds.append(_cell(0, None, None, None) if r is None
                       else _cell(r["n"], r["first"], r["last"], r["source"],
                                  daily=daily))
        rows.append(html.Tr(tds))

    return html.Div(
        html.Table([thead, html.Tbody(rows)], className="emd-table",
                   style={"borderCollapse": "collapse"}),
        style={"overflowX": "auto", "maxWidth": "100%"})


def _simple_list(cov, scope, label):
    sub = cov[cov["scope"] == scope].sort_values("field")
    if sub.empty:
        return html.Div()
    body = []
    for _, r in sub.iterrows():
        ds = _days_since(r["last"])
        stale = ds is not None and ds > _STALE_DAYS
        body.append(html.Tr([
            html.Td(r["field"], style={"fontWeight": 600}),
            html.Td(f"{int(r['n']):,}"),
            html.Td(f"{str(r['first'])[:10]} -> {str(r['last'])[:10]}",
                    style={"color": P["bad"] if stale else P["ink"]}),
            html.Td(str(r["source"])),
        ]))
    thead = html.Thead(html.Tr([html.Th(h) for h in
                                [label, "rows", "span", "source"]]))
    return html.Table([thead, html.Tbody(body)], className="emd-table")


def _news_panel(nc):
    if not nc or nc.get("total", 0) == 0:
        return html.Div("No news yet - run python news_ingest.py.",
                        style={"color": P["muted"], "padding": "8px"})
    tier = nc.get("by_tier", {})
    span = nc.get("span", ("-", "-"))
    tagged, untagged = nc.get("tagged", 0), nc.get("untagged", 0)
    summary = html.Div([
        html.Span(f"{nc['total']:,} headlines", style={"fontWeight": 700}),
        html.Span(f"   {span[0]} -> {span[1]}", style={"color": P["muted"]}),
        html.Span(f"   ·  A:{tier.get('A',0):,}  B:{tier.get('B',0):,}  "
                  f"C:{tier.get('C',0):,}", style={"marginLeft": "6px"}),
        html.Span(f"   ·  tagged {tagged:,} / untagged {untagged:,}",
                  style={"color": P["muted"], "marginLeft": "6px"}),
    ], style={"fontSize": "12px", "marginBottom": "8px"})
    bysrc = nc.get("by_source")
    body = []
    if bysrc is not None and not bysrc.empty:
        for _, r in bysrc.iterrows():
            body.append(html.Tr([
                html.Td(str(r["source_id"]), style={"fontWeight": 600}),
                html.Td(f"{int(r['n']):,}"),
                html.Td(f"{str(r['first'])[:10]} -> {str(r['last'])[:10]}"),
            ]))
    thead = html.Thead(html.Tr([html.Th(h) for h in
                                ["source", "headlines", "span"]]))
    return html.Div([summary,
                     html.Table([thead, html.Tbody(body)],
                                className="emd-table")])


def _freshness(log):
    if log is None or log.empty:
        return html.Div("No ingest log yet.",
                        style={"color": P["muted"], "padding": "8px"})
    body = []
    for _, r in log.iterrows():
        ds = _days_since(str(r["last_run"])[:10])
        col = (P["good"] if (ds is not None and ds <= 7)
               else (P["bad"] if (ds is not None and ds > 30) else P["ink"]))
        body.append(html.Tr([
            html.Td(r["source_id"], style={"fontWeight": 600}),
            html.Td(str(r["last_run"])[:16], style={"color": col}),
            html.Td(f"{int(r['rows']):,}" if pd.notna(r["rows"]) else "-"),
        ]))
    thead = html.Thead(html.Tr([html.Th(h) for h in
                                ["source", "last run", "rows added"]]))
    return html.Table([thead, html.Tbody(body)], className="emd-table")


def _tiles(counts, cov):
    def tile(label, value):
        return html.Div([html.Div(label, className="emd-stat-label"),
                         html.Div(value, className="emd-stat-value")],
                        className="emd-stat")
    n_countries = cov[cov["scope"].isin(["macro", "market"])]["key"].nunique()
    return html.Div([
        tile("MACRO ROWS", f"{counts.get('macro_data', 0):,}"),
        tile("MARKET ROWS", f"{counts.get('market_data', 0):,}"),
        tile("GLOBAL ROWS", f"{counts.get('global_market', 0):,}"),
        tile("COMMODITY", f"{counts.get('commodity_data', 0):,}"),
        tile("NEWS", f"{counts.get('news', 0):,}"),
        tile("PRED-MKT", f"{counts.get('predmarket_data', 0):,}"),
        tile("COUNTRIES w/ DATA", f"{n_countries}"),
    ], className="emd-stat-row")


# -------------------------------------------------------------------
# BUILD  (data -> rendered Div). Split out so warm_cache and the callback
# share exactly one code path.
# -------------------------------------------------------------------
def _compute():
    """Run the heavy reads. Returns (cov, counts, log, news)."""
    return (core.coverage(), core.table_counts(),
            core.ingest_log_df(), core.news_coverage())


def _render(cov, counts, log, news):
    def sect(title, node):
        return html.Div([html.Div(title, className="emd-section-title"), node],
                        style={"margin": "10px 16px 22px"})
    return html.Div([
        _tiles(counts, cov),
        sect("MACRO  ·  country x indicator  ·  number = observations "
             "(annual ~25, monthly in the hundreds)",
             _matrix(cov, "macro", _MACRO_ORDER, daily=False)),
        sect("MARKET  ·  country x series (FX / EQUITY / bond yields)  ·  "
             "number = daily rows  ·  colour = freshness",
             _matrix(cov, "market", _MARKET_ORDER, daily=True)),
        sect("NEWS  ·  what headlines the warehouse holds",
             _news_panel(news)),
        html.Div([
            html.Div([html.Div("GLOBAL GAUGES", className="emd-section-title"),
                      _simple_list(cov, "global", "series")],
                     style={"flex": 1, "minWidth": 0}),
            html.Div([html.Div("COMMODITIES", className="emd-section-title"),
                      _simple_list(cov, "commodity", "commodity")],
                     style={"flex": 1, "minWidth": 0}),
            html.Div([html.Div("INGEST FRESHNESS",
                               className="emd-section-title"),
                      _freshness(log)],
                     style={"flex": 1, "minWidth": 0}),
        ], style={"display": "flex", "gap": "18px",
                  "margin": "10px 16px", "flexWrap": "wrap"}),
    ])


def warm_cache():
    """Compute + render ONCE and store in the cache. Safe to call from a
    background thread at app startup (app.py). Any DB error is swallowed so a
    startup warm-up never crashes the app; the callback will just compute on
    first open instead."""
    try:
        cov, counts, log, news = _compute()
        _CACHE.update({"cov": cov, "counts": counts, "log": log, "news": news,
                       "rendered": _render(cov, counts, log, news),
                       "clicks": 0})
    except Exception:
        pass


# -------------------------------------------------------------------
# public API
# -------------------------------------------------------------------
def tab():
    return dcc.Tab(
        label="SQLite Store", value="database", className="emd-tab",
        selected_className="emd-tab--selected", children=[
            html.Div([
                html.Div([
                    html.Span("What's inside emdash.sqlite - live coverage map",
                              className="emd-es-modelabel"),
                    html.Button("Refresh", id="db-refresh", n_clicks=0,
                                className="emd-btn",
                                style={"marginLeft": "12px"}),
                ]),
                html.Div([
                    html.B("Each number = how many data points (rows) that "
                           "series holds. "),
                    "Hover any cell for its date span + source. ",
                    html.B("Market colours"), " show freshness: ",
                    html.Span("green", style={"color": P["good"],
                                              "fontWeight": 700}),
                    " <30d, ",
                    html.Span("amber", style={"color": "#8A6D1B",
                                              "fontWeight": 700}),
                    " <90d, ",
                    html.Span("red", style={"color": P["bad"],
                                            "fontWeight": 700}),
                    " stale.  ·  = no data.",
                ], className="emd-s-hint", style={"marginTop": "6px"}),
            ], className="emd-es-moderow", style={"padding": "12px 16px"}),
            dcc.Loading(html.Div(id="db-body"), type="default",
                        color=P["navy2"]),
        ])


def register(app):
    @app.callback(Output("db-body", "children"),
                  Input("tabs", "value"), Input("db-refresh", "n_clicks"))
    def _fill(tab_value, n_clicks):
        if tab_value != "database":
            return html.Div()
        clicks = n_clicks or 0
        # serve the cached RENDER unless this is first-ever or a real Refresh
        if _CACHE["rendered"] is not None and clicks <= _CACHE["clicks"]:
            return _CACHE["rendered"]
        try:
            cov, counts, log, news = _compute()
            rendered = _render(cov, counts, log, news)
        except Exception as e:
            return html.Div(f"coverage read failed: {e}",
                            style={"color": P["bad"], "padding": "16px"})
        _CACHE.update({"cov": cov, "counts": counts, "log": log, "news": news,
                       "rendered": rendered, "clicks": clicks})
        return rendered


# ===================================================================
# WIRE INTO app.py:
#   import database_tab
#   ... after server = app.server:
#       database_tab.register(app)
#       import threading
#       threading.Thread(target=database_tab.warm_cache, daemon=True).start()
#   ... in serve_layout(), FIRST tab:
#       if FLAGS.get("module_database", True):
#           tabs.append(database_tab.tab())
# ===================================================================
