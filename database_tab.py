"""
EMDASH :: database_tab.py   (v9)  -- the "Data Coverage & Updates" tab

Live map of emdash.sqlite: a slim stats strip, two pull panels (News + Data),
the news-source coverage table, and macro/market/gauge coverage matrices.

v8
  - Freshness & pulls strip REMOVED. Last-pull dates now live inside the two
    pull panels (runner.news_panel / runner.data_panel), so there is one place
    for every pull and no duplicated buttons.
  - Sections: stats -> News Pull Panel -> Data Pull Panel -> News sources ->
    Macro -> Market -> Gauges/Commodities.
  - Copy tightened (dropped the verbose coverage-map blurb).
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd
from dash import ALL, dcc, html, Input, Output, State, ctx

import config
import core

try:
    import indicator_coverage
except Exception:
    indicator_coverage = None

try:
    import runner
except Exception:
    runner = None

_STATE_PATH = config.ROOT / "emdash_state.json"


def _load_state() -> dict:
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as fh:
            d = json.load(fh)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(key, value) -> None:
    try:
        d = _load_state()
        d[key] = value
        with open(_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2)
    except Exception:
        pass


P = config.PALETTE
_LABELS = getattr(config, "INDICATOR_LABELS", {})

_MACRO_ORDER = list(getattr(config, "WB_INDICATORS", {})) + \
    list(getattr(config, "DBN_SERIES", {}))
_MARKET_ORDER = ["FX", "EQUITY", "Y2", "Y5", "Y10", "Y30", "FX_FRED"]
_FRESH_DAYS, _STALE_DAYS = 30, 90

_FEED_TIER = {f[0]: f[2] for f in getattr(config, "RSS_FEEDS", [])}

_ISLAND_BG = "#F4F6FA"
_BANNER_BG = "#EAEFF7"

_CACHE = {"cov": None, "counts": None, "log": None, "news": None,
          "rendered": None, "clicks": 0, "indicator_stamp": 0.0}


def _lbl(field):
    return _LABELS.get(field, field)


def _days_since(date_str):
    try:
        return (dt.date.today() - pd.to_datetime(date_str).date()).days
    except Exception:
        return None


def _short_span(first, last):
    try:
        a = pd.to_datetime(first)
        b = pd.to_datetime(last)
        if a.year == b.year:
            return f"{a.strftime('%b %d')} \u2192 {b.strftime('%b %d')}"
        return f"{a.strftime('%b %Y')} \u2192 {b.strftime('%b %Y')}"
    except Exception:
        return f"{str(first)[:10]} \u2192 {str(last)[:10]}"


# ===================================================================
# SECTION ISLAND
# ===================================================================
def _section(title, body, subtitle=None, right=None):
    head_left = [html.Span(title, style={
        "fontSize": "12px", "fontWeight": 700, "letterSpacing": ".6px",
        "textTransform": "uppercase", "color": P["navy1"]})]
    if subtitle:
        head_left.append(html.Span(subtitle, style={
            "fontSize": "11px", "color": P["muted"], "marginLeft": "12px",
            "fontWeight": 500, "textTransform": "none", "letterSpacing": "0"}))
    header = html.Div([
        html.Div(head_left, style={"display": "flex", "alignItems": "baseline",
                                   "flexWrap": "wrap", "minWidth": 0}),
        (html.Div(right) if right is not None else html.Span()),
    ], style={"display": "flex", "alignItems": "center",
              "justifyContent": "space-between", "gap": "12px",
              "padding": "10px 16px", "background": _BANNER_BG,
              "borderBottom": f"1px solid {P['border']}"})
    return html.Div([
        header,
        html.Div(body, style={"padding": "14px 16px"}),
    ], style={"background": _ISLAND_BG, "border": f"1px solid {P['border']}",
              "borderLeft": f"3px solid {P['gold']}", "borderRadius": "12px",
              "boxShadow": "0 1px 2px rgba(31,73,125,.05)",
              "overflow": "hidden", "margin": "14px 16px"})


# ===================================================================
# COVERAGE MATRIX
# ===================================================================
def _cell(n, first, last, source, daily=False):
    if not n or n == 0:
        return html.Td("\u00b7", style={"color": "#C9CED8", "textAlign": "center"})
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
        return html.Div("No data yet - run a pull above.",
                        style={"padding": "8px", "color": P["muted"]})
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
    return html.Div(
        html.Div(html.Table([thead, html.Tbody(rows)], className="emd-table",
                            style={"borderCollapse": "collapse"}),
                 style={"overflowX": "auto", "maxWidth": "100%"}),
        style={"background": P["card"], "border": f"1px solid {P['border']}",
               "borderRadius": "10px", "padding": "4px 8px"})


def _simple_list(cov, scope, label):
    sub = cov[cov["scope"] == scope].sort_values("field")
    if sub.empty:
        return html.Div("None yet.", style={"color": P["muted"], "padding": "8px",
                                             "fontSize": "12px"})
    body = []
    for _, r in sub.iterrows():
        ds = _days_since(r["last"])
        stale = ds is not None and ds > _STALE_DAYS
        body.append(html.Tr([
            html.Td(_lbl(r["field"]), style={"fontWeight": 600}),
            html.Td(f"{int(r['n']):,}"),
            html.Td(_short_span(r["first"], r["last"]),
                    style={"color": P["bad"] if stale else P["muted"],
                           "whiteSpace": "nowrap"}),
        ]))
    thead = html.Thead(html.Tr([html.Th(h) for h in [label, "rows", "span"]]))
    return html.Div(
        html.Table([thead, html.Tbody(body)], className="emd-table"),
        style={"background": P["card"], "border": f"1px solid {P['border']}",
               "borderRadius": "10px", "padding": "6px 12px"})


# ===================================================================
# NEWS SOURCES  (sortable table)
# ===================================================================
_SORT_OPTS = [
    {"label": "Headlines (high \u2192 low)", "value": "headlines"},
    {"label": "Tier (A \u2192 C)", "value": "tier"},
    {"label": "Source (A \u2192 Z)", "value": "source"},
    {"label": "Most recent", "value": "recent"},
    {"label": "Oldest coverage", "value": "oldest"},
]


def _sort_sources(df, how):
    df = df.copy()
    df["_tier"] = [_FEED_TIER.get(s, "C" if s == "gdelt" else "Z")
                   for s in df["source_id"]]
    if how == "tier":
        return df.sort_values(["_tier", "n"], ascending=[True, False])
    if how == "source":
        return df.sort_values("source_id")
    if how == "recent":
        return df.sort_values("last", ascending=False)
    if how == "oldest":
        return df.sort_values("first")
    return df.sort_values("n", ascending=False)


def _news_source_table(by_source, how="headlines"):
    if by_source is None or by_source.empty:
        return html.Div("No sources yet.", style={"color": P["muted"],
                                                   "padding": "8px"})
    df = _sort_sources(by_source, how)
    non_g = df[df["source_id"] != "gdelt"]["n"]
    max_n = int(non_g.max()) if len(non_g) else int(df["n"].max())
    max_n = max(max_n, 1)

    rows = []
    for _, r in df.iterrows():
        sid = str(r["source_id"])
        n = int(r["n"])
        tier = _FEED_TIER.get(sid, "C" if sid == "gdelt" else "?")
        tcls = tier if tier in ("A", "B", "C") else "U"
        is_gdelt = (sid == "gdelt")
        pct = 100 if is_gdelt else max(3, min(100, int(round(100 * n / max_n))))
        bar_col = P["gold"] if is_gdelt else P["navy3"]
        chip = html.Span(tier, className=f"emd-tier emd-tier--{tcls}",
                         title=f"Source Tier {tier}", style={"marginRight": "8px"})
        bar_inner = html.Div(style={"width": f"{pct}%", "height": "8px",
                                    "borderRadius": "4px", "background": bar_col})
        bar = html.Div(bar_inner, style={"background": "#EEF1F6",
                                         "borderRadius": "4px", "width": "100%",
                                         "height": "8px"})
        rows.append(html.Tr([
            html.Td([chip, html.Span(sid, style={"fontWeight": 600,
                                                 "color": P["navy1"]}),
                     (html.Span(" firehose", style={
                         "fontSize": "9.5px", "color": P["gold"],
                         "marginLeft": "6px", "fontWeight": 700}) if is_gdelt
                      else html.Span())],
                    style={"whiteSpace": "nowrap", "padding": "6px 10px 6px 0"}),
            html.Td(bar, style={"width": "230px", "padding": "6px 10px"}),
            html.Td(f"{n:,}", style={"textAlign": "right", "width": "64px",
                                     "color": P["ink"], "fontWeight": 600,
                                     "fontVariantNumeric": "tabular-nums"}),
            html.Td(_short_span(r["first"], r["last"]),
                    style={"textAlign": "right", "color": P["muted"],
                           "fontSize": "11px", "whiteSpace": "nowrap",
                           "paddingLeft": "12px"}),
        ], style={"borderBottom": f"1px solid {P['border']}"}))

    def th(txt, align):
        return html.Th(txt, style={"textAlign": align, "fontSize": "10.5px",
                                   "color": P["navy2"], "letterSpacing": ".4px",
                                   "textTransform": "uppercase",
                                   "padding": "0 10px 6px 0"})
    thead = html.Thead(html.Tr([th("Source", "left"),
                                th("Share of headlines*", "left"),
                                th("Rows", "right"), th("Span", "right")],
                               style={"borderBottom": f"2px solid {P['gold']}"}))
    table = html.Table([thead, html.Tbody(rows)],
                       style={"width": "100%", "borderCollapse": "collapse",
                              "fontSize": "12.5px"})
    note = html.Div("* bars scale to the largest non-GDELT source; GDELT is the "
                    "firehose and can't be split by sub-source.",
                    style={"fontSize": "10.5px", "color": P["muted"],
                           "fontStyle": "italic", "marginTop": "8px"})
    return html.Div([html.Div(table, style={"maxWidth": "660px"}), note])


def _dead_feed_box(dead):
    if not dead:
        return html.Div()
    chips = [html.Span(sid, style={
        "display": "inline-block", "fontSize": "11px", "fontWeight": 600,
        "color": "#8A6D1B", "background": "#FBF3E2",
        "border": "1px solid #E7D9B0", "borderRadius": "6px",
        "padding": "1px 7px", "margin": "2px 4px 2px 0"}) for sid in dead]
    return html.Div([
        html.Div("Feeds configured but holding 0 rows",
                 style={"fontSize": "11px", "fontWeight": 700,
                        "color": "#8A6D1B", "marginBottom": "4px"}),
        html.Div(chips),
        html.Div("New feeds sit here until their first pull; the rest are likely "
                 "a bad URL or blocked on this network.",
                 style={"fontSize": "10.5px", "color": P["muted"],
                        "fontStyle": "italic", "marginTop": "5px"}),
    ], style={"maxWidth": "660px", "background": "#FCFAF3",
              "border": "1px solid #ECE3C6", "borderRadius": "10px",
              "padding": "10px 12px", "margin": "12px 0 0"})


def _news_stats_line(nc):
    tier = nc.get("by_tier", {})
    span = nc.get("span", ("-", "-"))
    pct = nc.get("tagged_pct", 0.0)
    tagged = nc.get("tagged", 0)
    total = nc.get("total", 0)
    desk = nc.get("by_desk", {})

    head = html.Div([
        html.Span(f"{total:,} headlines", style={"fontWeight": 700,
                  "color": P["navy1"], "fontSize": "14px"}),
        html.Span(f"{span[0]} \u2192 {span[1]}", style={"color": P["muted"],
                  "fontSize": "11.5px", "marginLeft": "10px"}),
        html.Span(f"A:{tier.get('A', 0):,}  B:{tier.get('B', 0):,}  "
                  f"C:{tier.get('C', 0):,}", style={"color": P["muted"],
                  "fontSize": "11.5px", "marginLeft": "14px",
                  "fontVariantNumeric": "tabular-nums"}),
        html.Span(f"tagged {pct}%", style={"color": P["good"], "fontWeight": 700,
                  "fontSize": "11.5px", "marginLeft": "14px"}),
        html.Span(f"({tagged:,}/{total:,})", style={"color": P["muted"],
                  "fontSize": "11px", "marginLeft": "4px"}),
    ], style={"marginBottom": "8px"})

    chips = [html.Span("By desk:", style={"fontSize": "10.5px", "fontWeight": 700,
             "color": P["navy2"], "marginRight": "6px",
             "textTransform": "uppercase", "letterSpacing": ".4px"})]
    for d in list(config.DESK_LABELS) + ["(no desk)"]:
        if d not in desk:
            continue
        nodesk = (d == "(no desk)")
        chips.append(html.Span(f"{config.DESK_LABELS.get(d, d)}: {desk[d]:,}",
                               style={
            "display": "inline-block", "fontSize": "11px", "fontWeight": 600,
            "color": P["muted"] if nodesk else P["navy1"],
            "background": "#F3F4F7" if nodesk else "#EAF0F9",
            "border": f"1px solid {'#E0E3E9' if nodesk else '#D5E0F1'}",
            "borderRadius": "20px", "padding": "2px 10px",
            "margin": "2px 6px 2px 0"}))
    return html.Div([head, html.Div(chips, style={"marginBottom": "4px"})])


def _news_coverage_panel(nc):
    if not nc or nc.get("total", 0) == 0:
        return html.Div("No news yet - pull it in the News Pull Panel above.",
                        style={"color": P["muted"], "padding": "8px"})
    return html.Div([
        _news_stats_line(nc),
        html.Div(id="news-src-body",
                 children=_news_source_table(
                     nc.get("by_source"),
                     _load_state().get("news_src_sort", "headlines"))),
        _dead_feed_box(nc.get("dead_feeds", [])),
    ])


def _news_sort_control():
    return html.Div([
        html.Span("Sort by", style={"fontSize": "10.5px", "fontWeight": 700,
                                    "letterSpacing": ".5px",
                                    "textTransform": "uppercase",
                                    "color": P["navy2"], "marginRight": "8px"}),
        dcc.Dropdown(id="news-src-sort",
                     value=_load_state().get("news_src_sort", "headlines"),
                     clearable=False, options=_SORT_OPTS,
                     persistence=True, persistence_type="local",
                     style={"width": "210px"}),
    ], style={"display": "flex", "alignItems": "center"})


# ===================================================================
# STATS STRIP
# ===================================================================
def _tiles(counts, cov):
    def tile(label, value):
        return html.Div([html.Div(label, className="emd-stat-label"),
                         html.Div(value, className="emd-stat-value")],
                        className="emd-stat")
    n_countries = cov[cov["scope"].isin(["macro", "market"])]["key"].nunique()
    return html.Div([
        tile("Macro rows", f"{counts.get('macro_data', 0):,}"),
        tile("Market rows", f"{counts.get('market_data', 0):,}"),
        tile("Global rows", f"{counts.get('global_market', 0):,}"),
        tile("Commodity rows", f"{counts.get('commodity_data', 0):,}"),
        tile("News rows", f"{counts.get('news', 0):,}"),
        tile("Pred-market", f"{counts.get('predmarket_data', 0):,}"),
        tile("Countries w/ data", f"{n_countries}"),
    ], className="emd-stat-row")


# ===================================================================
# RENDER
# ===================================================================
def _compute():
    return (core.coverage(), core.table_counts(),
            core.ingest_log_df(), core.news_coverage())


def _render(cov, counts, log, news):
    gauges_commodities = html.Div([
        html.Div([html.Div("Global gauges", style={
            "fontSize": "11px", "fontWeight": 700, "letterSpacing": ".5px",
            "textTransform": "uppercase", "color": P["navy2"],
            "marginBottom": "6px"}),
            _simple_list(cov, "global", "series")],
            style={"flex": "0 1 440px", "maxWidth": "440px", "minWidth": "0"}),
        html.Div([html.Div("Commodities", style={
            "fontSize": "11px", "fontWeight": 700, "letterSpacing": ".5px",
            "textTransform": "uppercase", "color": P["navy2"],
            "marginBottom": "6px"}),
            _simple_list(cov, "commodity", "commodity")],
            style={"flex": "0 1 440px", "maxWidth": "440px", "minWidth": "0"}),
    ], style={"display": "flex", "gap": "24px", "flexWrap": "wrap"})

    news_body = (runner.news_panel(log) if runner is not None
                 else html.Span("runner.py not available"))
    data_body = (runner.data_panel(log) if runner is not None
                 else html.Span("runner.py not available"))

    if indicator_coverage is not None:
        try:
            indicator_body = indicator_coverage.render(
                indicator_coverage.coverage_snapshot(state=_load_state()))
        except Exception as exc:
            indicator_body = html.Div(
                f"Indicator Analysis coverage unavailable: {exc}",
                style={"color": P["bad"], "fontSize": "11px"})
    else:
        indicator_body = html.Div("Indicator Analysis coverage module unavailable.",
                                  style={"color": P["muted"]})

    return html.Div([
        _tiles(counts, cov),
        _section("Indicator Analysis live-source coverage", indicator_body,
                 subtitle="provider universe · full EMDASH catalogue · dynamic coverage/status"),
        _section("News Pull Panel", news_body,
                 subtitle="fetch headlines into the warehouse"),
        _section("Data Pull Panel", data_body,
                 subtitle="tick sources, choose a timeframe, pull"),
        _section("News sources in the warehouse", _news_coverage_panel(news),
                 right=_news_sort_control()),
        _section("Macro coverage", _matrix(cov, "macro", _MACRO_ORDER, daily=False),
                 subtitle="country \u00d7 indicator \u00b7 cell = observations"),
        _section("Market coverage", _matrix(cov, "market", _MARKET_ORDER, daily=True),
                 subtitle="daily rows \u00b7 colour = freshness "
                          "(green <30d, amber <90d, red stale)"),
        _section("Global gauges & commodities", gauges_commodities),
    ], style={"paddingBottom": "24px"})


def warm_cache():
    try:
        cov, counts, log, news = _compute()
        _CACHE.update({"cov": cov, "counts": counts, "log": log, "news": news,
                       "rendered": _render(cov, counts, log, news), "clicks": 0,
                       "indicator_stamp": (indicator_coverage.status_stamp()
                                           if indicator_coverage is not None else 0.0)})
    except Exception:
        pass


def tab():
    return dcc.Tab(
        label="Data Coverage & Updates", value="database", className="emd-tab",
        selected_className="emd-tab--selected", children=[
            html.Div([
                html.Span("Local warehouse \u00b7 emdash.sqlite",
                          style={"fontSize": "12px", "fontWeight": 600,
                                 "color": P["muted"]}),
                html.Button("Refresh", id="db-refresh", n_clicks=0,
                            className="emd-btn"),
            ], style={"display": "flex", "alignItems": "center",
                      "justifyContent": "space-between",
                      "padding": "12px 16px"}),
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
        current_stamp = (indicator_coverage.status_stamp()
                         if indicator_coverage is not None else 0.0)
        if (_CACHE["rendered"] is not None and clicks <= _CACHE["clicks"]
                and current_stamp == _CACHE.get("indicator_stamp", 0.0)):
            return _CACHE["rendered"]
        try:
            cov, counts, log, news = _compute()
            rendered = _render(cov, counts, log, news)
        except Exception as e:
            return html.Div(f"coverage read failed: {e}",
                            style={"color": P["bad"], "padding": "16px"})
        _CACHE.update({"cov": cov, "counts": counts, "log": log, "news": news,
                       "rendered": rendered, "clicks": clicks,
                       "indicator_stamp": current_stamp})
        return rendered

    @app.callback(
        Output({"type": "ia-coverage-detail", "provider": ALL}, "open"),
        Input("ia-cov-expand-all", "n_clicks"),
        Input("ia-cov-collapse-all", "n_clicks"),
        State({"type": "ia-coverage-detail", "provider": ALL}, "id"),
        prevent_initial_call=True)
    def _toggle_indicator_coverage(expand_clicks, collapse_clicks, ids):
        triggered = ctx.triggered_id or ""
        return _indicator_coverage_open_states(triggered, ids)

    @app.callback(Output("news-src-body", "children"),
                  Input("news-src-sort", "value"),
                  prevent_initial_call=True)
    def _sort_news(how):
        how = how or "headlines"
        _save_state("news_src_sort", how)
        nc = _CACHE.get("news")
        if not nc or nc.get("total", 0) == 0:
            return html.Div()
        return _news_source_table(nc.get("by_source"), how)


def _indicator_coverage_open_states(triggered, ids):
    if not ids:
        return []
    return [triggered == "ia-cov-expand-all"] * len(ids)
