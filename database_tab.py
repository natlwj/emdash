"""
EMDASH :: database_tab.py   (v1)
===================================================================
THE DATABASE TAB.  A live map of everything in emdash.sqlite: which country
has which field, from when to when, from what source, and how fresh.

Modular by design (matches EMDASH's one-concern-per-file style):
    database_tab.tab()            -> the dcc.Tab object (drop into app layout)
    database_tab.register(app)    -> wires its single callback onto the app

app.py needs only three small lines (see the block comment at the bottom).

Reads ONLY through core.py:
    core.coverage()        -> per (scope,key,field): n, first, last, source
    core.ingest_log_df()   -> per source: last_run, rows
    core.table_counts()    -> rows per table
Nothing here touches the DB directly.
===================================================================
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
from dash import dcc, html, Input, Output

import config
import core

P = config.PALETTE

# Field display order so the matrix reads left-to-right sensibly.
_MACRO_ORDER = list(getattr(config, "WB_INDICATORS", {})) + \
    list(getattr(config, "DBN_SERIES", {}))
_MARKET_ORDER = ["FX", "EQUITY", "Y2", "Y5", "Y10", "Y30", "FX_FRED"]

# Freshness thresholds (days) for DAILY market/global/commodity series.
_FRESH_DAYS = 30
_STALE_DAYS = 90


# -------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------
def _days_since(date_str) -> int | None:
    try:
        d = pd.to_datetime(date_str).date()
        return (dt.date.today() - d).days
    except Exception:
        return None


def _cell(n, first, last, source, daily=False):
    """One matrix cell. Colour = has-data (+ freshness for daily series)."""
    if not n or n == 0:
        return html.Td("·", style={"color": "#C9CED8", "textAlign": "center"})
    title = f"{n:,} rows | {str(first)[:10]} -> {str(last)[:10]} | {source}"
    bg = "#EAF0F9"          # has data (macro/annual default)
    fg = P["navy1"]
    if daily:
        ds = _days_since(last)
        if ds is not None:
            if ds <= _FRESH_DAYS:
                bg, fg = "#E4F0E6", P["good"]          # fresh green
            elif ds <= _STALE_DAYS:
                bg, fg = "#FBF3E2", "#8A6D1B"          # amber
            else:
                bg, fg = "#F7E4E1", P["bad"]           # stale red
    return html.Td(f"{n:,}", title=title,
                   style={"background": bg, "color": fg, "fontSize": "11px",
                          "textAlign": "center", "whiteSpace": "nowrap"})


def _matrix(cov: pd.DataFrame, scope: str, field_order, daily=False):
    """Country x field matrix for one scope (macro or market)."""
    sub = cov[cov["scope"] == scope]
    if sub.empty:
        return html.Div("No data yet in this scope - run python ingest.py.",
                        style={"padding": "16px", "color": P["muted"]})

    # index cells by (key, field) for O(1) lookup
    idx = {(r["key"], r["field"]): r for _, r in sub.iterrows()}
    present_fields = list(dict.fromkeys(
        [f for f in field_order if f in set(sub["field"])]
        + sorted(set(sub["field"]) - set(field_order))))

    # header
    head = [html.Th("Country", style={"position": "sticky", "left": 0,
                                       "background": P["card"], "zIndex": 2})]
    head += [html.Th(f, style={"fontSize": "10.5px", "writingMode": "vertical-rl",
                               "transform": "rotate(180deg)", "padding": "4px"})
             for f in present_fields]
    thead = html.Thead(html.Tr(head))

    # rows in COUNTRIES order (keeps desk grouping)
    rows = []
    for iso3, name, desk, dmem, *_ in config.COUNTRIES:
        if not any((iso3, f) in idx for f in present_fields):
            continue        # skip countries with zero data in this scope
        tds = [html.Td(f"{iso3}  {name}",
                       title=f"{desk} | {config.DMEM_LABELS.get(dmem, dmem)}",
                       style={"position": "sticky", "left": 0,
                              "background": P["card"], "fontSize": "11px",
                              "fontWeight": 600, "whiteSpace": "nowrap"})]
        for f in present_fields:
            r = idx.get((iso3, f))
            if r is None:
                tds.append(_cell(0, None, None, None))
            else:
                tds.append(_cell(r["n"], r["first"], r["last"], r["source"],
                                 daily=daily))
        rows.append(html.Tr(tds))

    return html.Div(
        html.Table([thead, html.Tbody(rows)], className="emd-table",
                   style={"borderCollapse": "collapse"}),
        style={"overflowX": "auto", "maxWidth": "100%"})


def _simple_list(cov: pd.DataFrame, scope: str, label: str):
    """Flat table for global / commodity (no country dimension)."""
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


def _freshness(log: pd.DataFrame):
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


def _tiles(counts: dict, cov: pd.DataFrame):
    def tile(label, value):
        return html.Div([
            html.Div(label, className="emd-stat-label"),
            html.Div(value, className="emd-stat-value"),
        ], className="emd-stat")
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
# public API
# -------------------------------------------------------------------
def tab():
    """The dcc.Tab. Body is filled by the callback in register()."""
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
                    html.B("Market colours"),
                    " show freshness: ",
                    html.Span("green", style={"color": P["good"],
                                              "fontWeight": 700}),
                    " up to date (<30d), ",
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
    """Wire the single callback. Call once from app.py after app is created."""

    @app.callback(Output("db-body", "children"),
                  Input("tabs", "value"), Input("db-refresh", "n_clicks"))
    def _fill(tab_value, _n):
        if tab_value != "database":
            return html.Div()
        try:
            cov = core.coverage()
            counts = core.table_counts()
            log = core.ingest_log_df()
        except Exception as e:
            return html.Div(f"coverage read failed: {e}",
                            style={"color": P["bad"], "padding": "16px"})

        def sect(title, node):
            return html.Div([
                html.Div(title, className="emd-section-title"),
                node,
            ], style={"margin": "10px 16px 22px"})

        return html.Div([
            _tiles(counts, cov),
            sect("MACRO  ·  country x indicator  ·  number = observations "
                 "(annual ~25, monthly in the hundreds)",
                 _matrix(cov, "macro", _MACRO_ORDER, daily=False)),
            sect("MARKET  ·  country x series (FX / EQUITY / bond yields)  ·  "
                 "number = daily rows  ·  colour = freshness",
                 _matrix(cov, "market", _MARKET_ORDER, daily=True)),
            html.Div([
                html.Div([html.Div("GLOBAL GAUGES",
                                   className="emd-section-title"),
                          _simple_list(cov, "global", "series")],
                         style={"flex": 1, "minWidth": 0}),
                html.Div([html.Div("COMMODITIES",
                                   className="emd-section-title"),
                          _simple_list(cov, "commodity", "commodity")],
                         style={"flex": 1, "minWidth": 0}),
                html.Div([html.Div("INGEST FRESHNESS",
                                   className="emd-section-title"),
                          _freshness(log)],
                         style={"flex": 1, "minWidth": 0}),
            ], style={"display": "flex", "gap": "18px",
                      "margin": "10px 16px", "flexWrap": "wrap"}),
        ])


# ===================================================================
# HOW TO WIRE INTO app.py  (3 lines):
#
#   1. near the other imports:            import database_tab
#   2. right after  server = app.server:  database_tab.register(app)
#   3. in serve_layout(), as the FIRST tab appended:
#          if FLAGS.get("module_database", True):
#              tabs.append(database_tab.tab())
# ===================================================================
