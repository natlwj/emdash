"""Collapsible Indicator Analysis source catalogue for Data Coverage & Updates.

This is a provider catalogue and availability view—not a cache browser. It may
use successfully retrieved observation files internally to enrich individual
catalogue rows with truthful coverage dates, but it never enumerates those files
and never reads or writes emdash.sqlite.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from dash import html

import config
from indicator_providers import (
    FRED_API_KEY, FRED_INDICATORS, GembridgeExcelProvider,
    IMF_DATAMAPPER_INDICATORS, IMF_INDICATORS, MARKET_INDICATORS,
    PROVIDER_LABELS, SERVICE, WORLD_BANK_INDICATORS,
)


P = config.PALETTE
UTC = dt.timezone.utc
MAINTENANCE_START = dt.datetime(2026, 10, 24, 6, 0, tzinfo=UTC)
MAINTENANCE_END = dt.datetime(2026, 10, 26, 13, 0, tzinfo=UTC)

PROVIDER_PROFILES = {
    "world_bank": {
        "description": "Cross-country development and macroeconomic data from World Development Indicators.",
        "type": "Live API", "universe": "Broad WDI cross-country indicator catalogue",
        "emdash_scope": "13 curated EMDASH indicators",
    },
    "imf_datamapper": {
        "description": "Headline IMF macro and WEO-style annual country series through the simple DataMapper JSON route.",
        "type": "Live API", "universe": "Multiple IMF DataMapper datasets and country series",
        "emdash_scope": "7 curated annual headline indicators",
    },
    "imf_sdmx": {
        "description": "Multidimensional IMF SDMX service for richer statistical datasets and frequencies.",
        "type": "Live API", "universe": "Richer multidimensional IMF statistical dataflows",
        "emdash_scope": "1 tested monthly all-items CPI route",
    },
    "fred": {
        "description": "St. Louis Fed economic and financial database for US rates, spreads, conditions, macro and Fed balance-sheet data.",
        "type": "Live API · key required", "universe": "Large FRED economic and financial series database",
        "emdash_scope": "19 curated series plus additional-series search",
    },
    "yahoo_market": {
        "description": "Public historical market-price adapter for selected commodities, FX, equity indices and crypto.",
        "type": "Live API", "universe": "Public Yahoo Finance chart-ticker universe",
        "emdash_scope": "15 curated EMDASH instruments",
    },
    "gembridge_excel": {
        "description": "Internal workbook bridge for CDS, sovereign auctions and other proprietary or manually maintained series.",
        "type": "Workbook / internal", "universe": "Configured workbook tables/sheets",
        "emdash_scope": "Discovered series in the configured workbook",
    },
}

WB_CATEGORY = {
    "NY.GDP.MKTP.KD.ZG": "Growth", "FP.CPI.TOTL.ZG": "Inflation",
    "BN.CAB.XOKA.GD.ZS": "External", "GC.DOD.TOTL.GD.ZS": "Debt",
    "SL.UEM.TOTL.ZS": "Labour", "NE.EXP.GNFS.ZS": "Trade",
    "NE.IMP.GNFS.ZS": "Trade", "BX.KLT.DINV.WD.GD.ZS": "FDI",
    "FI.RES.TOTL.CD": "Reserves", "NY.GDP.PCAP.CD": "Income",
    "NY.GNS.ICTR.ZS": "Savings", "FM.LBL.BMNY.GD.ZS": "Money",
    "SP.POP.TOTL": "Population",
}
IMF_DM_CATEGORY = {
    "NGDP_RPCH": "Growth", "PCPIPCH": "Inflation", "BCA": "External",
    "BCA_NGDPD": "External", "LUR": "Labour",
    "GGXCNL_NGDP": "Fiscal", "GGXWDG_NGDP": "Debt",
}
FRED_CATEGORY = {
    "DFF": "Policy rate", "DGS2": "Treasury rates", "DGS10": "Treasury rates",
    "DGS30": "Treasury rates", "T10Y2Y": "Curve spreads", "T10Y3M": "Curve spreads",
    "DFII10": "Real rates", "BAMLC0A0CM": "Credit spreads",
    "BAMLH0A0HYM2": "Credit spreads", "BAMLEMCBPIOAS": "Credit spreads",
    "VIXCLS": "Volatility", "NFCI": "Financial conditions",
    "STLFSI4": "Financial conditions", "CPIAUCSL": "Inflation",
    "UNRATE": "Labour", "PAYEMS": "Labour", "INDPRO": "Production",
    "GDPC1": "Growth", "WALCL": "Fed balance sheet",
}


def maintenance_active(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return MAINTENANCE_START <= now <= MAINTENANCE_END


def _excel_status(state: dict[str, Any]) -> tuple[str, str]:
    raw = str((state or {}).get("ia_excel_path") or "").strip()
    if not raw:
        return "Workbook not configured", "muted"
    return (("Configured", "good") if Path(raw).expanduser().exists()
            else ("Workbook path not found", "bad"))


def _default_status(provider: str, state: dict[str, Any], now: dt.datetime,
                    fred_key: str) -> tuple[str, str]:
    if provider == "fred":
        return (("Configured", "good") if fred_key
                else ("API key required / not configured", "muted"))
    if provider == "gembridge_excel":
        return _excel_status(state)
    if provider == "imf_sdmx" and maintenance_active(now):
        return "Temporary maintenance / unavailable", "warn"
    return "Available · no key required", "good"


def _registry_status(entry: dict[str, Any], fallback: tuple[str, str]) -> tuple[str, str, str]:
    if not entry:
        return fallback[0], fallback[1], ""
    availability = str(entry.get("availability") or "")
    tested = str(entry.get("tested_at") or "")
    status = str(entry.get("http_status") or "")
    if availability == "available":
        return "Available · source test passed", "good", tested
    if availability == "not configured":
        return "API key required / not configured", "muted", tested
    if status == "403":
        return "Blocked / unavailable", "bad", tested
    if status == "503":
        return "Temporary maintenance / unavailable", "warn", tested
    if availability == "temporarily unavailable":
        return "Temporarily unavailable", "warn", tested
    if availability == "error":
        return "Source test error", "bad", tested
    return fallback[0], fallback[1], tested


def _observation_metadata(cache_root: Path | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    """Aggregate dates/geographies internally by provider+code; never render files."""
    root = cache_root or SERVICE.cache.root
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not root.exists():
        return out
    for path in root.glob("*.json"):
        if path.name == "provider_status.json":
            continue
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            meta, records = body.get("meta") or {}, body.get("records") or []
            provider, code = meta.get("provider"), meta.get("series_code")
            dates = sorted(str(row.get("date"))[:10] for row in records if row.get("date"))
            if not provider or not code or not dates:
                continue
            key = (provider, code)
            item = out.setdefault(key, {"first": dates[0], "last": dates[-1],
                                        "geographies": set(), "last_updated": ""})
            item["first"] = min(item["first"], dates[0]); item["last"] = max(item["last"], dates[-1])
            geography = meta.get("geography_label") or meta.get("geography")
            if geography: item["geographies"].add(str(geography))
            item["last_updated"] = max(item["last_updated"], str(meta.get("retrieved_at") or ""))
        except (OSError, ValueError, TypeError):
            continue
    for item in out.values():
        item["geographies"] = sorted(item["geographies"])
    return out


def _coverage_dates(provider: str, code: str, observed: dict[tuple[str, str], dict[str, Any]],
                    definition: dict[str, Any] | None = None) -> tuple[str, str, str]:
    item = observed.get((provider, code))
    if item:
        geo = ", ".join(item.get("geographies", [])[:3])
        return item["first"], item["last"], geo or "Retrieved selection"
    if definition:
        start, end = definition.get("observation_start"), definition.get("observation_end")
        if start or end:
            return start or "Not yet queried", end or "Not yet queried", definition.get("geography", "")
    return "Not yet queried", "Not yet queried", ""


def _row(provider: str, definition, category: str, observed, *, code: str | None = None,
         geography: str = "", note: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    series_code = code or definition.code
    first, last, observed_geo = _coverage_dates(provider, series_code, observed, metadata)
    observed_item = observed.get((provider, series_code), {})
    return {
        "label": definition.label, "code": series_code, "category": category,
        "unit": definition.unit, "frequency": definition.frequency,
        "geography": observed_geo or geography,
        "first": first, "last": last,
        "note": note or definition.description,
        "last_updated": ((metadata or {}).get("last_updated") or
                         observed_item.get("last_updated") or "Not yet queried"),
    }


def _excel_rows(state: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    path = str(state.get("ia_excel_path") or "").strip()
    if not path:
        return [], ("No workbook configured. Accepted long-format columns: date, series_id, value, "
                    "unit, frequency, source, geography, label. Supported frequencies include "
                    "Daily, Weekly, Monthly, Quarterly, Annual, Event and Irregular.")
    try:
        catalogue, _diag = GembridgeExcelProvider.discover(
            path, state.get("ia_excel_sheet", "Data_Long"),
            state.get("ia_excel_table", "GembridgeSeries"),
            state.get("ia_excel_format", "auto"), state.get("ia_excel_mapping", "Mapping"))
    except Exception as exc:
        return [], f"Workbook configured but catalogue could not be read: {exc}"
    rows = []
    for item in catalogue:
        rows.append({"label": item.get("label") or item["series_id"], "code": item["series_id"],
                     "category": "Internal / workbook", "unit": item.get("unit") or "Unspecified",
                     "frequency": item.get("frequency") or "Irregular",
                     "geography": item.get("geography") or "—",
                     "first": item.get("first") or "Not yet queried",
                     "last": item.get("last") or "Not yet queried",
                     "note": f"Source: {item.get('source') or 'Gembridge Excel'}",
                     "last_updated": "Not yet queried"})
    return rows, ""


def _catalogues(state: dict[str, Any], observed) -> dict[str, tuple[list[dict[str, Any]], str]]:
    wb = [_row("world_bank", definition, WB_CATEGORY[code], observed, geography="Cross-country",
               note=f"{definition.description} Country coverage varies by source reporting.")
          for code, definition in WORLD_BANK_INDICATORS.items()]
    dm = [_row("imf_datamapper", definition, IMF_DM_CATEGORY[code], observed,
               geography="Country series") for code, definition in IMF_DATAMAPPER_INDICATORS.items()]
    sdmx = [_row("imf_sdmx", definition, "Prices", observed, geography="Country series",
                 note="Monthly all-items CPI index. SDMX supports richer multidimensional IMF datasets; EMDASH currently exposes only this tested CPI route.")
            for definition in IMF_INDICATORS.values()]
    fred = [_row("fred", definition, FRED_CATEGORY[code], observed, geography="United States")
            for code, definition in FRED_INDICATORS.items()]
    # Persisted searched FRED cards are part of the current EMDASH-exposed catalogue.
    for card in state.get("ia_series_config", []) if isinstance(state.get("ia_series_config"), list) else []:
        fd = card.get("fred_definition") if card.get("provider") == "fred" else None
        if fd and fd.get("code") not in {row["code"] for row in fred}:
            class Obj: pass
            obj = Obj(); obj.code=fd["code"]; obj.label=fd.get("label") or fd["code"]
            obj.unit=fd.get("unit") or "Unspecified"; obj.frequency=fd.get("frequency") or "Irregular"
            obj.description=fd.get("description") or "Additional FRED series selected through search."
            fred.append(_row("fred", obj, "Additional search result", observed, geography="United States", metadata=fd))
    yahoo = [_row("yahoo_market", definition, definition.asset or "Market", observed,
                  geography=definition.asset or "Market",
                  note=(definition.description + " Public historical chart adapter; not an institutionally supported market-data feed."))
             for definition in MARKET_INDICATORS.values()]
    excel_rows, excel_empty = _excel_rows(state)
    return {"world_bank": (wb, ""), "imf_datamapper": (dm, ""),
            "imf_sdmx": (sdmx, ""), "fred": (fred, ""),
            "yahoo_market": (yahoo, ""), "gembridge_excel": (excel_rows, excel_empty)}


def coverage_snapshot(status_registry: dict[str, Any] | None = None,
                      state: dict[str, Any] | None = None,
                      now: dt.datetime | None = None,
                      fred_key: str | None = None,
                      observation_metadata: dict[tuple[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    state, now = state or {}, now or dt.datetime.now(UTC)
    registry = SERVICE.status.read() if status_registry is None else status_registry
    key = FRED_API_KEY if fred_key is None else fred_key
    observed = _observation_metadata() if observation_metadata is None else observation_metadata
    catalogues = _catalogues(state, observed)
    providers = []
    for provider, profile in PROVIDER_PROFILES.items():
        fallback = _default_status(provider, state, now, key)
        status, tone, tested = _registry_status(registry.get(provider, {}), fallback)
        rows, empty = catalogues[provider]
        providers.append({"key": provider, "label": PROVIDER_LABELS[provider], **profile,
                          "status": status, "tone": tone, "tested_at": tested,
                          "catalogue": rows, "empty_message": empty})
    return {"providers": providers}


def _tone_style(tone: str) -> dict[str, str]:
    palette = {"good": {"color": P["good"], "background": "#E4F0E6"},
               "warn": {"color": "#8A6D1B", "background": "#FBF3E2"},
               "bad": {"color": P["bad"], "background": "#F7E4E1"},
               "muted": {"color": P["muted"], "background": "#EEF0F4"}}
    return {**palette.get(tone, palette["muted"]), "fontSize": "10px", "fontWeight": 700,
            "padding": "2px 7px", "borderRadius": "6px", "whiteSpace": "nowrap"}


def _catalogue_table(rows: list[dict[str, Any]], empty_message: str):
    if not rows:
        return html.Div(empty_message or "No EMDASH-exposed series are currently configured.",
                        className="ia-cov-empty")
    headers = ["Series", "Code / ticker", "Category", "Unit", "Frequency",
               "Geography / asset", "Earliest", "Latest", "Metadata / retrieved",
               "Source / methodology note"]
    body = []
    for row in rows:
        body.append(html.Tr([
            html.Td(row["label"], style={"fontWeight": 600, "color": P["ink"]}),
            html.Td(row["code"], style={"fontFamily": "Consolas, monospace", "whiteSpace": "nowrap"}),
            html.Td(row["category"]), html.Td(row["unit"]), html.Td(row["frequency"]),
            html.Td(row.get("geography") or "—"),
            html.Td(row["first"], style={"whiteSpace": "nowrap"}),
            html.Td(row["last"], style={"whiteSpace": "nowrap"}),
            html.Td(str(row.get("last_updated") or "Not yet queried").replace("T", " ").replace("Z", " UTC"),
                    style={"whiteSpace": "nowrap"}),
            html.Td(row["note"], style={"minWidth": "260px"}),
        ]))
    return html.Div(html.Table([html.Thead(html.Tr([html.Th(h) for h in headers])),
                                html.Tbody(body)], className="emd-table ia-cov-table"),
                    className="ia-cov-table-wrap")


def provider_detail(item: dict[str, Any]):
    summary = html.Div([
        html.Span("▸", className="ia-cov-chevron", **{"aria-hidden": "true"}),
        html.Div([html.Div(item["label"], className="ia-cov-provider"),
                  html.Div(item["description"], className="ia-cov-description")], className="ia-cov-summary-main"),
        html.Span(item["type"], className="ia-cov-type"),
        html.Span(item["status"], style=_tone_style(item["tone"]),
                  title=f"Latest source test: {item.get('tested_at') or 'not yet tested'}"),
    ], className="ia-cov-summary")
    scope = html.Div([
        html.Div([html.Strong("Provider universe: "), item["universe"]]),
        html.Div([html.Strong("Current EMDASH catalogue: "), item["emdash_scope"]]),
    ], className="ia-cov-scope")
    return html.Details([html.Summary(summary), scope,
                         _catalogue_table(item["catalogue"], item["empty_message"])],
                        id={"type": "ia-coverage-detail", "provider": item["key"]},
                        className="ia-cov-detail", open=False)


def render(snapshot: dict[str, Any]):
    controls = html.Div([
        html.Div("What Indicator Analysis can pull", className="ia-cov-title"),
        html.Div([html.Button("Expand All", id="ia-cov-expand-all", n_clicks=0,
                              className="emd-btn emd-btn--ghost ia-cov-btn"),
                  html.Button("Collapse All", id="ia-cov-collapse-all", n_clicks=0,
                              className="emd-btn emd-btn--ghost ia-cov-btn")], className="ia-cov-actions"),
    ], className="ia-cov-toolbar")
    return html.Div([controls, *[provider_detail(item) for item in snapshot["providers"]]],
                    className="ia-cov-root")


def status_stamp() -> float:
    stamp = 0.0
    for path in (SERVICE.status.path, config.ROOT / "emdash_state.json", SERVICE.cache.root):
        try: stamp = max(stamp, path.stat().st_mtime)
        except OSError: pass
    return stamp
