"""EMDASH Indicator Analysis and Market Watch V1 UI.

Provider I/O, Market Watch snapshot calculations and caching live in
indicator_providers.py. This module manages the provider-neutral watch state/UI,
the dynamic series editor, deterministic transformations, charting, statistics,
diagnostics and underlying data. It never reads or writes emdash.sqlite.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import uuid
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import ALL, Input, Output, State, ctx, dash_table, dcc, html, no_update

import config
from indicator_providers import (
    FRED_INDICATORS, MAX_MARKET_WATCH, MAX_SERIES, MARKET_INDICATORS,
    MARKET_WATCH_SERVICE, PROVIDER_LABELS, SERVICE, GembridgeExcelProvider,
    HistoryWindow, SeriesRequest, catalogue, indicator_options,
)


P = config.PALETTE
F = config.FONTS
TODAY = dt.datetime.now(dt.timezone.utc).date()
COUNTRY_OPTIONS = sorted(
    ({"label": f"{name} ({iso})", "value": iso} for iso, name, *_ in config.COUNTRIES),
    key=lambda item: item["label"],
)
COLORS = [
    ("Navy", P["navy2"]), ("Gold", P["gold"]), ("Light blue", P["navy3"]),
    ("Green", P["good"]), ("Red", P["bad"]), ("Brown", P.get("brown", "#74592D")),
    ("Grey", P["grey"]), ("Dark navy", P["navy1"]),
]
COLOR_OPTIONS = [{"label": name, "value": colour} for name, colour in COLORS]
GLOBAL_MODES = {
    "native": "Native / Actual Values",
    "indexed": "Indexed to 100",
    "pct_start": "Change from Chart Start (%)",
    "standardised": "Standardised (Z-score)",
}
FETCH_OPTIONS = [
    {"label": "5 Years", "value": "5y"}, {"label": "10 Years", "value": "10y"},
    {"label": "20 Years", "value": "20y"}, {"label": "Max Available", "value": "max"},
    {"label": "Custom", "value": "custom"},
]
CHART_OPTIONS = [
    {"label": "1 Year", "value": "1y"}, {"label": "5 Years", "value": "5y"},
    {"label": "10 Years", "value": "10y"}, {"label": "20 Years", "value": "20y"},
    {"label": "Max Available", "value": "max"}, {"label": "Custom", "value": "custom"},
]
TRANSFORM_LABELS = {
    "level": "Level", "diff": "Absolute difference", "pp_diff": "Percentage-point difference",
    "pop_pct": "Period-over-period %",
    "mom": "MoM %", "qoq": "QoQ %", "yoy": "YoY %",
    "rolling_mean": "Rolling average", "rebase": "Rebased index",
    "rolling_zscore": "Rolling Z-score",
}
MARKET_WATCH_PROVIDER_OPTIONS = [
    {"label": PROVIDER_LABELS["yahoo_market"], "value": "yahoo_market"},
]


def default_market_watch() -> dict[str, Any]:
    """Compact initial board; all state remains in emdash_state.json."""
    groups = [
        {"uid": "mw-global", "name": "Global risk", "collapsed": False},
        {"uid": "mw-fx", "name": "FX", "collapsed": False},
        {"uid": "mw-commodities", "name": "Commodities", "collapsed": False},
    ]
    instruments = [
        ("mw-spx", "SPX", "mw-global"), ("mw-vix", "VIX", "mw-global"),
        ("mw-us10y", "US10Y", "mw-global"), ("mw-eem", "EEM", "mw-global"),
        ("mw-eurusd", "EURUSD", "mw-fx"), ("mw-usdjpy", "USDJPY", "mw-fx"),
        ("mw-dxy", "DXY", "mw-fx"), ("mw-brent", "BRENT", "mw-commodities"),
        ("mw-gold", "GOLD", "mw-commodities"),
    ]
    return {
        "collapsed": False,
        "groups": groups,
        "instruments": [
            {"uid": uid, "provider": "yahoo_market", "indicator": indicator,
             "geography": "Market", "group_uid": group_uid}
            for uid, indicator, group_uid in instruments
        ],
    }


def _normalise_market_watch(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = copy.deepcopy(value) if isinstance(value, dict) else default_market_watch()
    groups, seen_groups = [], set()
    for index, item in enumerate(raw.get("groups") or []):
        uid = str(item.get("uid") or f"mw-group-{index}-{_uid()}")
        if uid in seen_groups:
            continue
        seen_groups.add(uid)
        groups.append({"uid": uid, "name": str(item.get("name") or "Group")[:48],
                       "collapsed": bool(item.get("collapsed", False))})
    if not groups:
        groups = [{"uid": "mw-main", "name": "Markets", "collapsed": False}]
        seen_groups = {"mw-main"}
    instruments, seen_uids = [], set()
    for index, item in enumerate((raw.get("instruments") or [])[:MAX_MARKET_WATCH]):
        provider = str(item.get("provider") or "yahoo_market")
        indicator = str(item.get("indicator") or "")
        if not indicator or indicator not in catalogue(provider):
            continue
        uid = str(item.get("uid") or f"mw-{index}-{_uid()}")
        if uid in seen_uids:
            uid = f"{uid}-{_uid()}"
        seen_uids.add(uid)
        group_uid = str(item.get("group_uid") or groups[0]["uid"])
        if group_uid not in seen_groups:
            group_uid = groups[0]["uid"]
        instruments.append({
            "uid": uid, "provider": provider, "indicator": indicator,
            "geography": str(item.get("geography") or
                             ("Market" if provider == "yahoo_market" else "")),
            "group_uid": group_uid,
            "options": dict(item.get("options") or {}),
        })
    return {"collapsed": bool(raw.get("collapsed", False)),
            "groups": groups, "instruments": instruments}


def mutate_market_watch(value: dict[str, Any] | None, operation: str,
                        uid: str | None = None, payload: Any = None) -> dict[str, Any]:
    """Pure Market Watch state reducer used by callbacks and local tests."""
    state = _normalise_market_watch(value)
    groups, instruments = state["groups"], state["instruments"]
    if operation == "toggle_outer":
        state["collapsed"] = not state["collapsed"]
    elif operation == "add_group":
        name = str(payload or "").strip()
        if name and len(groups) < 10:
            groups.append({"uid": f"mw-group-{_uid()}", "name": name[:48],
                           "collapsed": False})
    elif operation == "add_instrument" and isinstance(payload, dict):
        provider = str(payload.get("provider") or "yahoo_market")
        indicator = str(payload.get("indicator") or "")
        duplicate = any(row["provider"] == provider and
                        row["indicator"] == indicator for row in instruments)
        if (not duplicate and len(instruments) < MAX_MARKET_WATCH and
                indicator in catalogue(provider)):
            group_uid = str(payload.get("group_uid") or groups[0]["uid"])
            if not any(group["uid"] == group_uid for group in groups):
                group_uid = groups[0]["uid"]
            instruments.append({"uid": f"mw-item-{_uid()}",
                                "provider": provider, "indicator": indicator,
                                "geography": "Market", "group_uid": group_uid,
                                "options": {}})
    elif operation.startswith("group_"):
        pos = next((i for i, row in enumerate(groups) if row["uid"] == uid), None)
        if pos is not None:
            action = operation[6:]
            if action == "toggle":
                groups[pos]["collapsed"] = not groups[pos]["collapsed"]
            elif action == "up" and pos > 0:
                groups[pos - 1], groups[pos] = groups[pos], groups[pos - 1]
            elif action == "down" and pos < len(groups) - 1:
                groups[pos + 1], groups[pos] = groups[pos], groups[pos + 1]
            elif action == "delete" and len(groups) > 1:
                destination = next(group["uid"] for i, group in enumerate(groups)
                                   if i != pos)
                for item in instruments:
                    if item["group_uid"] == uid:
                        item["group_uid"] = destination
                groups.pop(pos)
    elif operation.startswith("instrument_"):
        pos = next((i for i, row in enumerate(instruments) if row["uid"] == uid), None)
        if pos is not None:
            action = operation[11:]
            if action == "delete":
                instruments.pop(pos)
            elif action == "group":
                if any(group["uid"] == payload for group in groups):
                    instruments[pos]["group_uid"] = payload
            elif action in ("up", "down"):
                group_uid = instruments[pos]["group_uid"]
                member_positions = [i for i, row in enumerate(instruments)
                                    if row["group_uid"] == group_uid]
                member_index = member_positions.index(pos)
                target_member = member_index + (-1 if action == "up" else 1)
                if 0 <= target_member < len(member_positions):
                    target = member_positions[target_member]
                    instruments[pos], instruments[target] = instruments[target], instruments[pos]
    return _normalise_market_watch(state)


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _new_series(provider="world_bank", geography="USA", indicator="NY.GDP.MKTP.KD.ZG",
                colour=None, collapsed=False) -> dict[str, Any]:
    return {
        "uid": _uid(), "included": True, "collapsed": collapsed,
        "provider": provider, "geography": geography, "indicator": indicator,
        "transform": "level", "window": 5, "colour": colour or COLORS[0][1],
    }


def default_series() -> list[dict[str, Any]]:
    return [
        _new_series("world_bank", "USA", "NY.GDP.MKTP.KD.ZG", COLORS[0][1], False),
        _new_series("world_bank", "CHN", "NY.GDP.MKTP.KD.ZG", COLORS[1][1], True),
    ]


def valid_transforms(frequency: str, semantic_type: str = "raw_level") -> list[str]:
    freq = (frequency or "Irregular").lower()
    semantic = (semantic_type or "raw_level").lower()
    if semantic == "event":
        return ["level", "diff"]
    if semantic in ("growth_rate", "rate", "ratio"):
        return ["level", "pp_diff", "rolling_mean", "rolling_zscore"]
    base = ["level", "diff"]
    if not any(word in freq for word in ("event", "irregular")):
        base.append("pop_pct")
    if "month" in freq:
        base.extend(["mom", "qoq", "yoy"])
    elif "quarter" in freq:
        base.extend(["qoq", "yoy"])
    elif "annual" in freq or "year" in freq:
        base.append("yoy")
    elif any(word in freq for word in ("daily", "weekly")):
        base.append("yoy")
    base.extend(["rolling_mean", "rebase", "rolling_zscore"])
    return list(dict.fromkeys(base))


def transform_options(frequency: str, semantic_type: str = "raw_level") -> list[dict[str, str]]:
    return [{"label": TRANSFORM_LABELS[key], "value": key}
            for key in valid_transforms(frequency, semantic_type)]


def default_transform(frequency: str, semantic_type: str) -> str:
    if semantic_type == "index" and "month" in (frequency or "").lower():
        return "yoy"
    return "level"


def _definition_meta(item: dict[str, Any], excel_catalog: list[dict[str, Any]],
                     fred_catalog: list[dict[str, Any]] | None = None) -> dict[str, str]:
    provider, indicator = item.get("provider"), item.get("indicator")
    if provider == "gembridge_excel":
        entry = next((row for row in (excel_catalog or []) if row.get("series_id") == indicator), {})
        return {
            "label": entry.get("label", indicator or "Excel series"),
            "frequency": entry.get("frequency", "Irregular"), "unit": entry.get("unit", "Unspecified"),
            "geography": entry.get("geography", ""),
            "semantic_type": entry.get("semantic_type", "raw_level"),
        }
    if provider == "fred" and indicator not in FRED_INDICATORS:
        entry = item.get("fred_definition") or next(
            (row for row in (fred_catalog or []) if row.get("code") == indicator), {})
        if entry:
            return {"label": entry.get("label", indicator),
                    "frequency": entry.get("frequency", "Irregular"),
                    "unit": entry.get("unit", "Unspecified"),
                    "geography": "United States",
                    "semantic_type": entry.get("semantic_type", "raw_level")}
    definition = catalogue(provider).get(indicator)
    if definition:
        geography = item.get("geography", "")
        if provider == "yahoo_market": geography = definition.asset or "Market"
        if provider == "fred": geography = "United States"
        return {"label": definition.label, "frequency": definition.frequency,
                "unit": definition.unit, "geography": geography,
                "semantic_type": definition.semantic_type}
    return {"label": indicator or "Select indicator", "frequency": "Irregular",
            "unit": "Unspecified", "geography": item.get("geography", ""),
            "semantic_type": "raw_level"}


def _provider_indicator_options(provider: str, excel_catalog: list[dict[str, Any]],
                                fred_catalog: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    if provider == "gembridge_excel":
        return [{"label": f"{row.get('label', row['series_id'])} · {row['series_id']}", "value": row["series_id"]}
                for row in sorted(excel_catalog or [], key=lambda row: row.get("label", row.get("series_id", "")))]
    if provider == "fred":
        options = indicator_options("fred")
        seen = {item["value"] for item in options}
        options.extend({"label": f"{row.get('label', row['code'])} · {row['code']}", "value": row["code"]}
                       for row in (fred_catalog or []) if row.get("code") not in seen)
        return options
    return indicator_options(provider)


def _field(component, label: str, class_name=""):
    return html.Div([html.Span(label, className="emd-ctrl-label"), component], className=f"ia-field {class_name}".strip())


def _summary_name(item: dict[str, Any], excel_catalog: list[dict[str, Any]], fred_catalog=None) -> str:
    meta = _definition_meta(item, excel_catalog, fred_catalog)
    geo = meta["geography"] or item.get("geography", "") or "Global"
    return f"{geo} — {meta['label']}"


def _series_card(item: dict[str, Any], index: int, excel_catalog: list[dict[str, Any]], fred_catalog=None) -> html.Div:
    uid, provider = item["uid"], item.get("provider", "world_bank")
    meta = _definition_meta(item, excel_catalog, fred_catalog)
    options = _provider_indicator_options(provider, excel_catalog, fred_catalog)
    indicator = item.get("indicator")
    if indicator not in {option["value"] for option in options} and options:
        indicator = options[0]["value"]
    transform = item.get("transform", "level")
    valid = valid_transforms(meta["frequency"], meta["semantic_type"])
    if transform not in valid:
        transform = default_transform(meta["frequency"], meta["semantic_type"])
    actions = html.Div([
        html.Button("↑", id={"type": "ia-action", "uid": uid, "action": "up"}, n_clicks=0, className="ia-icon-btn", title="Move up", disabled=index == 0),
        html.Button("↓", id={"type": "ia-action", "uid": uid, "action": "down"}, n_clicks=0, className="ia-icon-btn", title="Move down"),
        html.Button("Duplicate", id={"type": "ia-action", "uid": uid, "action": "duplicate"}, n_clicks=0, className="ia-text-btn"),
        html.Button("Delete", id={"type": "ia-action", "uid": uid, "action": "delete"}, n_clicks=0, className="ia-text-btn ia-delete"),
    ], className="ia-series-actions")
    header = html.Div([
        html.Button("▸" if item.get("collapsed") else "▾", id={"type": "ia-action", "uid": uid, "action": "collapse"}, n_clicks=0, className="ia-collapse-btn", title="Expand/collapse"),
        html.Span(style={"backgroundColor": item.get("colour", COLORS[index % len(COLORS)][1])}, className="ia-colour-mark"),
        html.Div([
            html.Div(_summary_name(item, excel_catalog, fred_catalog), className="ia-series-name"),
            html.Div(f"{PROVIDER_LABELS.get(provider, provider)} · {meta['frequency']} · {TRANSFORM_LABELS.get(transform, transform)}", className="ia-series-meta"),
        ], className="ia-series-summary"),
        dcc.Checklist(id={"type": "ia-field", "uid": uid, "field": "included"}, value=["on"] if item.get("included", True) else [], options=[{"label": "Include", "value": "on"}], className="emd-check ia-include"),
        actions,
    ], className="ia-series-card-head")
    editor = html.Div([
        _field(dcc.Dropdown(id={"type": "ia-field", "uid": uid, "field": "provider"}, value=provider, clearable=False,
                            options=[{"label": label, "value": key} for key, label in PROVIDER_LABELS.items()]), "Source", "ia-provider-field"),
        (_field(dcc.Dropdown(id={"type": "ia-field", "uid": uid, "field": "geography"}, value=item.get("geography", "USA"), clearable=False, searchable=True, options=COUNTRY_OPTIONS), "Geography", "ia-geography-field")
         if provider in ("world_bank", "imf_datamapper", "imf_sdmx") else
         _field(html.Div(meta["geography"] or "From source metadata", className="ia-adaptive-value"), "Asset class" if provider == "yahoo_market" else ("Coverage" if provider == "fred" else "Geography"), "ia-geography-field")),
        _field(dcc.Dropdown(id={"type": "ia-field", "uid": uid, "field": "indicator"}, value=indicator, clearable=False, searchable=True, options=options, placeholder="Load Excel catalogue first" if provider == "gembridge_excel" else "Select series"), "Indicator / series", "ia-indicator-field"),
        _field(dcc.Dropdown(id={"type": "ia-field", "uid": uid, "field": "transform"}, value=transform, clearable=False, options=transform_options(meta["frequency"], meta["semantic_type"])), "Series transformation", "ia-transform-field"),
        (_field(dcc.Input(id={"type": "ia-field", "uid": uid, "field": "window"}, type="number", min=2, max=500, step=1, value=int(item.get("window", 5)), className="emd-input ia-window-input"), "Window (obs.)", "ia-window-field")
         if transform in ("rolling_mean", "rolling_zscore") else
         html.Div(className="ia-window-field ia-window-placeholder")),
        _field(dcc.Dropdown(id={"type": "ia-field", "uid": uid, "field": "colour"}, value=item.get("colour", COLORS[index % len(COLORS)][1]), clearable=False, options=COLOR_OPTIONS), "Colour", "ia-colour-field"),
    ], className="ia-series-editor-body", style={"display": "none"} if item.get("collapsed") else {})
    return html.Div([header, editor], className="ia-series-card ia-series-disabled" if not item.get("included", True) else "ia-series-card")


def _mw_price(value: Any, unit: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    decimals = 4 if " per " in str(unit).lower() else (3 if abs(number) < 10 else 2)
    return f"{number:,.{decimals}f}"


def _mw_change(value: Any) -> tuple[str, str]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—", "mw-change mw-change--flat"
    if not math.isfinite(number):
        return "—", "mw-change mw-change--flat"
    tone = "positive" if number > 0 else ("negative" if number < 0 else "flat")
    return f"{number:+.2f}%", f"mw-change mw-change--{tone}"


def _mw_sparkline(points: list[dict[str, Any]], colour: str) -> go.Figure:
    x = [row.get("date") for row in points or []]
    y = [row.get("value") for row in points or []]
    fig = go.Figure(go.Scatter(x=x, y=y, mode="lines",
                               line={"color": colour, "width": 1.6},
                               hoverinfo="skip"))
    fig.update_layout(height=34, width=112, margin={"l": 1, "r": 1, "t": 2, "b": 2},
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False, xaxis={"visible": False, "fixedrange": True},
                      yaxis={"visible": False, "fixedrange": True})
    return fig


def _mw_instrument_row(item: dict[str, Any], snapshot: dict[str, Any] | None,
                       group_options: list[dict[str, str]], index: int,
                       group_size: int) -> html.Div:
    definition = catalogue(item["provider"]).get(item["indicator"])
    snapshot = snapshot or {}
    values = []
    for key in ("change_1d", "change_1w", "change_1m", "change_ytd"):
        text, class_name = _mw_change(snapshot.get(key))
        values.append(html.Div(text, className=class_name))
    last_change = snapshot.get("change_1d")
    spark_colour = P["good"] if isinstance(last_change, (int, float)) and last_change > 0 else (
        P["bad"] if isinstance(last_change, (int, float)) and last_change < 0 else P["navy3"])
    freshness = snapshot.get("freshness", "Awaiting data")
    freshness_tone = snapshot.get("freshness_tone", "unknown")
    freshness_title = (
        f"Market observation: {snapshot.get('as_of') or 'not loaded'}; "
        f"retrieved: {str(snapshot.get('retrieved_at') or 'not loaded').replace('T', ' ')}; "
        f"status: {snapshot.get('cache_status') or 'not loaded'}"
    )
    label = snapshot.get("label") or (definition.label if definition else item["indicator"])
    unit = snapshot.get("unit") or (definition.unit if definition else "")
    return html.Div([
        html.Div([
            html.Div(item["indicator"], className="mw-code"),
            html.Div(label, className="mw-label", title=label),
            html.Div(PROVIDER_LABELS.get(item["provider"], item["provider"]),
                     className="mw-provider"),
        ], className="mw-instrument"),
        html.Div([html.Div(_mw_price(snapshot.get("last"), unit), className="mw-last"),
                  html.Div(unit, className="mw-unit")], className="mw-price"),
        *values,
        html.Div(dcc.Graph(figure=_mw_sparkline(snapshot.get("sparkline", []), spark_colour),
                           config={"displayModeBar": False, "staticPlot": True,
                                   "responsive": False}), className="mw-spark"),
        html.Div([
            html.Span(freshness, className=f"mw-fresh mw-fresh--{freshness_tone}"),
            html.Span(snapshot.get("as_of") or "—", className="mw-asof"),
        ], className="mw-freshness", title=freshness_title),
        html.Div([
            dcc.Dropdown(id={"type": "mw-instrument-group", "uid": item["uid"]},
                         value=item["group_uid"], options=group_options,
                         clearable=False, searchable=False,
                         className="mw-group-select"),
            html.Button("↑", id={"type": "mw-instrument-action", "uid": item["uid"], "action": "up"},
                        n_clicks=0, className="mw-icon-btn", title="Move up in group",
                        disabled=index == 0),
            html.Button("↓", id={"type": "mw-instrument-action", "uid": item["uid"], "action": "down"},
                        n_clicks=0, className="mw-icon-btn", title="Move down in group",
                        disabled=index >= group_size - 1),
            html.Button("Chart in IA", id={"type": "mw-chart", "uid": item["uid"]},
                        n_clicks=0, className="mw-chart-btn",
                        title="Add or focus this instrument in Indicator Analysis"),
            html.Button("×", id={"type": "mw-instrument-action", "uid": item["uid"], "action": "delete"},
                        n_clicks=0, className="mw-icon-btn mw-remove", title="Remove"),
        ], className="mw-row-actions"),
    ], className="mw-row")


def _mw_header_row() -> html.Div:
    return html.Div([
        html.Div("Instrument", className="mw-h-instrument"), html.Div("Last", className="mw-h-last"),
        html.Div("1D"), html.Div("1W"), html.Div("1M", title="Trailing one month; not month-to-date"), html.Div("YTD"),
        html.Div("Trend", className="mw-h-spark", title="Latest 30 daily observations"), html.Div("Freshness"),
        html.Div("Actions", className="mw-h-actions"),
    ], className="mw-column-head")


def _market_watch_body(config_value: dict[str, Any], data: dict[str, Any] | None) -> html.Div:
    config_value = _normalise_market_watch(config_value)
    snapshots = {row.get("request_id"): row for row in (data or {}).get("instruments", [])}
    group_options = [{"label": row["name"], "value": row["uid"]}
                     for row in config_value["groups"]]
    groups = []
    for group_index, group in enumerate(config_value["groups"]):
        members = [row for row in config_value["instruments"]
                   if row["group_uid"] == group["uid"]]
        group_head = html.Div([
            html.Button("▸" if group["collapsed"] else "▾",
                        id={"type": "mw-group-action", "uid": group["uid"], "action": "toggle"},
                        n_clicks=0, className="mw-group-toggle"),
            html.Div(group["name"], className="mw-group-name"),
            html.Div(f"{len(members)} instrument{'s' if len(members) != 1 else ''}",
                     className="mw-group-count"),
            html.Button("↑", id={"type": "mw-group-action", "uid": group["uid"], "action": "up"},
                        n_clicks=0, className="mw-icon-btn", disabled=group_index == 0,
                        title="Move group up"),
            html.Button("↓", id={"type": "mw-group-action", "uid": group["uid"], "action": "down"},
                        n_clicks=0, className="mw-icon-btn",
                        disabled=group_index >= len(config_value["groups"]) - 1,
                        title="Move group down"),
            html.Button("Delete group", id={"type": "mw-group-action", "uid": group["uid"], "action": "delete"},
                        n_clicks=0, className="mw-group-delete",
                        disabled=len(config_value["groups"]) <= 1,
                        title="Move its instruments to another group and delete this group"),
        ], className="mw-group-head")
        rows = [] if group["collapsed"] else [
            _mw_instrument_row(item, snapshots.get(item["uid"]), group_options,
                               index, len(members))
            for index, item in enumerate(members)
        ]
        groups.append(html.Div([group_head] + ([] if group["collapsed"] else [_mw_header_row()] + rows),
                               className="mw-group"))

    instrument_options = indicator_options("yahoo_market")
    existing = {(row["provider"], row["indicator"])
                for row in config_value["instruments"]}
    instrument_options = [dict(option, disabled=("yahoo_market", option["value"]) in existing)
                          for option in instrument_options]
    controls = html.Details([
        html.Summary("Manage watchlist", className="mw-manage-summary"),
        html.Div([
        _field(dcc.Dropdown(id="mw-add-provider", value="yahoo_market",
                            options=MARKET_WATCH_PROVIDER_OPTIONS, clearable=False,
                            searchable=False), "Source"),
        _field(dcc.Dropdown(id="mw-add-indicator", value="SPX",
                            options=instrument_options, clearable=False,
                            searchable=True), "Instrument"),
        _field(dcc.Dropdown(id="mw-add-group", value=config_value["groups"][0]["uid"],
                            options=group_options, clearable=False,
                            searchable=False), "Group"),
        html.Button("Add instrument", id="mw-add-instrument", n_clicks=0,
                    className="emd-btn", disabled=len(config_value["instruments"]) >= MAX_MARKET_WATCH),
        dcc.Input(id="mw-new-group-name", type="text", debounce=True,
                  placeholder="New group name", className="emd-input mw-new-group"),
        html.Button("Add group", id="mw-add-group-button", n_clicks=0,
                    className="emd-btn emd-btn--ghost",
                    disabled=len(config_value["groups"]) >= 10),
        ], className="mw-controls")
    ], className="mw-manage-details", open=False)
    note = html.Div([
        html.Span("Yahoo market data · delayed daily observations · cached through the Indicator Analysis provider layer."),
        html.Span(id="mw-chart-status", className="mw-chart-status"),
    ], className="mw-note")
    return html.Div([controls, note] + groups)


def tab(state: dict[str, Any] | None = None) -> dcc.Tab:
    state = state or {}
    stored = state.get("ia_series_config")
    if not isinstance(stored, list) or not stored: stored = default_series()
    market_watch = _normalise_market_watch(state.get("ia_market_watch"))
    return dcc.Tab(label="Indicator Analysis", value="country", className="emd-tab", selected_className="emd-tab--selected", children=[
        dcc.Store(id="ia-series-config", data=stored, storage_type="memory"),
        dcc.Store(id="ia-excel-catalog", data=[], storage_type="memory"),
        dcc.Store(id="ia-fred-catalog", data=[], storage_type="memory"),
        dcc.Store(id="ia-data-store", storage_type="memory"),
        dcc.Store(id="mw-config", data=market_watch, storage_type="memory"),
        dcc.Store(id="mw-data", storage_type="memory"),
        dcc.Store(id="mw-chart-request", storage_type="memory"),
        html.Div([
            html.Div([html.Div("Indicator Analysis", className="ia-page-title"), html.Div("Build and compare up to eight live or workbook series.", className="ia-page-subtitle")]),
            html.Div([
                html.Button("Collapse All", id="ia-collapse-all", n_clicks=0, className="emd-btn emd-btn--ghost"),
                html.Button("Expand All", id="ia-expand-all", n_clicks=0, className="emd-btn emd-btn--ghost"),
                html.Button("Add Series", id="ia-add-series", n_clicks=0, className="emd-btn"),
            ], className="ia-page-actions"),
        ], className="ia-page-head"),
        html.Div([
            html.Div([
                html.Button("▾", id="mw-toggle", n_clicks=0,
                            className="mw-island-toggle", title="Expand/collapse Market Watch"),
                html.Div([
                    html.Div("Market Watch", className="mw-title"),
                    html.Div("Quick market check; use Chart in IA for deeper analysis.",
                             className="mw-subtitle"),
                ], className="mw-title-wrap"),
                html.Div(id="mw-count", className="mw-count"),
                html.Div(id="mw-status", className="mw-status"),
                html.Button("Refresh", id="mw-refresh", n_clicks=0,
                            className="emd-btn emd-btn--ghost"),
            ], className="mw-island-head"),
            html.Div(id="mw-island-body", className="mw-island-body"),
        ], className="mw-island"),
        html.Div([html.Div(id="ia-series-count", className="ia-series-count"), html.Div(id="ia-series-list")], className="ia-series-workspace"),

        html.Details([
            html.Summary("Data sources and diagnostics"),
            html.Div([
                html.Div("Gembridge Excel", className="ia-subhead"),
                html.Div([
                    _field(dcc.Input(id="ia-excel-path", type="text", debounce=True, value=state.get("ia_excel_path", ""), placeholder=r"C:\path\Gembridge_Series.xlsx", className="emd-input ia-path-input"), "Workbook path"),
                    _field(dcc.Input(id="ia-excel-sheet", type="text", debounce=True, value=state.get("ia_excel_sheet", "Data_Long"), className="emd-input"), "Sheet"),
                    _field(dcc.Input(id="ia-excel-table", type="text", debounce=True, value=state.get("ia_excel_table", "GembridgeSeries"), placeholder="Optional table", className="emd-input"), "Table (optional)"),
                    _field(dcc.Dropdown(id="ia-excel-format", value=state.get("ia_excel_format", "auto"), clearable=False, options=[{"label": "Auto detect", "value": "auto"}, {"label": "Long format", "value": "long"}, {"label": "Wide format", "value": "wide"}]), "Format"),
                    _field(dcc.Input(id="ia-excel-mapping", type="text", debounce=True, value=state.get("ia_excel_mapping", "Mapping"), className="emd-input"), "Mapping sheet"),
                    html.Button("Load Excel Catalogue", id="ia-excel-load", n_clicks=0, className="emd-btn emd-btn--ghost"),
                ], className="ia-source-controls"),
                html.Div(id="ia-excel-status", className="ia-source-status"),
                html.Div("FRED series search", className="ia-subhead ia-test-head"),
                html.Div([
                    dcc.Input(id="ia-fred-search-text", type="text", debounce=True,
                              placeholder="e.g. term premium, Brazil inflation, credit spread",
                              className="emd-input ia-fred-search-input"),
                    html.Button("Search FRED", id="ia-fred-search", n_clicks=0,
                                className="emd-btn emd-btn--ghost"),
                    html.Span("Requires FRED_API_KEY. Results are added to FRED series dropdowns for this session.",
                              className="ia-test-help"),
                ], className="ia-test-controls"),
                html.Div(id="ia-fred-search-status", className="ia-source-status"),
                html.Div("Data Source Test", className="ia-subhead ia-test-head"),
                html.Div([
                    dcc.Dropdown(id="ia-test-provider", value="imf_sdmx", clearable=False, options=[{"label": label, "value": key} for key, label in PROVIDER_LABELS.items()], style={"width": "220px"}),
                    html.Button("Run Source Test", id="ia-run-source-test", n_clicks=0, className="emd-btn emd-btn--ghost"),
                    html.Span("One step: select a source, click Run Source Test, then copy the diagnostic box below.", className="ia-test-help"),
                ], className="ia-test-controls"),
                dcc.Textarea(id="ia-source-test-output", value="", readOnly=True, className="ia-diagnostic-copy", placeholder="Diagnostic output appears here."),
            ], className="ia-sources-body"),
        ], className="emd-es-details ia-sources-details", open=False),

        html.Div([
            _field(dcc.Dropdown(id="ia-fetch-mode", value=state.get("ia_fetch_mode", "20y"), clearable=False, options=FETCH_OPTIONS, style={"width": "165px"}), "Fetch History"),
            html.Div([dcc.DatePickerRange(id="ia-fetch-custom", start_date=state.get("ia_fetch_start", f"{TODAY.year-20}-01-01"), end_date=state.get("ia_fetch_end", TODAY.isoformat()), display_format="YYYY-MM-DD", minimum_nights=0)], id="ia-fetch-custom-wrap", className="ia-date-wrap"),
            html.Div("Controls provider requests and the separate Indicator Analysis cache.", className="ia-control-help"),
            html.Button("Refresh Data", id="ia-refresh", n_clicks=0, className="emd-btn"),
        ], className="emd-controls ia-fetch-controls"),
        dcc.Loading(html.Div([
            html.Div(id="ia-status", className="ia-status"),
            html.Details([html.Summary("Retrieval details and errors"), html.Div(id="ia-retrieval-details"), dcc.Textarea(id="ia-retrieval-diagnostic-copy", readOnly=True, className="ia-diagnostic-copy")], className="ia-retrieval-details", open=False),
        ]), type="default", color=P["navy2"]),

        html.Div([
            _field(dcc.Dropdown(id="ia-global-mode", value=state.get("ia_global_mode", "native"), clearable=False, options=[{"label": label, "value": key} for key, label in GLOBAL_MODES.items()], style={"width": "245px"}), "Comparison mode"),
            _field(dcc.Dropdown(id="ia-chart-period", value=state.get("ia_chart_period", "10y"), clearable=False, options=CHART_OPTIONS, style={"width": "165px"}), "Chart Period"),
            html.Div([dcc.DatePickerRange(id="ia-chart-custom", start_date=state.get("ia_chart_start", f"{TODAY.year-10}-01-01"), end_date=state.get("ia_chart_end", TODAY.isoformat()), display_format="YYYY-MM-DD", minimum_nights=0)], id="ia-chart-custom-wrap", className="ia-date-wrap"),
            html.Div("Filters the chart and local statistics only; it does not fetch more data.", className="ia-control-help"),
        ], className="emd-controls ia-chart-controls"),

        dcc.Loading(html.Div([
            html.Div([html.Div([html.Div(id="ia-chart-title", className="emd-chart-title"), html.Div(id="ia-chart-subtitle", className="emd-chart-sub")], className="emd-chart-head"), dcc.Graph(id="ia-chart", config={"displayModeBar": True, "displaylogo": False}), html.Div(id="ia-chart-source", className="emd-chart-source")], className="emd-card ia-chart-panel"),
            html.Div([html.Div("Series Statistics", className="ia-section-title"), html.Div("Deterministic local calculations from each selected series transformation and Chart Period. Not source commentary or AI-generated prose.", className="ia-section-note"), html.Div(id="ia-statistics-table")], className="emd-card ia-section"),
            html.Details([html.Summary("View underlying data"), html.Div("Raw observations are supplied by the source. Series-transformed and chart values are calculated locally without interpolation or forward-filling.", className="ia-section-note"), html.Div(id="ia-data-table")], className="emd-es-details ia-data-details", open=False),
        ]), type="default", color=P["navy2"]),
        html.Details([html.Summary("Methodology and coverage"), html.Div(id="ia-methodology", className="ia-methodology")], className="emd-es-details ia-methodology-wrap", open=False),
    ])


def _frequency(item: dict[str, Any], excel_catalog, fred_catalog=None) -> str:
    return _definition_meta(item, excel_catalog, fred_catalog)["frequency"]


def unused_colour(configs: list[dict[str, Any]]) -> str:
    used = {row.get("colour") for row in configs or []}
    return next((colour for _name, colour in COLORS if colour not in used),
                COLORS[len(configs or []) % len(COLORS)][1])


def duplicate_colour_warning(configs: list[dict[str, Any]]) -> str:
    included = [row.get("colour") for row in configs or [] if row.get("included", True)]
    duplicates = sorted({colour for colour in included if included.count(colour) > 1 and colour})
    return (" · Duplicate colours in use; manual overrides are retained."
            if duplicates else "")


def _normalise_config(configs: list[dict[str, Any]], excel_catalog, fred_catalog=None) -> list[dict[str, Any]]:
    fred_catalog = list(fred_catalog or [])
    for existing in configs or []:
        definition = existing.get("fred_definition")
        if definition and not any(row.get("code") == definition.get("code") for row in fred_catalog):
            fred_catalog.append(definition)
    out = []
    for index, item in enumerate((configs or [])[:MAX_SERIES]):
        row = dict(item); row.setdefault("uid", _uid()); row.setdefault("included", True); row.setdefault("collapsed", False)
        row.setdefault("provider", "world_bank"); row.setdefault("geography", "USA"); row.setdefault("window", 5); row.setdefault("colour", COLORS[index % len(COLORS)][1])
        options = _provider_indicator_options(row["provider"], excel_catalog, fred_catalog)
        valid = {option["value"] for option in options}
        if row.get("indicator") not in valid: row["indicator"] = options[0]["value"] if options else ""
        meta = _definition_meta(row, excel_catalog, fred_catalog)
        if row.get("transform") not in valid_transforms(meta["frequency"], meta["semantic_type"]):
            row["transform"] = default_transform(meta["frequency"], meta["semantic_type"])
        out.append(row)
    return out


def mutate_series_config(configs: list[dict[str, Any]], operation: str,
                         uid: str | None = None, field: str | None = None,
                         value: Any = None, excel_catalog=None, fred_catalog=None) -> list[dict[str, Any]]:
    """Pure series-state reducer used by the Dash callback and automated tests."""
    rows = _normalise_config(copy.deepcopy(configs or []), excel_catalog or [], fred_catalog or [])
    if operation in ("collapse_all", "expand_all"):
        collapsed = operation == "collapse_all"
        return [dict(row, collapsed=collapsed) for row in rows]
    if operation == "add":
        if len(rows) < MAX_SERIES:
            rows.append(_new_series(colour=unused_colour(rows)))
        return rows
    pos = next((i for i, row in enumerate(rows) if row["uid"] == uid), None)
    if pos is None:
        return rows
    if operation == "collapse":
        rows[pos]["collapsed"] = not rows[pos].get("collapsed", False)
    elif operation == "delete":
        rows.pop(pos)
    elif operation == "duplicate" and len(rows) < MAX_SERIES:
        clone = copy.deepcopy(rows[pos]); clone["uid"] = _uid(); clone["collapsed"] = False
        clone["colour"] = unused_colour(rows)
        rows.insert(pos + 1, clone)
    elif operation == "up" and pos > 0:
        rows[pos - 1], rows[pos] = rows[pos], rows[pos - 1]
    elif operation == "down" and pos < len(rows) - 1:
        rows[pos + 1], rows[pos] = rows[pos], rows[pos + 1]
    elif operation == "set" and field:
        rows[pos][field] = value
        if field == "provider":
            options = _provider_indicator_options(str(value), excel_catalog or [], fred_catalog or [])
            rows[pos]["indicator"] = options[0]["value"] if options else ""
            meta = _definition_meta(rows[pos], excel_catalog or [], fred_catalog or [])
            rows[pos]["transform"] = default_transform(meta["frequency"], meta["semantic_type"])
            rows[pos]["geography"] = "USA" if value in ("world_bank", "imf_datamapper", "imf_sdmx") else ""
        elif field == "indicator":
            if rows[pos].get("provider") == "fred" and value not in FRED_INDICATORS:
                rows[pos]["fred_definition"] = next(
                    (dict(entry) for entry in (fred_catalog or []) if entry.get("code") == value),
                    rows[pos].get("fred_definition", {}))
            meta = _definition_meta(rows[pos], excel_catalog or [], fred_catalog or [])
            rows[pos]["transform"] = default_transform(meta["frequency"], meta["semantic_type"])
    return _normalise_config(rows, excel_catalog or [], fred_catalog or [])


def add_market_watch_to_series(configs: list[dict[str, Any]],
                               request: dict[str, Any], excel_catalog=None,
                               fred_catalog=None) -> list[dict[str, Any]]:
    """Add a watch instrument to IA, or focus the existing matching series."""
    rows = _normalise_config(copy.deepcopy(configs or []), excel_catalog or [],
                             fred_catalog or [])
    provider, indicator = request.get("provider"), request.get("indicator")
    existing = next((row for row in rows if row.get("provider") == provider and
                     row.get("indicator") == indicator), None)
    if existing:
        existing["included"] = True
        existing["collapsed"] = False
        return _normalise_config(rows, excel_catalog or [], fred_catalog or [])
    if len(rows) >= MAX_SERIES or indicator not in catalogue(str(provider)):
        return rows
    rows.append(_new_series(str(provider), str(request.get("geography") or "Market"),
                            str(indicator), unused_colour(rows), False))
    return _normalise_config(rows, excel_catalog or [], fred_catalog or [])


def _excel_options(path, sheet, table, fmt, mapping):
    return {"path": path or "", "sheet": sheet or "", "table": table or "", "format": fmt or "auto", "mapping_sheet": mapping or "Mapping"}


def _periods_per_year(frequency: str, index: pd.DatetimeIndex) -> int:
    freq = (frequency or "").lower()
    if "daily" in freq: return 252
    if "weekly" in freq: return 52
    if "monthly" in freq: return 12
    if "quarter" in freq: return 4
    if "annual" in freq or "year" in freq: return 1
    if len(index) > 2:
        gap = pd.Series(index).sort_values().diff().dt.days.median()
        if pd.notna(gap):
            if gap <= 3: return 252
            if gap <= 10: return 52
            if gap <= 45: return 12
            if gap <= 120: return 4
    return 1


def apply_series_transform(series: pd.Series, transform: str, frequency: str,
                           window: int = 5,
                           semantic_type: str = "raw_level") -> tuple[pd.Series, str]:
    values = pd.to_numeric(series, errors="coerce").dropna().sort_index(); unit = ""
    if values.empty: return values, unit
    allowed = valid_transforms(frequency, semantic_type)
    if transform not in allowed:
        raise ValueError(
            f"{TRANSFORM_LABELS.get(transform, transform)} is not valid for "
            f"{semantic_type} data at {frequency} frequency."
        )
    periods = _periods_per_year(frequency, pd.DatetimeIndex(values.index)); window = max(2, int(window or 5))
    if transform == "level": return values, "native"
    if transform == "diff": return values.diff(), "native"
    if transform == "pp_diff": return values.diff(), "percentage points"
    if transform in ("pop_pct", "mom"): return values.pct_change(1, fill_method=None) * 100, "%"
    if transform == "qoq": return values.pct_change(3 if periods == 12 else 1, fill_method=None) * 100, "%"
    if transform == "yoy": return values.pct_change(periods, fill_method=None) * 100, "%"
    if transform == "rolling_mean": return values.rolling(window, min_periods=window).mean(), "native"
    if transform == "rebase": return (values / values.iloc[0] * 100 if values.iloc[0] != 0 else values * np.nan), "Index"
    if transform == "rolling_zscore":
        mean = values.rolling(window, min_periods=window).mean(); std = values.rolling(window, min_periods=window).std(ddof=0).replace(0, np.nan)
        return (values - mean) / std, "Z-score"
    raise ValueError(f"Unsupported series transformation: {transform}")


def apply_global_mode(series: pd.Series, mode: str) -> pd.Series:
    values = series.dropna().sort_index()
    if values.empty or mode == "native": return values
    first = values.iloc[0]
    if mode == "indexed": return values / first * 100 if first != 0 else values * np.nan
    if mode == "pct_start": return (values / first - 1) * 100 if first != 0 else values * np.nan
    if mode == "standardised":
        std = values.std(ddof=0); return (values - values.mean()) / std if std and math.isfinite(std) else values * np.nan
    raise ValueError(f"Unsupported global comparison mode: {mode}")


def _frame(payload):
    rows = []
    for series in (payload or {}).get("series", []):
        meta = series.get("meta", {}); name = f"{meta.get('geography_label','')} — {meta.get('label',meta.get('series_code',''))}"
        for observation in series.get("records", []): rows.append({**observation, "uid": meta.get("request_id"), "series_name": name, **{key: meta.get(key) for key in ("provider_label","source","source_url","geography","geography_label","label","series_code","frequency","unit","semantic_type","retrieved_at","cache_status")}})
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce"); frame["value"] = pd.to_numeric(frame["value"], errors="coerce"); frame = frame.dropna(subset=["date","value"]).sort_values(["uid","date"])
    return frame


def _chart_bounds(mode, start, end, frame):
    if frame.empty or mode == "max": return None, None
    if mode == "custom": return pd.to_datetime(start, errors="coerce") if start else None, pd.to_datetime(end, errors="coerce") if end else None
    years = {"1y":1,"5y":5,"10y":10,"20y":20}.get(mode); hi = frame["date"].max(); return (hi-pd.DateOffset(years=years), hi) if years else (None,None)


def _analysis_series(frame, configs, global_mode, lo=None, hi=None):
    output = {}
    config_by_uid = {item["uid"]: item for item in configs or []}
    for uid, group in frame.groupby("uid", sort=False):
        config_row = config_by_uid.get(uid, {}); raw = group.sort_values("date").set_index("date")["value"]
        transformed, unit_type = apply_series_transform(
            raw, config_row.get("transform", "level"),
            str(group.iloc[0]["frequency"]),
            window=config_row.get("window", 5),
            semantic_type=str(group.iloc[0].get("semantic_type") or "raw_level"),
        )
        native_unit = str(group.iloc[0]["unit"]); transformed_unit = native_unit if unit_type == "native" else unit_type
        visible = transformed
        if lo is not None: visible = visible[visible.index >= lo]
        if hi is not None: visible = visible[visible.index <= hi]
        output[uid] = {"raw": raw, "series": visible, "chart": apply_global_mode(visible, global_mode), "unit": transformed_unit, "config": config_row, "meta": group.iloc[0].to_dict()}
    return output


def _empty_figure(message):
    fig=go.Figure(); fig.update_layout(template="plotly_white",height=500,font={"family":F["ui"],"color":P["ink"],"size":11},paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",margin={"l":80,"r":40,"t":45,"b":50}); fig.add_annotation(text=message,showarrow=False,font={"color":P["muted"]}); return fig


def scale_dominance_warning(analysis, global_mode: str, threshold: float = 100.0) -> str:
    if global_mode != "native":
        return ""
    by_unit: dict[str, list[tuple[str, float]]] = {}
    for item in analysis.values():
        values = item["chart"].dropna().abs()
        if values.empty:
            continue
        scale = float(values.quantile(.9))
        if scale > 0 and math.isfinite(scale):
            by_unit.setdefault(item["unit"], []).append((item["meta"]["series_name"], scale))
    warnings = []
    for unit, members in by_unit.items():
        scales = [scale for _name, scale in members]
        if len(scales) > 1 and max(scales) / min(scales) >= threshold:
            warnings.append(f"{unit}: largest series is {max(scales)/min(scales):,.0f}× the smallest")
    return ("Scale warning — " + "; ".join(warnings) +
            ". Smaller lines may be visually compressed; no mode was changed."
            if warnings else "")


def _build_chart(analysis, global_mode):
    live=[item for item in analysis.values() if not item["chart"].dropna().empty]
    if not live: return _empty_figure("No values remain after transformations and Chart Period filters."),"",""
    units=list(dict.fromkeys(item["unit"] for item in live)) if global_mode=="native" else [GLOBAL_MODES[global_mode]]
    if global_mode=="native" and len(units)>2: return _empty_figure("Native / Actual Values supports at most two transformed units. Select Indexed, Change from Chart Start, or Standardised."),"More than two units selected",""
    secondary=global_mode=="native" and len(units)==2; fig=make_subplots(specs=[[{"secondary_y":secondary}]])
    sources=[]
    for item in live:
        s=item["chart"].dropna(); meta=item["meta"]; cfg=item["config"]; use_secondary=secondary and item["unit"]==units[1]
        fig.add_trace(go.Scatter(x=s.index,y=s.values,name=meta["series_name"],mode="lines+markers" if len(s)<70 else "lines",line={"color":cfg.get("colour",P["navy2"]),"width":2},marker={"size":4},hovertemplate=f"{meta['series_name']}<br>%{{x|%Y-%m-%d}}<br>%{{y:,.3f}}<extra></extra>"),secondary_y=use_secondary)
        sources.append(f"{meta.get('provider_label')} · {meta.get('series_code')}")
    if global_mode=="native":
        fig.update_yaxes(title_text=units[0],secondary_y=False)
        if secondary: fig.update_yaxes(title_text=units[1],secondary_y=True,showgrid=False)
        subtitle="Native transformed values"+(" · left/right axes separate units" if secondary else "")
    else:
        fig.update_yaxes(title_text=GLOBAL_MODES[global_mode],secondary_y=False); subtitle=f"{GLOBAL_MODES[global_mode]} after each series transformation"
    scale_warning = scale_dominance_warning(analysis, global_mode)
    if scale_warning:
        subtitle += " · " + scale_warning
    fig.update_layout(template="plotly_white",height=520,hovermode="x unified",font={"family":F["ui"],"color":P["ink"],"size":11},paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",margin={"l":86,"r":86 if secondary else 32,"t":50,"b":52},legend={"orientation":"h","yanchor":"bottom","y":1.02,"x":0.5,"xanchor":"center"},xaxis={"showgrid":False,"showline":True,"linecolor":"#1A1A1A","ticks":"outside"})
    fig.update_yaxes(showgrid=True,gridcolor="#E6E9EF",zeroline=True,zerolinecolor="#C9CED8",showline=True,linecolor="#1A1A1A",ticks="outside",secondary_y=False)
    return fig,subtitle,"Sources: "+"; ".join(dict.fromkeys(sources))


def _fmt(value):
    try: value=float(value)
    except: return "—"
    if not math.isfinite(value): return "—"
    if abs(value)>=1e9:return f"{value/1e9:,.2f}bn"
    if abs(value)>=1e6:return f"{value/1e6:,.2f}m"
    return f"{value:,.3f}"


def format_context_value(value, unit: str, semantic_type: str = "raw_level") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    unit_low = str(unit or "").lower()
    if unit == "percentage points":
        return f"{number:,.2f} pp"
    if "bp" in unit_low or semantic_type == "spread":
        return f"{number:,.1f} bp"
    if unit == "%" or "%" in unit:
        return f"{number:,.2f}%"
    if "per " in unit_low and semantic_type == "price":
        return f"{number:,.4f}"
    if semantic_type in ("price", "index") or unit == "Index":
        return f"{number:,.2f}"
    if abs(number) >= 1e9:
        return f"{number/1e9:,.2f}bn"
    if abs(number) >= 1e6:
        return f"{number/1e6:,.2f}m"
    return f"{number:,.3f}"


def format_context_change(change, unit: str, semantic_type: str) -> str:
    if pd.isna(change):
        return "—"
    if unit == "percentage points" or unit == "%" or "%" in str(unit):
        return f"{float(change):+,.2f} pp"
    if "bp" in str(unit).lower() or semantic_type == "spread":
        return f"{float(change):+,.1f} bp"
    return ("+" if float(change) >= 0 else "") + format_context_value(
        change, unit, semantic_type)


def _stats(analysis):
    rows=[]
    for item in analysis.values():
        s=item["series"].dropna(); meta=item["meta"]; cfg=item["config"]
        if s.empty: continue
        latest=s.iloc[-1]; prior=s.iloc[-2] if len(s)>1 else np.nan
        semantic = str(meta.get("semantic_type") or "raw_level")
        transform = cfg.get("transform", "level")
        rows.append({
            "Series": meta["series_name"],
            "Value Basis": "Source level" if transform == "level" else "Transformed",
            "Transformation": TRANSFORM_LABELS.get(transform),
            "Unit": item["unit"],
            "Latest Date": s.index[-1].date().isoformat(),
            "Latest": format_context_value(latest, item["unit"], semantic),
            "Previous": format_context_value(prior, item["unit"], semantic),
            "Change": format_context_change(latest-prior, item["unit"], semantic)
                      if not pd.isna(prior) else "—",
            "Mean": format_context_value(s.mean(), item["unit"], semantic),
            "Min": format_context_value(s.min(), item["unit"], semantic),
            "Max": format_context_value(s.max(), item["unit"], semantic),
            "Observations": len(s),
        })
    return rows


def _table(rows,page_size=10):
    if not rows:return html.Div("No rows to display.",className="ia-empty-table")
    return dash_table.DataTable(data=rows,columns=[{"name":key,"id":key} for key in rows[0]],sort_action="native",page_size=page_size,style_as_list_view=True,style_header={"fontWeight":700,"backgroundColor":"#F3F5F8","color":P["ink"],"border":"none","borderBottom":"1px solid #DFE2E8"},style_cell={"fontFamily":F["ui"],"fontSize":11,"padding":"8px 7px","border":"none","borderBottom":"1px solid #EEF0F4","textAlign":"right","minWidth":"80px","maxWidth":"230px","whiteSpace":"normal"},style_cell_conditional=[{"if":{"column_id":"Series"},"textAlign":"left","minWidth":"220px"},{"if":{"column_id":"Source"},"textAlign":"left"}])


def _diagnostic_text(payload):
    blocks=[]
    for error in (payload or {}).get("errors",[]):
        blocks.append(json.dumps({"error":error.get("message"),"diagnostic":error.get("diagnostic")},indent=2,ensure_ascii=False))
    for series in (payload or {}).get("series",[]):
        meta=series.get("meta",{}); diag=meta.get("live_error_diagnostic") or meta.get("diagnostic")
        if diag: blocks.append(json.dumps({"series":meta.get("series_code"),"status":meta.get("cache_status"),"diagnostic":diag},indent=2,ensure_ascii=False))
    return "\n\n".join(blocks)


def register(app):
    @app.callback(
        Output("mw-island-body", "children"), Output("mw-island-body", "style"),
        Output("mw-count", "children"), Output("mw-toggle", "children"),
        Input("mw-config", "data"), Input("mw-data", "data"))
    def _render_market_watch(config_value, data):
        config_value = _normalise_market_watch(config_value)
        count = len(config_value["instruments"])
        style = {"display": "none"} if config_value["collapsed"] else {}
        return (_market_watch_body(config_value, data or {}), style,
                "",
                "▸" if config_value["collapsed"] else "▾")

    @app.callback(
        Output("mw-config", "data"),
        Input("mw-toggle", "n_clicks"), Input("mw-add-instrument", "n_clicks"),
        Input("mw-add-group-button", "n_clicks"),
        Input({"type": "mw-group-action", "uid": ALL, "action": ALL}, "n_clicks"),
        Input({"type": "mw-instrument-action", "uid": ALL, "action": ALL}, "n_clicks"),
        Input({"type": "mw-instrument-group", "uid": ALL}, "value"),
        State({"type": "mw-group-action", "uid": ALL, "action": ALL}, "id"),
        State({"type": "mw-instrument-action", "uid": ALL, "action": ALL}, "id"),
        State({"type": "mw-instrument-group", "uid": ALL}, "id"),
        State("mw-config", "data"), State("mw-add-provider", "value"),
        State("mw-add-indicator", "value"), State("mw-add-group", "value"),
        State("mw-new-group-name", "value"), prevent_initial_call=True)
    def _update_market_watch(_toggle, _add, _add_group, group_clicks,
                             instrument_clicks, group_values, group_action_ids,
                             instrument_action_ids, group_field_ids, config_value,
                             provider, indicator, group_uid, group_name):
        state = _normalise_market_watch(config_value)
        trig = ctx.triggered_id
        if trig == "mw-toggle" and _toggle:
            return mutate_market_watch(state, "toggle_outer")
        if trig == "mw-add-instrument" and _add:
            updated = mutate_market_watch(
                state, "add_instrument", payload={"provider": provider,
                "indicator": indicator, "group_uid": group_uid})
            return updated if updated != state else no_update
        if trig == "mw-add-group-button" and _add_group:
            updated = mutate_market_watch(state, "add_group", payload=group_name)
            return updated if updated != state else no_update
        if isinstance(trig, dict) and trig.get("type") == "mw-group-action":
            clicks = {json.dumps(item, sort_keys=True): count for item, count in
                      zip(group_action_ids or [], group_clicks or [])}
            if not clicks.get(json.dumps(trig, sort_keys=True)):
                return no_update
            updated = mutate_market_watch(state, f"group_{trig.get('action')}",
                                          uid=trig.get("uid"))
            return updated if updated != state else no_update
        if isinstance(trig, dict) and trig.get("type") == "mw-instrument-action":
            clicks = {json.dumps(item, sort_keys=True): count for item, count in
                      zip(instrument_action_ids or [], instrument_clicks or [])}
            if not clicks.get(json.dumps(trig, sort_keys=True)):
                return no_update
            updated = mutate_market_watch(state,
                f"instrument_{trig.get('action')}", uid=trig.get("uid"))
            return updated if updated != state else no_update
        if isinstance(trig, dict) and trig.get("type") == "mw-instrument-group":
            values = {json.dumps(item, sort_keys=True): value for item, value in
                      zip(group_field_ids or [], group_values or [])}
            updated = mutate_market_watch(state, "instrument_group",
                                          uid=trig.get("uid"),
                                          payload=values.get(json.dumps(trig, sort_keys=True)))
            return updated if updated != state else no_update
        return no_update

    @app.callback(
        Output("mw-data", "data"), Output("mw-status", "children"),
        Output("mw-status", "className"),
        Input("mw-refresh", "n_clicks"), Input("mw-config", "data"),
        prevent_initial_call=False)
    def _retrieve_market_watch(_clicks, config_value):
        config_value = _normalise_market_watch(config_value)
        force = ctx.triggered_id == "mw-refresh"
        try:
            payload = MARKET_WATCH_SERVICE.fetch(config_value["instruments"], force=force)
        except Exception as exc:
            payload = {"instruments": [], "errors": [{"message": str(exc)}]}
        loaded = len(payload.get("instruments", []))
        errors = len(payload.get("errors", []))
        stale = sum(row.get("freshness_tone") == "stale"
                    for row in payload.get("instruments", []))
        delayed = sum(row.get("freshness_tone") == "delayed"
                      for row in payload.get("instruments", []))
        issues = []
        if delayed:
            issues.append(f"{delayed} delayed")
        if stale:
            issues.append(f"{stale} stale")
        if errors:
            issues.append(f"{errors} unavailable")
        text = " · ".join(issues)
        class_name = "mw-status mw-status--error" if not loaded and errors else (
            "mw-status mw-status--warning" if issues else "mw-status mw-status--quiet")
        return payload, text, class_name

    @app.callback(
        Output("mw-chart-request", "data"), Output("mw-chart-status", "children"),
        Input({"type": "mw-chart", "uid": ALL}, "n_clicks"),
        State({"type": "mw-chart", "uid": ALL}, "id"),
        State("mw-config", "data"), State("ia-series-config", "data"),
        prevent_initial_call=True)
    def _request_market_watch_chart(clicks, ids, config_value, series_config):
        trig = ctx.triggered_id
        if not isinstance(trig, dict):
            return no_update, no_update
        clicks_by_id = {json.dumps(item, sort_keys=True): count for item, count in
                        zip(ids or [], clicks or [])}
        if not clicks_by_id.get(json.dumps(trig, sort_keys=True)):
            return no_update, no_update
        item = next((row for row in _normalise_market_watch(config_value)["instruments"]
                     if row["uid"] == trig.get("uid")), None)
        if not item:
            return no_update, "Instrument is no longer on the watch list."
        existing = any(row.get("provider") == item["provider"] and
                       row.get("indicator") == item["indicator"]
                       for row in (series_config or []))
        if not existing and len(series_config or []) >= MAX_SERIES:
            return no_update, f"Indicator Analysis already has {MAX_SERIES} series; remove one first."
        request = {**item, "requested_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        message = (f"Focused {item['indicator']} in Indicator Analysis." if existing else
                   f"Added {item['indicator']} to Indicator Analysis.")
        return request, message

    @app.callback(Output("ia-series-list","children"),Output("ia-series-count","children"),Output("ia-add-series","disabled"),Input("ia-series-config","data"),Input("ia-excel-catalog","data"),Input("ia-fred-catalog","data"))
    def _render_series(configs,excel_catalog,fred_catalog):
        configs=_normalise_config(configs or [],excel_catalog or [],fred_catalog or []); return [_series_card(item,i,excel_catalog or [],fred_catalog or []) for i,item in enumerate(configs)],f"{len(configs)} / {MAX_SERIES} series{duplicate_colour_warning(configs)}",len(configs)>=MAX_SERIES

    @app.callback(Output("ia-series-config","data"),Input("ia-add-series","n_clicks"),Input("ia-collapse-all","n_clicks"),Input("ia-expand-all","n_clicks"),Input({"type":"ia-action","uid":ALL,"action":ALL},"n_clicks"),Input({"type":"ia-field","uid":ALL,"field":ALL},"value"),Input("mw-chart-request","data"),State({"type":"ia-action","uid":ALL,"action":ALL},"id"),State({"type":"ia-field","uid":ALL,"field":ALL},"id"),State("ia-series-config","data"),State("ia-excel-catalog","data"),State("ia-fred-catalog","data"),prevent_initial_call=True)
    def _update_config(_add,_collapse_all,_expand_all,_actions,field_values,mw_chart_request,action_ids,field_ids,configs,excel_catalog,fred_catalog):
        configs=_normalise_config(configs or [],excel_catalog or [],fred_catalog or []); trig=ctx.triggered_id
        if trig=="mw-chart-request" and mw_chart_request:
            updated=add_market_watch_to_series(configs,mw_chart_request,excel_catalog,fred_catalog)
            return updated if updated!=configs else no_update
        if trig=="ia-add-series":
            if not _add:return no_update
            updated=mutate_series_config(configs,"add",excel_catalog=excel_catalog,fred_catalog=fred_catalog)
            return updated if len(updated)!=len(configs) else no_update
        if trig in ("ia-collapse-all", "ia-expand-all"):
            collapsed = trig == "ia-collapse-all"
            updated = [dict(row, collapsed=collapsed) for row in configs]
            return updated if updated != configs else no_update
        if isinstance(trig,dict) and trig.get("type")=="ia-action":
            uid,action=trig.get("uid"),trig.get("action"); pos=next((i for i,row in enumerate(configs) if row["uid"]==uid),None)
            if pos is None:return no_update
            clicks_by_id={json.dumps(aid,sort_keys=True):clicks for aid,clicks in zip(action_ids or [],_actions or [])}
            if not clicks_by_id.get(json.dumps(trig,sort_keys=True)):return no_update
            updated=mutate_series_config(configs,action,uid=uid,excel_catalog=excel_catalog,fred_catalog=fred_catalog)
            return updated if updated!=configs else no_update
        if isinstance(trig,dict) and trig.get("type")=="ia-field":
            uid,field=trig.get("uid"),trig.get("field"); values_by_id={json.dumps(fid,sort_keys=True):value for fid,value in zip(field_ids or [],field_values or [])}; key=json.dumps(trig,sort_keys=True); value=values_by_id.get(key)
            row=next((item for item in configs if item["uid"]==uid),None)
            if row is None:return no_update
            new_value=("on" in (value or [])) if field=="included" else value
            if row.get(field)==new_value:return no_update
            return mutate_series_config(configs,"set",uid=uid,field=field,value=new_value,excel_catalog=excel_catalog,fred_catalog=fred_catalog)
        return no_update

    @app.callback(Output("ia-excel-catalog","data"),Output("ia-excel-status","children"),Input("ia-excel-load","n_clicks"),State("ia-excel-path","value"),State("ia-excel-sheet","value"),State("ia-excel-table","value"),State("ia-excel-format","value"),State("ia-excel-mapping","value"),prevent_initial_call=True)
    def _load_excel(_clicks,path,sheet,table,fmt,mapping):
        try:
            catalog,diag=GembridgeExcelProvider.discover(path,sheet,table,fmt,mapping); return catalog,f"{diag.message} Available series: {', '.join(diag.available_series[:12])}"
        except Exception as exc:return [],f"Excel validation failed: {exc}"

    @app.callback(Output("ia-fred-catalog","data"),Output("ia-fred-search-status","children"),Input("ia-fred-search","n_clicks"),State("ia-fred-search-text","value"),prevent_initial_call=True)
    def _search_fred(_clicks,search_text):
        if not str(search_text or "").strip():
            return [], "Enter FRED search text."
        try:
            results, diagnostic = SERVICE.search_fred(str(search_text).strip(), 20)
            return results, f"{diagnostic.message} Results are now available in FRED series dropdowns."
        except Exception as exc:
            return [], f"FRED search unavailable: {exc}"

    @app.callback(Output("ia-source-test-output","value"),Input("ia-run-source-test","n_clicks"),State("ia-test-provider","value"),State("ia-series-config","data"),State("ia-fetch-mode","value"),State("ia-fetch-custom","start_date"),State("ia-fetch-custom","end_date"),State("ia-excel-path","value"),State("ia-excel-sheet","value"),State("ia-excel-table","value"),State("ia-excel-format","value"),State("ia-excel-mapping","value"),State("ia-fred-catalog","data"),prevent_initial_call=True)
    def _source_test(_clicks,provider,configs,fetch_mode,start,end,path,sheet,table,fmt,mapping,fred_catalog):
        configs=configs or []; row=next((item for item in configs if item.get("provider")==provider),None)
        defaults={"world_bank":("USA","NY.GDP.MKTP.KD.ZG"),"imf_datamapper":("USA","NGDP_RPCH"),"imf_sdmx":("USA","CPI_ALL_ITEMS_INDEX_M"),"fred":("USA","DGS10"),"yahoo_market":("Market","BRENT"),"gembridge_excel":("","")}; geography,indicator=defaults.get(provider,("",""))
        if row:geography,indicator=row.get("geography",geography),row.get("indicator",indicator)
        options=_excel_options(path,sheet,table,fmt,mapping) if provider=="gembridge_excel" else {}
        if provider=="fred" and row and row.get("fred_definition"):
            options={"fred_definition":row["fred_definition"]}
        diagnostic=SERVICE.test_source(SeriesRequest("test",provider,geography,indicator,options),HistoryWindow(fetch_mode or "5y",start,end))
        return json.dumps(diagnostic,indent=2,ensure_ascii=False)

    @app.callback(Output("ia-fetch-custom-wrap","style"),Input("ia-fetch-mode","value"))
    def _fetch_custom(mode):return {} if mode=="custom" else {"display":"none"}
    @app.callback(Output("ia-chart-custom-wrap","style"),Input("ia-chart-period","value"))
    def _chart_custom(mode):return {} if mode=="custom" else {"display":"none"}

    @app.callback(Output("ia-data-store","data"),Output("ia-status","children"),Output("ia-status","className"),Output("ia-retrieval-details","children"),Output("ia-retrieval-diagnostic-copy","value"),Input("ia-refresh","n_clicks"),Input("ia-series-config","data"),Input("ia-fetch-mode","value"),Input("ia-fetch-custom","start_date"),Input("ia-fetch-custom","end_date"),State("ia-excel-path","value"),State("ia-excel-sheet","value"),State("ia-excel-table","value"),State("ia-excel-format","value"),State("ia-excel-mapping","value"),prevent_initial_call=False)
    def _retrieve(_clicks,configs,mode,start,end,path,sheet,table,fmt,mapping):
        excel_options=_excel_options(path,sheet,table,fmt,mapping); requests=[]
        for item in configs or []:
            if item.get("included") and item.get("indicator"):
                provider=item.get("provider"); options={}
                if provider=="gembridge_excel": options=excel_options
                if provider=="fred" and item.get("fred_definition"): options={"fred_definition":item["fred_definition"]}
                geography=item.get("geography","") or ("Market" if provider=="yahoo_market" else ("USA" if provider=="fred" else ""))
                requests.append(SeriesRequest(item["uid"],provider,geography,item.get("indicator"),options))
        try:payload=SERVICE.fetch_many(requests,HistoryWindow(mode or "20y",start,end),force=ctx.triggered_id=="ia-refresh")
        except Exception as exc:payload={"series":[],"errors":[{"request_id":"","message":str(exc)}]}
        successes=len(payload.get("series",[])); errors=payload.get("errors",[]); stale=sum(s.get("meta",{}).get("cache_status")=="stale cache" for s in payload.get("series",[]))
        statuses=[s.get("meta",{}).get("cache_status","") for s in payload.get("series",[])]; status=f"{successes} loaded"+(f" · {statuses.count('live')} live · {statuses.count('fresh cache')} cached" if successes else "")+(f" · {stale} stale" if stale else "")+(f" · {len(errors)} failed" if errors else "")
        cls="ia-status ia-status--error" if not successes else ("ia-status ia-status--warning" if errors or stale else "ia-status ia-status--ok")
        detail_rows=[]
        for s in payload.get("series",[]):
            m=s["meta"]; detail_rows.append({"Series":f"{m.get('geography_label')} — {m.get('label')}","Source":m.get("provider_label"),"Code":m.get("series_code"),"Frequency":m.get("frequency"),"Unit":m.get("unit"),"Latest":f"{m.get('latest_period')} · {_fmt(m.get('latest_value'))}","Retrieved":str(m.get("retrieved_at","")).replace("T"," ").replace("Z"," UTC"),"Status":m.get("cache_status")})
        return payload,status,cls,_table(detail_rows,MAX_SERIES),_diagnostic_text(payload)

    @app.callback(Output("ia-chart","figure"),Output("ia-chart-title","children"),Output("ia-chart-subtitle","children"),Output("ia-chart-source","children"),Output("ia-statistics-table","children"),Output("ia-data-table","children"),Output("ia-methodology","children"),Input("ia-data-store","data"),Input("ia-series-config","data"),Input("ia-global-mode","value"),Input("ia-chart-period","value"),Input("ia-chart-custom","start_date"),Input("ia-chart-custom","end_date"))
    def _render(payload,configs,global_mode,period,start,end):
        frame=_frame(payload or {}); configs=configs or []
        if frame.empty:
            msg="No observations loaded. Use Retrieval details or Data Source Test for diagnostics."; return _empty_figure(msg),"Series comparison","","",html.Div(msg),html.Div(msg),html.Div()
        lo,hi=_chart_bounds(period or "10y",start,end,frame); analysis=_analysis_series(frame,configs,global_mode or "native",lo,hi); fig,subtitle,source=_build_chart(analysis,global_mode or "native")
        rows=[]
        for uid,item in analysis.items():
            meta=item["meta"]; raw=item["raw"]; transformed=item["series"]; chart=item["chart"]
            for date,value in raw.sort_index(ascending=False).items():
                if lo is not None and date<lo:continue
                if hi is not None and date>hi:continue
                rows.append({"Series":meta["series_name"],"Date":date.date().isoformat(),"Raw Value":_fmt(value),"Raw Unit":meta.get("unit"),"Series Transform":TRANSFORM_LABELS.get(item["config"].get("transform","level")),"Transformed":_fmt(transformed.get(date,np.nan)),"Chart Value":_fmt(chart.get(date,np.nan)),"Source":meta.get("provider_label"),"Code":meta.get("series_code")})
        methodology=html.Div([html.P("Fetch History controls provider requests and cache keys. Chart Period filters locally after each per-series transformation."),html.P("Per-series transformations are frequency-aware. Native observations are never interpolated or forward-filled. Rolling windows are measured in observations."),html.P("Native mode supports up to two transformed units using separate axes. Normalised comparison modes are applied after per-series transformations."),html.P("Implemented coverage: curated World Bank WDI; curated annual IMF headline macro series through DataMapper; IMF monthly all-items CPI through SDMX 3.0; curated and searched FRED series when an API key is configured; curated Yahoo chart-market series; Gembridge Excel long/wide format. DataMapper complements rather than replaces SDMX, and coverage is not presented as complete for any provider."),html.P("Series Statistics are deterministic local calculations, not source commentary or AI-generated prose.")])
        return fig,"Series comparison",subtitle,source,_table(_stats(analysis),MAX_SERIES),_table(rows,20),methodology
