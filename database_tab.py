"""
EMDASH :: database_tab.py   (v4)  -- the "SQLite Store" tab
===================================================================
Live map of emdash.sqlite: coverage matrices, a richer NEWS panel, freshness,
warm-cache + render-cache for speed, and per-section PULL buttons.

v4 CHANGES
  * NEWS PANEL richer: total, tier A/B/C, tagged % (BIG), per-DESK breakdown,
    per-source spans, and a DEAD FEEDS warning (feeds configured in RSS_FEEDS
    that returned zero rows -> likely bad URL / firewalled), so you can see at
    a glance what to fix/swap.
  * PULL BUTTONS on the tab (via runner): Pull Markets / Pull Macro /
    Pull Everything. "Pull" = fetch from the internet; "Refresh" (top) = just
    re-read the DB into this view.
  * FRIENDLY NAMES: uses config.INDICATOR_LABELS (if present) so matrix column
    headers read e.g. "GDP per capita (USD)" instead of GDP_PC_USD.

v3 (kept): warm_cache() + render cache.  v2 (kept): news panel + data cache.
===================================================================
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
from dash import dcc, html, Input, Output

import config
import core

try:
    import runner
except Exception:                       # runner optional; tab still renders
    runner = None

P = config.PALETTE
_LABELS = getattr(config, "INDICATOR_LABELS", {})

_MACRO_ORDER = list(getattr(config, "WB_INDICATORS", {})) + \
    list(getattr(config, "DBN_SERIES", {}))
_MARKET_ORDER = ["FX", "EQUITY", "Y2", "Y5", "Y10", "Y30", "FX_FRED"]
_FRESH_DAYS, _STALE_DAYS = 30, 90

_CACHE = {"cov": None, "counts": None, "log": None, "news": None,
          "rendered": None, "clicks": 0}


def _lbl(field):
    return _LABELS.get(field, field)


def _days_since(date_str):
    try:
        return (dt.date.today() - pd.to_datetime(date_str).date()).days
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
        return html.Div("No data yet in this scope - run a Pull.",
                        style={"padding": "16px", "color": P["muted"]})
    idx = {(r["key"], r["field"]): r for _, r in sub.iterrows()}
    present = list(dict.fromkeys(
        [f for f in field_order if f in set(sub["field"])]
        + sorted(set(sub["field"]) - set(field_order))))
    head = [html.Th("Country", style={"position": "sticky", "left": 0,
                                       "background": P["card"], "zIndex": 2})]
    head += [html.Th(_lbl(f), title=_lbl(f),
                     style={"fontSize": "10.5px", "writingMode": "vertical-rl",
                            "transform": "rotate(180deg)", "padding": "4px"})
             for f in present]
    thead = html.Thead(html.Tr(head))
    rows = []
    for iso3, name, desk, dmem, *_ in config.COUNTRIES:
        if not any((iso3, f) in idx for f in present):
            continue
        tds = [html.Td(f"{iso3}  {name}",
                       title=f"{desk} | {config.DMEM_LABELS.get(dmem, dmem)}",
                       style={"position": "sticky", "left": 0,
                              "background": P["card"], "fontSize": "11px",
                              "fontWeight": 600, "whiteSpace": "nowrap"})]
        for f in present:
            r = idx.get((iso3, f))
            tds.append(_cell(0, None, None, None) if r is None
                       else _cell(r["n"], r["first"], r["last"], r["source"],
                                  daily=daily))
        rows.append(html.Tr(tds))
    return html.Div(html.Table([thead, html.Tbody(rows)], className="emd-table",
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
            html.Td(_lbl(r["field"]), style={"fontWeight": 600}),
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
        return html.Div("No news yet - click Pull News.",
                        style={"color": P["muted"], "padding": "8px"})
    tier = nc.get("by_tier", {})
    span = nc.get("span", ("-", "-"))
    tagged, untagged = nc.get("tagged", 0), nc.get("untagged", 0)
    pct = nc.get("tagged_pct", 0.0)
    desk = nc.get("by_desk", {})
    dead = nc.get("dead_feeds", [])

    summary = html.Div([
        html.Span(f"{nc['total']:,} headlines", style={"fontWeight": 700}),
        html.Span(f"   {span[0]} -> {span[1]}", style={"color": P["muted"]}),
        html.Span(f"   ·  A:{tier.get('A',0):,}  B:{tier.get('B',0):,}  "
                  f"C:{tier.get('C',0):,}", style={"marginLeft": "6px"}),
        html.Span(f"   ·  tagged {pct:.0f}%  ({tagged:,}/{nc['total']:,})",
                  style={"marginLeft": "6px",
                         "color": P["good"] if pct >= 60 else P["bad"],
                         "fontWeight": 700}),
    ], style={"fontSize": "12px", "marginBottom": "8px"})

    # per-desk chips
    order = list(config.DESK_LABELS) + ["(no desk)"]
    chips = []
    for d in order:
        if d not in desk:
            continue
        lab = config.DESK_LABELS.get(d, d)
        is_none = (d == "(no desk)")
        chips.append(html.Span(f"{lab}: {desk[d]:,}",
                     style={"display": "inline-block", "margin": "2px 6px 2px 0",
                            "padding": "2px 8px", "borderRadius": "10px",
                            "fontSize": "11px",
                            "background": "#F7E4E1" if is_none else "#EEF2FA",
                            "color": P["bad"] if is_none else P["navy1"]}))
    desk_row = html.Div(["By desk:  ", *chips],
                        style={"margin": "4px 0 10px", "fontSize": "11.5px"})

    # dead feeds warning
    dead_row = html.Div()
    if dead:
        dead_row = html.Div([
            html.B("⚠ Feeds returning nothing "),
            f"(configured but 0 rows - bad URL or firewalled): ",
            html.Span(", ".join(dead), style={"color": P["bad"],
                                              "fontWeight": 600}),
        ], style={"fontSize": "11.5px", "margin": "0 0 10px",
                  "padding": "6px 10px", "background": "#FBF3E2",
                  "borderRadius": "8px"})

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
    return html.Div([summary, desk_row, dead_row,
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


def _compute():
    return (core.coverage(), core.table_counts(),
            core.ingest_log_df(), core.news_coverage())


def _render(cov, counts, log, news):
    def sect(title, node):
        return html.Div([html.Div(title, className="emd-section-title"), node],
                        style={"margin": "10px 16px 22px"})
    pull_bar = (runner.buttons_bar(["pull-markets", "pull-macro", "pull-all"])
                if runner is not None else html.Div())
    return html.Div([
        _tiles(counts, cov),
        html.Div([html.Span("Pull data (fetches from the internet, then click "
                            "Refresh above): ", className="emd-ctrl-label"),
                  pull_bar],
                 style={"margin": "6px 16px", "display": "flex",
                        "alignItems": "center", "gap": "8px",
                        "flexWrap": "wrap"}),
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
    try:
        cov, counts, log, news = _compute()
        _CACHE.update({"cov": cov, "counts": counts, "log": log, "news": news,
                       "rendered": _render(cov, counts, log, news),
                       "clicks": 0})
    except Exception:
        pass


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
                    html.B("Each number = rows that series holds. "),
                    "Hover any cell for its date span + source. ",
                    html.B("Market colours"), " = freshness: ",
                    html.Span("green", style={"color": P["good"],
                                              "fontWeight": 700}), " <30d, ",
                    html.Span("amber", style={"color": "#8A6D1B",
                                              "fontWeight": 700}), " <90d, ",
                    html.Span("red", style={"color": P["bad"],
                                            "fontWeight": 700}),
                    " stale.  ·  = none.",
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
