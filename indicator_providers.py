"""Provider, diagnostics and cache layer for EMDASH Indicator Analysis.

All providers return the same records/meta contract. Indicator Analysis and the
provider-neutral Market Watch snapshot service therefore do not need to change
when another approved provider is added.

Implemented providers:
- curated World Bank World Development Indicators (official API)
- IMF monthly all-items CPI (current SDMX 3.0 data API)
- curated Yahoo Finance chart data (direct HTTPS JSON; no hidden interpolation)
- Gembridge Excel long or wide format (local workbook)

Nothing in this module reads or writes emdash.sqlite.
"""
from __future__ import annotations

import csv
import calendar
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config


UTC = dt.timezone.utc
TODAY = dt.datetime.now(UTC).date()
DEFAULT_CACHE_DIR = Path(os.getenv(
    "EMDASH_INDICATOR_CACHE",
    str(Path(__file__).resolve().parent / ".cache" / "indicator_analysis_v3"),
))
DEFAULT_CACHE_HOURS = float(os.getenv("EMDASH_INDICATOR_CACHE_HOURS", "12"))
PROVIDER_STATUS_PATH = DEFAULT_CACHE_DIR / "provider_status.json"
REQUEST_TIMEOUT = (5.0, 30.0)
MAX_SERIES = 8
MAX_MARKET_WATCH = 20
NAME_BY_ISO = {iso: name for iso, name, *_ in config.COUNTRIES}
IMF_CPI_VERSION = os.getenv("EMDASH_IMF_CPI_VERSION", "5.0.0")
IMF_API_KEY = os.getenv("EMDASH_IMF_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", os.getenv("EMDASH_FRED_API_KEY", ""))
_SECRET_KEYS = {"key", "api_key", "apikey", "token", "access_token", "subscription-key", "ocp-apim-subscription-key"}


@dataclass
class RequestDiagnostic:
    provider: str
    requested_series: str = ""
    final_endpoint: str = ""
    http_status: str = ""
    content_type: str = ""
    response_preview: str = ""
    detected_columns: list[str] = field(default_factory=list)
    parsed_row_count: int = 0
    available_countries: list[str] = field(default_factory=list)
    available_series: list[str] = field(default_factory=list)
    message: str = ""
    tested_at: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)
    fallback_result: str = ""

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["final_endpoint"] = sanitize_url(body["final_endpoint"])
        body["response_preview"] = scrub_preview(body["response_preview"])
        for attempt in body.get("attempts", []):
            attempt["final_endpoint"] = sanitize_url(attempt.get("final_endpoint", ""))
            attempt["response_preview"] = scrub_preview(attempt.get("response_preview", ""))
        return body


class ProviderError(RuntimeError):
    """Safe provider failure with optional copyable diagnostics."""

    def __init__(self, message: str, diagnostic: RequestDiagnostic | None = None):
        super().__init__(message)
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class IndicatorDefinition:
    provider: str
    code: str
    label: str
    frequency: str
    unit: str
    description: str
    dataset: str
    source_url: str
    key_template: str = ""
    version: str = ""
    notes: str = ""
    asset: str = ""
    semantic_type: str = "raw_level"


@dataclass(frozen=True)
class SeriesRequest:
    request_id: str
    provider: str
    geography: str
    indicator: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HistoryWindow:
    mode: str = "20y"
    start: str | None = None
    end: str | None = None

    def bounds(self, today: dt.date = TODAY) -> tuple[str | None, str | None]:
        end = self.end or today.isoformat()
        if self.mode == "max":
            return None, self.end
        if self.mode == "custom":
            if not self.start:
                raise ProviderError("Enter a Fetch History start date for Custom.")
            if self.end and self.start > self.end:
                raise ProviderError("Fetch History From must be before To.")
            return self.start, self.end
        years = {"5y": 5, "10y": 10, "20y": 20}.get(self.mode)
        if not years:
            raise ProviderError("Unknown Fetch History selection.")
        return f"{today.year - years}-01-01", end


@dataclass
class ProviderResult:
    records: list[dict[str, Any]]
    meta: dict[str, Any]
    diagnostic: RequestDiagnostic

    def to_dict(self) -> dict[str, Any]:
        body = {"records": self.records, "meta": self.meta}
        body["meta"]["diagnostic"] = self.diagnostic.to_dict()
        return body


def _utc_now() -> str:
    return dt.datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sanitize_url(url: str) -> str:
    if not url:
        return ""
    try:
        split = urlsplit(url)
        safe = []
        for key, value in parse_qsl(split.query, keep_blank_values=True):
            safe.append((key, "[redacted]" if key.lower() in _SECRET_KEYS else value))
        return urlunsplit((split.scheme, split.netloc, split.path, urlencode(safe, doseq=True), ""))
    except Exception:
        return str(url)[:1000]


def scrub_preview(text: str, limit: int = 1200) -> str:
    value = str(text or "")[:limit]
    for key in _SECRET_KEYS:
        value = re.sub(rf"(?i)({re.escape(key)}\s*[:=]\s*)[^,;\s\"']+", r"\1[redacted]", value)
    return value


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2, connect=2, read=2, status=2, backoff_factor=0.45,
        # 429 and 503 are handled explicitly. In particular, do not create a
        # retry storm during IMF maintenance or provider rate limiting.
        status_forcelist=(500, 502, 504),
        allowed_methods=frozenset(("GET",)), respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10))
    session.headers.update({
        "User-Agent": "EMDASH/10.0 data-client",
        "Accept-Encoding": "gzip, deflate",
    })
    return session


def safe_error(exc: Exception) -> str:
    if isinstance(exc, ProviderError):
        return str(exc)
    if isinstance(exc, requests.Timeout):
        return "The data source timed out. Retry shortly."
    if isinstance(exc, requests.ConnectionError):
        return "The data source could not be reached. Check internet or proxy access."
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else "unknown"
        return f"The data source returned HTTP {status}."
    return (str(exc).strip() or "Unexpected provider response.")[:300]


def error_diagnostic(exc: Exception, provider: str = "") -> dict[str, Any] | None:
    if isinstance(exc, ProviderError) and exc.diagnostic:
        return exc.diagnostic.to_dict()
    return RequestDiagnostic(provider=provider, message=safe_error(exc), tested_at=_utc_now()).to_dict()


WORLD_BANK_INDICATORS: dict[str, IndicatorDefinition] = {
    item.code: item for item in (
        IndicatorDefinition("world_bank", "NY.GDP.MKTP.KD.ZG", "Real GDP growth", "Annual", "% YoY", "Annual real GDP growth.", "World Development Indicators", "https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG", semantic_type="growth_rate"),
        IndicatorDefinition("world_bank", "FP.CPI.TOTL.ZG", "Consumer price inflation", "Annual", "% YoY", "Annual CPI inflation.", "World Development Indicators", "https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG", semantic_type="growth_rate"),
        IndicatorDefinition("world_bank", "BN.CAB.XOKA.GD.ZS", "Current account balance", "Annual", "% of GDP", "Current-account balance as a share of GDP.", "World Development Indicators", "https://data.worldbank.org/indicator/BN.CAB.XOKA.GD.ZS", semantic_type="ratio"),
        IndicatorDefinition("world_bank", "GC.DOD.TOTL.GD.ZS", "Central government debt", "Annual", "% of GDP", "Central government debt; coverage varies.", "World Development Indicators", "https://data.worldbank.org/indicator/GC.DOD.TOTL.GD.ZS", semantic_type="ratio"),
        IndicatorDefinition("world_bank", "SL.UEM.TOTL.ZS", "Unemployment", "Annual", "% of labour force", "ILO-modelled unemployment rate.", "World Development Indicators", "https://data.worldbank.org/indicator/SL.UEM.TOTL.ZS", semantic_type="rate"),
        IndicatorDefinition("world_bank", "NE.EXP.GNFS.ZS", "Exports of goods and services", "Annual", "% of GDP", "Exports as a share of GDP.", "World Development Indicators", "https://data.worldbank.org/indicator/NE.EXP.GNFS.ZS", semantic_type="ratio"),
        IndicatorDefinition("world_bank", "NE.IMP.GNFS.ZS", "Imports of goods and services", "Annual", "% of GDP", "Imports as a share of GDP.", "World Development Indicators", "https://data.worldbank.org/indicator/NE.IMP.GNFS.ZS", semantic_type="ratio"),
        IndicatorDefinition("world_bank", "BX.KLT.DINV.WD.GD.ZS", "FDI net inflows", "Annual", "% of GDP", "FDI net inflows as a share of GDP.", "World Development Indicators", "https://data.worldbank.org/indicator/BX.KLT.DINV.WD.GD.ZS", semantic_type="ratio"),
        IndicatorDefinition("world_bank", "FI.RES.TOTL.CD", "Total reserves including gold", "Annual", "USD", "Total reserves including gold.", "World Development Indicators", "https://data.worldbank.org/indicator/FI.RES.TOTL.CD", semantic_type="stock"),
        IndicatorDefinition("world_bank", "NY.GDP.PCAP.CD", "GDP per capita", "Annual", "USD per person", "GDP per capita in current US dollars.", "World Development Indicators", "https://data.worldbank.org/indicator/NY.GDP.PCAP.CD", semantic_type="raw_level"),
        IndicatorDefinition("world_bank", "NY.GNS.ICTR.ZS", "Gross savings", "Annual", "% of GDP", "Gross savings as a share of GDP.", "World Development Indicators", "https://data.worldbank.org/indicator/NY.GNS.ICTR.ZS", semantic_type="ratio"),
        IndicatorDefinition("world_bank", "FM.LBL.BMNY.GD.ZS", "Broad money", "Annual", "% of GDP", "Broad money as a share of GDP.", "World Development Indicators", "https://data.worldbank.org/indicator/FM.LBL.BMNY.GD.ZS", semantic_type="ratio"),
        IndicatorDefinition("world_bank", "SP.POP.TOTL", "Population", "Annual", "people", "Total resident population.", "World Development Indicators", "https://data.worldbank.org/indicator/SP.POP.TOTL", semantic_type="stock"),
    )
}

IMF_INDICATORS = {
    "CPI_ALL_ITEMS_INDEX_M": IndicatorDefinition(
        "imf_sdmx", "CPI_ALL_ITEMS_INDEX_M", "Consumer Price Index — all items", "Monthly", "Index",
        "National all-items CPI index, monthly.", "IMF Consumer Price Index (CPI)",
        "https://data.imf.org/en/datasets/IMF.STA:CPI",
        key_template="{geography}.CPI._T.IX.M", version=IMF_CPI_VERSION,
        notes="IMF SDMX 3.0 CPI flow; explicit version and dimension key.",
        semantic_type="index",
    )
}

# DataMapper is the deliberately simple annual route. It does not replace SDMX;
# monthly CPI and future richer IMF datasets remain on the SDMX provider.
IMF_DATAMAPPER_INDICATORS = {
    item.code: item for item in (
        IndicatorDefinition("imf_datamapper", "NGDP_RPCH", "Real GDP growth", "Annual", "% YoY", "Real GDP, annual percent change.", "IMF World Economic Outlook (October 2026)", "https://www.imf.org/external/datamapper/NGDP_RPCH@WEO", semantic_type="growth_rate"),
        IndicatorDefinition("imf_datamapper", "PCPIPCH", "Consumer price inflation", "Annual", "% YoY", "Average consumer prices, annual percent change.", "IMF World Economic Outlook (October 2026)", "https://www.imf.org/external/datamapper/PCPIPCH@WEO", semantic_type="growth_rate"),
        IndicatorDefinition("imf_datamapper", "BCA", "Current account balance", "Annual", "USD billions", "Current-account balance in billions of US dollars.", "IMF World Economic Outlook (October 2026)", "https://www.imf.org/external/datamapper/BCA@WEO", semantic_type="flow"),
        IndicatorDefinition("imf_datamapper", "BCA_NGDPD", "Current account balance", "Annual", "% of GDP", "Current-account balance as a share of GDP.", "IMF World Economic Outlook (October 2026)", "https://www.imf.org/external/datamapper/BCA_NGDPD@WEO", semantic_type="ratio"),
        IndicatorDefinition("imf_datamapper", "LUR", "Unemployment rate", "Annual", "% of labour force", "Unemployment rate.", "IMF World Economic Outlook (October 2026)", "https://www.imf.org/external/datamapper/LUR@WEO", semantic_type="rate"),
        IndicatorDefinition("imf_datamapper", "GGXCNL_NGDP", "General government net lending/borrowing", "Annual", "% of GDP", "General government net lending/borrowing as a share of GDP.", "IMF World Economic Outlook (October 2026)", "https://www.imf.org/external/datamapper/GGXCNL_NGDP@WEO", semantic_type="ratio"),
        IndicatorDefinition("imf_datamapper", "GGXWDG_NGDP", "General government gross debt", "Annual", "% of GDP", "General government gross debt as a share of GDP.", "IMF World Economic Outlook (October 2026)", "https://www.imf.org/external/datamapper/GGXWDG_NGDP@WEO", semantic_type="ratio"),
    )
}

FRED_INDICATORS = {
    item.code: item for item in (
        IndicatorDefinition("fred", "DFF", "Effective Federal Funds Rate", "Daily", "%", "Effective federal funds rate.", "FRED", "https://fred.stlouisfed.org/series/DFF", semantic_type="rate"),
        IndicatorDefinition("fred", "DGS2", "2-Year Treasury Constant Maturity Rate", "Daily", "%", "US Treasury 2-year constant-maturity rate.", "FRED", "https://fred.stlouisfed.org/series/DGS2", semantic_type="rate"),
        IndicatorDefinition("fred", "DGS10", "10-Year Treasury Constant Maturity Rate", "Daily", "%", "US Treasury 10-year constant-maturity rate.", "FRED", "https://fred.stlouisfed.org/series/DGS10", semantic_type="rate"),
        IndicatorDefinition("fred", "DGS30", "30-Year Treasury Constant Maturity Rate", "Daily", "%", "US Treasury 30-year constant-maturity rate.", "FRED", "https://fred.stlouisfed.org/series/DGS30", semantic_type="rate"),
        IndicatorDefinition("fred", "T10Y2Y", "10-Year minus 2-Year Treasury Spread", "Daily", "percentage points", "10-year less 2-year Treasury constant-maturity spread.", "FRED", "https://fred.stlouisfed.org/series/T10Y2Y", semantic_type="spread"),
        IndicatorDefinition("fred", "T10Y3M", "10-Year minus 3-Month Treasury Spread", "Daily", "percentage points", "10-year less 3-month Treasury spread.", "FRED", "https://fred.stlouisfed.org/series/T10Y3M", semantic_type="spread"),
        IndicatorDefinition("fred", "DFII10", "10-Year Treasury Inflation-Indexed Rate", "Daily", "%", "10-year TIPS constant-maturity rate.", "FRED", "https://fred.stlouisfed.org/series/DFII10", semantic_type="rate"),
        IndicatorDefinition("fred", "BAMLC0A0CM", "ICE BofA US Corporate OAS", "Daily", "percentage points", "US investment-grade corporate option-adjusted spread.", "FRED", "https://fred.stlouisfed.org/series/BAMLC0A0CM", semantic_type="spread"),
        IndicatorDefinition("fred", "BAMLH0A0HYM2", "ICE BofA US High Yield OAS", "Daily", "percentage points", "US high-yield corporate option-adjusted spread.", "FRED", "https://fred.stlouisfed.org/series/BAMLH0A0HYM2", semantic_type="spread"),
        IndicatorDefinition("fred", "BAMLEMCBPIOAS", "ICE BofA Emerging Markets Corporate Plus OAS", "Daily", "percentage points", "Emerging-markets corporate option-adjusted spread.", "FRED", "https://fred.stlouisfed.org/series/BAMLEMCBPIOAS", semantic_type="spread"),
        IndicatorDefinition("fred", "VIXCLS", "CBOE Volatility Index: VIX", "Daily", "Index", "VIX closing level.", "FRED", "https://fred.stlouisfed.org/series/VIXCLS", semantic_type="index"),
        IndicatorDefinition("fred", "NFCI", "Chicago Fed National Financial Conditions Index", "Weekly", "Index", "National Financial Conditions Index.", "FRED", "https://fred.stlouisfed.org/series/NFCI", semantic_type="index"),
        IndicatorDefinition("fred", "STLFSI4", "St. Louis Fed Financial Stress Index", "Weekly", "Index", "St. Louis Fed Financial Stress Index.", "FRED", "https://fred.stlouisfed.org/series/STLFSI4", semantic_type="index"),
        IndicatorDefinition("fred", "CPIAUCSL", "Consumer Price Index for All Urban Consumers", "Monthly", "Index", "US all-items CPI index.", "FRED", "https://fred.stlouisfed.org/series/CPIAUCSL", semantic_type="index"),
        IndicatorDefinition("fred", "UNRATE", "Unemployment Rate", "Monthly", "%", "US unemployment rate.", "FRED", "https://fred.stlouisfed.org/series/UNRATE", semantic_type="rate"),
        IndicatorDefinition("fred", "PAYEMS", "All Employees, Total Nonfarm", "Monthly", "Thousands of persons", "US total nonfarm payroll employment.", "FRED", "https://fred.stlouisfed.org/series/PAYEMS", semantic_type="stock"),
        IndicatorDefinition("fred", "INDPRO", "Industrial Production: Total Index", "Monthly", "Index", "US industrial production index.", "FRED", "https://fred.stlouisfed.org/series/INDPRO", semantic_type="index"),
        IndicatorDefinition("fred", "GDPC1", "Real Gross Domestic Product", "Quarterly", "Billions of chained 2017 USD", "US real GDP.", "FRED", "https://fred.stlouisfed.org/series/GDPC1", semantic_type="flow"),
        IndicatorDefinition("fred", "WALCL", "Federal Reserve Total Assets", "Weekly", "Millions USD", "Federal Reserve total assets.", "FRED", "https://fred.stlouisfed.org/series/WALCL", semantic_type="stock"),
    )
}

MARKET_INDICATORS = {
    item.code: item for item in (
        IndicatorDefinition("yahoo_market", "BRENT", "Brent crude front-month", "Daily", "USD/bbl", "Front-month Brent crude futures close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/BZ=F", key_template="BZ=F", asset="Commodity", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "WTI", "WTI crude front-month", "Daily", "USD/bbl", "Front-month WTI crude futures close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/CL=F", key_template="CL=F", asset="Commodity", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "GOLD", "Gold front-month", "Daily", "USD/oz", "Front-month gold futures close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/GC=F", key_template="GC=F", asset="Commodity", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "COPPER", "Copper front-month", "Daily", "USD/lb", "Front-month copper futures close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/HG=F", key_template="HG=F", asset="Commodity", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "EURUSD", "EUR/USD", "Daily", "USD per EUR", "EUR/USD close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/EURUSD=X", key_template="EURUSD=X", asset="FX", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "GBPUSD", "GBP/USD", "Daily", "USD per GBP", "GBP/USD close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/GBPUSD=X", key_template="GBPUSD=X", asset="FX", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "USDJPY", "USD/JPY", "Daily", "JPY per USD", "USD/JPY close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/JPY=X", key_template="JPY=X", asset="FX", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "AUDUSD", "AUD/USD", "Daily", "USD per AUD", "AUD/USD close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/AUDUSD=X", key_template="AUDUSD=X", asset="FX", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "USDSGD", "USD/SGD", "Daily", "SGD per USD", "USD/SGD delayed daily close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/SGD=X", key_template="SGD=X", asset="FX", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "USDCNH", "USD/CNH", "Daily", "CNH per USD", "USD/CNH delayed daily close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/CNH=X", key_template="CNH=X", asset="FX", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "SPX", "S&P 500", "Daily", "Index", "S&P 500 close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/%5EGSPC", key_template="^GSPC", asset="Equity index", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "NASDAQ", "Nasdaq Composite", "Daily", "Index", "Nasdaq Composite close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/%5EIXIC", key_template="^IXIC", asset="Equity index", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "DOW", "Dow Jones Industrial Average", "Daily", "Index", "DJIA close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/%5EDJI", key_template="^DJI", asset="Equity index", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "NIKKEI", "Nikkei 225", "Daily", "Index", "Nikkei 225 close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/%5EN225", key_template="^N225", asset="Equity index", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "HSI", "Hang Seng Index", "Daily", "Index", "Hang Seng Index close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/%5EHSI", key_template="^HSI", asset="Equity index", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "BTCUSD", "Bitcoin / USD", "Daily", "USD", "BTC-USD close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/BTC-USD", key_template="BTC-USD", asset="Crypto", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "ETHUSD", "Ether / USD", "Daily", "USD", "ETH-USD close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/ETH-USD", key_template="ETH-USD", asset="Crypto", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "VIX", "CBOE Volatility Index", "Daily", "Index", "VIX close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/%5EVIX", key_template="^VIX", asset="Volatility", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "US10Y", "US 10-Year Treasury yield", "Daily", "%", "US 10-year Treasury yield index close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/%5ETNX", key_template="^TNX", asset="Rates", semantic_type="rate"),
        IndicatorDefinition("yahoo_market", "DXY", "US Dollar Index", "Daily", "Index", "ICE US Dollar Index close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/DX-Y.NYB", key_template="DX-Y.NYB", asset="FX", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "EEM", "iShares MSCI Emerging Markets ETF", "Daily", "USD", "EEM adjusted market close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/EEM", key_template="EEM", asset="Equity ETF", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "EMB", "iShares J.P. Morgan USD EM Bond ETF", "Daily", "USD", "EMB adjusted market close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/EMB", key_template="EMB", asset="Bond ETF", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "STOXX50", "EURO STOXX 50", "Daily", "Index", "EURO STOXX 50 close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/%5ESTOXX50E", key_template="^STOXX50E", asset="Equity index", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "SHCOMP", "Shanghai Composite", "Daily", "Index", "Shanghai Composite close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/000001.SS", key_template="000001.SS", asset="Equity index", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "CSI300", "CSI 300", "Daily", "Index", "CSI 300 delayed daily close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/000300.SS", key_template="000300.SS", asset="Equity index", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "USDCHF", "USD/CHF", "Daily", "CHF per USD", "USD/CHF close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/CHF=X", key_template="CHF=X", asset="FX", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "USDCAD", "USD/CAD", "Daily", "CAD per USD", "USD/CAD close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/CAD=X", key_template="CAD=X", asset="FX", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "NATGAS", "Natural gas front-month", "Daily", "USD/MMBtu", "Front-month Henry Hub natural-gas futures close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/NG=F", key_template="NG=F", asset="Commodity", semantic_type="price"),
        IndicatorDefinition("yahoo_market", "SILVER", "Silver front-month", "Daily", "USD/oz", "Front-month silver futures close.", "Yahoo Finance chart data", "https://finance.yahoo.com/quote/SI=F", key_template="SI=F", asset="Commodity", semantic_type="price"),
    )
}

CATALOGUES = {"world_bank": WORLD_BANK_INDICATORS, "imf_datamapper": IMF_DATAMAPPER_INDICATORS, "imf_sdmx": IMF_INDICATORS, "fred": FRED_INDICATORS, "yahoo_market": MARKET_INDICATORS}
PROVIDER_LABELS = {"world_bank": "World Bank WDI", "imf_datamapper": "IMF DataMapper — Annual", "imf_sdmx": "IMF SDMX — CPI", "fred": "FRED", "yahoo_market": "Market Data — Yahoo", "gembridge_excel": "Gembridge Excel"}


def catalogue(provider: str) -> dict[str, IndicatorDefinition]:
    return CATALOGUES.get(provider, {})


def indicator_options(provider: str) -> list[dict[str, str]]:
    return [{"label": f"{item.label} · {item.code}", "value": key}
            for key, item in sorted(catalogue(provider).items(), key=lambda pair: pair[1].label)]


def infer_semantic_type(unit: str, label: str = "", declared: str = "") -> str:
    declared = str(declared or "").strip().lower().replace(" ", "_")
    valid = {"index", "price", "raw_level", "growth_rate", "rate", "ratio",
             "spread", "stock", "flow", "event"}
    if declared in valid:
        return declared
    unit_low, label_low = str(unit or "").lower(), str(label or "").lower()
    if "bp" in unit_low or "basis point" in unit_low or "spread" in label_low:
        return "spread"
    if "index" in unit_low:
        return "index"
    if "% yoy" in unit_low or "growth" in label_low or "inflation" in label_low:
        return "growth_rate"
    if "% of" in unit_low or "ratio" in label_low:
        return "ratio"
    if unit_low.strip() in {"%", "percent", "percentage points", "pp"} or "rate" in label_low:
        return "rate"
    if "event" in unit_low:
        return "event"
    if any(token in unit_low for token in ("usd", "eur", "gbp", "jpy")) and any(
            token in label_low for token in ("price", "crude", "gold", "copper", "fx", "/")):
        return "price"
    return "raw_level"


class SeriesProvider(ABC):
    provider_id: str

    def __init__(self, session: requests.Session | None = None):
        self.session = session or _session()

    @abstractmethod
    def fetch(self, request: SeriesRequest, history: HistoryWindow) -> ProviderResult:
        raise NotImplementedError

    def definition(self, code: str) -> IndicatorDefinition:
        try:
            return catalogue(self.provider_id)[code]
        except KeyError as exc:
            raise ProviderError(f"Unsupported {PROVIDER_LABELS.get(self.provider_id, self.provider_id)} series code.") from exc

    def test(self, request: SeriesRequest, history: HistoryWindow) -> RequestDiagnostic:
        try:
            return self.fetch(request, history).diagnostic
        except ProviderError as exc:
            return exc.diagnostic or RequestDiagnostic(provider=self.provider_id, requested_series=request.indicator, message=str(exc), tested_at=_utc_now())
        except Exception as exc:
            return RequestDiagnostic(provider=self.provider_id, requested_series=request.indicator, message=safe_error(exc), tested_at=_utc_now())


def _response_diag(provider: str, requested: str, response: requests.Response) -> RequestDiagnostic:
    return RequestDiagnostic(
        provider=provider, requested_series=requested,
        final_endpoint=sanitize_url(response.url), http_status=str(response.status_code),
        content_type=response.headers.get("Content-Type", ""),
        response_preview=scrub_preview(response.text), tested_at=_utc_now(),
    )


def _planned_diag(provider: str, requested: str, url: str, params=None) -> RequestDiagnostic:
    prepared = requests.Request("GET", url, params=params).prepare().url or url
    return RequestDiagnostic(provider=provider, requested_series=requested,
                             final_endpoint=prepared, tested_at=_utc_now())


def _imf_http_error(response: requests.Response,
                    diagnostic: RequestDiagnostic) -> ProviderError | None:
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "")
        extra = f" Retry-After: {retry_after}." if retry_after else ""
        diagnostic.message = (
            "IMF is temporarily rate-limiting requests (HTTP 429). "
            "No rapid retries were attempted; use cached data and retry later." + extra
        )
        return ProviderError(diagnostic.message, diagnostic)
    if response.status_code == 503:
        diagnostic.message = (
            "IMF is temporarily unavailable (HTTP 503). IMF announced planned "
            "maintenance from October 24, 2026 01:00 EST through October 26, "
            "2026 08:00 EST with intermittent outages. No rapid retries were "
            "attempted. This status does not by itself invalidate the query; "
            "cached data will be used when available."
        )
        return ProviderError(diagnostic.message, diagnostic)
    return None


def _base_meta(request: SeriesRequest, definition: IndicatorDefinition, request_url: str,
               records: list[dict[str, Any]]) -> dict[str, Any]:
    latest = records[-1]
    geography_label = NAME_BY_ISO.get(request.geography, request.geography or definition.asset or "Global")
    return {
        "request_id": request.request_id, "provider": request.provider,
        "provider_label": PROVIDER_LABELS[request.provider], "source": definition.dataset,
        "source_url": definition.source_url, "geography": request.geography,
        "geography_label": geography_label, "indicator": request.indicator,
        "series_code": definition.code, "label": definition.label,
        "description": definition.description, "frequency": definition.frequency,
        "unit": definition.unit, "dataset_version": definition.version,
        "semantic_type": definition.semantic_type,
        "notes": definition.notes, "request_url": sanitize_url(request_url),
        "retrieved_at": _utc_now(), "latest_period": latest["period"],
        "latest_value": latest["value"], "observations": len(records),
    }


class WorldBankProvider(SeriesProvider):
    provider_id = "world_bank"
    base = "https://api.worldbank.org/v2"

    def fetch(self, request: SeriesRequest, history: HistoryWindow) -> ProviderResult:
        definition = self.definition(request.indicator)
        start, end = history.bounds()
        params: dict[str, Any] = {"format": "json", "source": 2, "per_page": 2000}
        if start or end:
            params["date"] = f"{int((start or '1960')[:4])}:{int((end or str(TODAY.year))[:4])}"
        url = f"{self.base}/country/{request.geography}/indicator/{definition.code}"
        planned = _planned_diag(self.provider_id, definition.code, url, params)
        try:
            response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except Exception as exc:
            planned.http_status = "NETWORK_ERROR"; planned.message = safe_error(exc)
            raise ProviderError(planned.message, planned) from exc
        diagnostic = _response_diag(self.provider_id, definition.code, response)
        try:
            response.raise_for_status()
            body = response.json()
            records, parsed = self.parse(body, request.geography)
            diagnostic.detected_columns = parsed["columns"]
            diagnostic.available_countries = parsed["countries"]
            diagnostic.available_series = parsed["series"]
            diagnostic.parsed_row_count = len(records)
            if not records:
                diagnostic.message = "HTTP succeeded but no matching observations parsed. Inspect available identifiers and response preview."
                raise ProviderError(diagnostic.message, diagnostic)
        except ProviderError:
            raise
        except Exception as exc:
            diagnostic.message = safe_error(exc)
            raise ProviderError(diagnostic.message, diagnostic) from exc
        return ProviderResult(records, _base_meta(request, definition, response.url, records), diagnostic)

    @staticmethod
    def parse(body: Any, geography: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not isinstance(body, list) or len(body) < 2 or not isinstance(body[1], list):
            raise ProviderError("World Bank returned an unexpected JSON shape.")
        records, countries, series, columns = [], set(), set(), set()
        for row in body[1]:
            columns.update(row.keys()); countries.add(row.get("countryiso3code") or "")
            series.add((row.get("indicator") or {}).get("id") or "")
            value, year = row.get("value"), str(row.get("date", ""))
            if value is None or not year.isdigit() or (row.get("countryiso3code") or geography) != geography:
                continue
            try: numeric = float(value)
            except (TypeError, ValueError): continue
            if math.isfinite(numeric):
                records.append({"date": f"{int(year):04d}-12-31", "period": year, "value": numeric, "is_projection": False, "observation_status": row.get("obs_status") or ""})
        return sorted(records, key=lambda item: item["date"]), {
            "columns": sorted(columns), "countries": sorted(x for x in countries if x), "series": sorted(x for x in series if x)
        }


class IMFDataMapperProvider(SeriesProvider):
    provider_id = "imf_datamapper"
    base = "https://www.imf.org/external/datamapper/api/v1"

    def fetch(self, request: SeriesRequest, history: HistoryWindow) -> ProviderResult:
        definition = self.definition(request.indicator)
        start, end = history.bounds()
        params: dict[str, str] = {}
        if start or end:
            first = int((start or "1980")[:4])
            last = int((end or str(TODAY.year + 5))[:4])
            params["periods"] = ",".join(str(year) for year in range(first, last + 1))
        url = f"{self.base}/{definition.code}/{request.geography}"
        planned = _planned_diag(self.provider_id, definition.code, url, params)
        try:
            response = self.session.get(url, params=params, headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
        except Exception as exc:
            planned.http_status = "NETWORK_ERROR"; planned.message = safe_error(exc)
            raise ProviderError(planned.message, planned) from exc
        diagnostic = _response_diag(self.provider_id, definition.code, response)
        imf_error = _imf_http_error(response, diagnostic)
        if imf_error:
            raise imf_error
        try:
            response.raise_for_status()
            body = response.json()
            records, parsed = self.parse(body, definition.code, request.geography)
            diagnostic.detected_columns = parsed["columns"]
            diagnostic.available_countries = parsed["countries"]
            diagnostic.available_series = parsed["series"]
            diagnostic.parsed_row_count = len(records)
            if not records:
                diagnostic.message = "IMF DataMapper returned no matching annual observations."
                raise ProviderError(diagnostic.message, diagnostic)
        except ProviderError:
            raise
        except Exception as exc:
            diagnostic.message = safe_error(exc)
            raise ProviderError(diagnostic.message, diagnostic) from exc
        diagnostic.fallback_result = "DataMapper JSON route succeeded."
        meta = _base_meta(request, definition, response.url, records)
        meta["imf_route"] = "datamapper_json"
        return ProviderResult(records, meta, diagnostic)

    @staticmethod
    def parse(body: Any, code: str, geography: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        values = (body or {}).get("values", {}) if isinstance(body, dict) else {}
        indicator_values = values.get(code, {}) if isinstance(values, dict) else {}
        countries = sorted(str(key) for key in indicator_values.keys()) if isinstance(indicator_values, dict) else []
        country_values = indicator_values.get(geography, {}) if isinstance(indicator_values, dict) else {}
        records = []
        if isinstance(country_values, dict):
            for year, value in country_values.items():
                try:
                    numeric, year_int = float(value), int(year)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(numeric):
                    records.append({"date": f"{year_int:04d}-12-31", "period": str(year_int),
                                    "value": numeric, "is_projection": year_int > TODAY.year,
                                    "observation_status": ""})
        parsed = {"columns": ["indicator", "country", "year", "value"],
                  "countries": countries, "series": [code] if code in values else []}
        return sorted(records, key=lambda item: item["date"]), parsed


class IMFSDMXProvider(SeriesProvider):
    provider_id = "imf_sdmx"
    base = "https://api.imf.org/external/sdmx/3.0/data/dataflow"
    accept_csv = "application/vnd.sdmx.data+csv;version=2.0.0"
    accept_json = "application/vnd.sdmx.data+json;version=2.0.0"

    def fetch(self, request: SeriesRequest, history: HistoryWindow) -> ProviderResult:
        definition = self.definition(request.indicator)
        start, end = history.bounds()
        key = definition.key_template.format(geography=request.geography)
        url = f"{self.base}/IMF.STA/CPI/{definition.version}/{key}"
        # Do not send dimensionAtObservation=AllDimensions. A live target-machine
        # response proved that this returned OBS_VALUE rows but blank TIME_PERIOD.
        params: list[tuple[str, str]] = [("attributes", "none")]
        if start: params.append(("startPeriod", start[:7]))
        if end: params.append(("endPeriod", end[:7]))
        requested = f"IMF.STA/CPI/{definition.version}/{key}"
        attempts: list[dict[str, Any]] = []
        csv_response = self._request(url, params, self.accept_csv, requested)
        csv_diag = _response_diag(self.provider_id, requested, csv_response)
        imf_error = _imf_http_error(csv_response, csv_diag)
        if imf_error:
            csv_diag.attempts = [csv_diag.to_dict()]
            raise imf_error
        try:
            csv_response.raise_for_status()
            records, parsed = self.parse(csv_response.text, request.geography)
            self._populate_diag(csv_diag, parsed, len(records))
        except ProviderError as exc:
            if exc.diagnostic:
                csv_diag.detected_columns = exc.diagnostic.detected_columns
                csv_diag.available_countries = exc.diagnostic.available_countries
                csv_diag.available_series = exc.diagnostic.available_series
            csv_diag.message = str(exc)
            records, parsed = [], {"columns": csv_diag.detected_columns,
                                   "countries": csv_diag.available_countries,
                                   "series": csv_diag.available_series,
                                   "value_rows": 0, "blank_time_rows": 0}
        except Exception as exc:
            csv_diag.message = safe_error(exc)
            csv_diag.attempts = [csv_diag.to_dict()]
            raise ProviderError(csv_diag.message, csv_diag) from exc
        attempts.append(csv_diag.to_dict())

        needs_fallback = bool(parsed.get("blank_time_rows")) or (
            not records and bool(parsed.get("value_rows")))
        if records and not needs_fallback:
            csv_diag.attempts = attempts
            csv_diag.fallback_result = "Primary SDMX-CSV succeeded with dated observations."
            meta = _base_meta(request, definition, csv_response.url, records)
            meta["sdmx_columns"] = parsed["columns"]
            return ProviderResult(records, meta, csv_diag)

        if needs_fallback:
            json_response = self._request(url, params, self.accept_json, requested)
            json_diag = _response_diag(self.provider_id, requested, json_response)
            imf_error = _imf_http_error(json_response, json_diag)
            if imf_error:
                json_diag.message = str(imf_error)
                attempts.append(json_diag.to_dict())
                csv_diag.attempts = attempts
                csv_diag.fallback_result = "SDMX-JSON fallback was temporarily unavailable."
                csv_diag.message = json_diag.message
                raise ProviderError(csv_diag.message, csv_diag)
            try:
                json_response.raise_for_status()
                json_records, json_parsed = self.parse_json(json_response.json(), request.geography)
                self._populate_diag(json_diag, json_parsed, len(json_records))
                if json_records:
                    attempts.append(json_diag.to_dict())
                    json_diag.attempts = attempts
                    json_diag.fallback_result = (
                        "Primary CSV contained values with blank/unusable periods; "
                        "SDMX-JSON time-index fallback succeeded."
                    )
                    meta = _base_meta(request, definition, json_response.url, json_records)
                    meta["sdmx_columns"] = json_parsed["columns"]
                    meta["imf_fallback"] = "sdmx_json_time_index"
                    return ProviderResult(json_records, meta, json_diag)
                json_diag.message = "SDMX-JSON fallback returned no dated matching observations."
            except Exception as exc:
                json_diag.message = safe_error(exc)
            attempts.append(json_diag.to_dict())

        csv_diag.attempts = attempts
        if parsed.get("value_rows") and parsed.get("blank_time_rows"):
            csv_diag.message = (
                f"IMF returned {parsed['value_rows']} numeric values but "
                f"{parsed['blank_time_rows']} had blank/unusable TIME_PERIOD values; "
                "the SDMX-JSON time-index fallback did not produce dated observations."
            )
            csv_diag.fallback_result = "Fallback attempted but dated observations were not recovered."
        else:
            csv_diag.message = "IMF returned no dated matching CPI observations."
            csv_diag.fallback_result = "Fallback was not required because no numeric blank-period rows were detected."
        raise ProviderError(csv_diag.message, csv_diag)

    def _request(self, url: str, params: list[tuple[str, str]], accept: str,
                 requested: str) -> requests.Response:
        planned = _planned_diag(self.provider_id, requested, url, params)
        try:
            headers = {"Accept": accept}
            if IMF_API_KEY:
                headers["Ocp-Apim-Subscription-Key"] = IMF_API_KEY
            return self.session.get(url, params=params, headers=headers,
                                    timeout=REQUEST_TIMEOUT)
        except Exception as exc:
            planned.http_status = "NETWORK_ERROR"
            planned.message = safe_error(exc)
            raise ProviderError(planned.message, planned) from exc

    @staticmethod
    def _populate_diag(diagnostic: RequestDiagnostic, parsed: dict[str, Any],
                       row_count: int) -> None:
        diagnostic.detected_columns = parsed.get("columns", [])
        diagnostic.available_countries = parsed.get("countries", [])
        diagnostic.available_series = parsed.get("series", [])
        diagnostic.parsed_row_count = row_count

    @staticmethod
    def parse(text: str, geography: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not text or not text.strip():
            raise ProviderError("IMF SDMX returned an empty response.")
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        rows = list(reader)
        if not reader.fieldnames:
            raise ProviderError("IMF SDMX response had no columns.")
        fields = {name.upper(): name for name in reader.fieldnames if name}
        time_col = next((fields[k] for k in ("TIME_PERIOD", "TIME", "PERIOD") if k in fields), None)
        value_col = next((fields[k] for k in ("OBS_VALUE", "VALUE") if k in fields), None)
        country_col = next((fields[k] for k in ("COUNTRY", "REF_AREA") if k in fields), None)
        indicator_col = next((fields[k] for k in ("INDICATOR", "SERIES", "INDEX_TYPE") if k in fields), None)
        countries = sorted({str(row.get(country_col, "")) for row in rows if country_col and row.get(country_col)})
        series = sorted({str(row.get(indicator_col, "")) for row in rows if indicator_col and row.get(indicator_col)})
        parsed = {"columns": list(reader.fieldnames), "countries": countries,
                  "series": series, "value_rows": 0, "blank_time_rows": 0}
        if not time_col or not value_col:
            raise ProviderError("IMF SDMX response is missing TIME_PERIOD or OBS_VALUE.", RequestDiagnostic(provider="imf_sdmx", detected_columns=list(reader.fieldnames), available_countries=countries, available_series=series, parsed_row_count=0, tested_at=_utc_now()))
        records = []
        for row in rows:
            if country_col and row.get(country_col) and row[country_col] != geography: continue
            try: numeric = float(row.get(value_col))
            except (TypeError, ValueError): continue
            if not math.isfinite(numeric):
                continue
            parsed["value_rows"] += 1
            period = str(row.get(time_col, "")).strip(); date = IMFSDMXProvider.period_to_date(period)
            if date:
                records.append({"date": date, "period": period, "value": numeric, "is_projection": False, "observation_status": row.get(fields.get("OBS_STATUS", ""), "")})
            else:
                parsed["blank_time_rows"] += 1
        return sorted(records, key=lambda item: item["date"]), parsed

    @staticmethod
    def parse_json(body: Any, geography: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Decode SDMX-JSON 1.x/2.x observation indexes into dated rows."""
        body = body if isinstance(body, dict) else {}
        root = body.get("data", body)
        datasets = root.get("dataSets") or body.get("dataSets") or []
        structures = root.get("structures") or body.get("structures") or []
        structure = structures[0] if structures else (root.get("structure") or body.get("structure") or {})
        dimensions = structure.get("dimensions", {}) if isinstance(structure, dict) else {}
        series_dims = dimensions.get("series") or []
        obs_dims = dimensions.get("observation") or []
        columns = [str(dim.get("id", "")) for dim in series_dims + obs_dims]
        time_dim = next((dim for dim in obs_dims if str(dim.get("id", "")).upper() == "TIME_PERIOD"), None)
        country_pos = next((i for i, dim in enumerate(series_dims)
                            if str(dim.get("id", "")).upper() in ("COUNTRY", "REF_AREA")), None)
        indicator_pos = next((i for i, dim in enumerate(series_dims)
                              if str(dim.get("id", "")).upper() in ("INDICATOR", "INDEX_TYPE", "SERIES")), None)
        countries, series_ids, records = set(), set(), []
        if not datasets or not time_dim:
            return [], {"columns": columns, "countries": [], "series": [],
                        "value_rows": 0, "blank_time_rows": 0}
        time_values = time_dim.get("values") or []
        time_labels = [str(value.get("id") or value.get("name") or "") for value in time_values]
        series_map = datasets[0].get("series") or {}
        value_rows = blank_time_rows = 0
        for series_key, series_body in series_map.items():
            key_parts = [int(part) for part in str(series_key).split(":") if part != ""]
            country = ""
            if country_pos is not None and country_pos < len(key_parts):
                vals = series_dims[country_pos].get("values") or []
                if key_parts[country_pos] < len(vals):
                    country = str(vals[key_parts[country_pos]].get("id") or "")
            if country:
                countries.add(country)
            indicator = ""
            if indicator_pos is not None and indicator_pos < len(key_parts):
                vals = series_dims[indicator_pos].get("values") or []
                if key_parts[indicator_pos] < len(vals):
                    indicator = str(vals[key_parts[indicator_pos]].get("id") or "")
            if indicator:
                series_ids.add(indicator)
            if country and country != geography:
                continue
            for obs_key, obs_value in (series_body.get("observations") or {}).items():
                raw = obs_value[0] if isinstance(obs_value, list) else obs_value
                try:
                    numeric = float(raw)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(numeric):
                    continue
                value_rows += 1
                try:
                    period = time_labels[int(str(obs_key).split(":")[0])]
                except (ValueError, IndexError):
                    period = ""
                date = IMFSDMXProvider.period_to_date(period)
                if date:
                    records.append({"date": date, "period": period, "value": numeric,
                                    "is_projection": False, "observation_status": ""})
                else:
                    blank_time_rows += 1
        return sorted(records, key=lambda item: item["date"]), {
            "columns": columns, "countries": sorted(countries),
            "series": sorted(series_ids), "value_rows": value_rows,
            "blank_time_rows": blank_time_rows,
        }

    @staticmethod
    def period_to_date(period: str) -> str | None:
        try:
            period = str(period).strip()
            if len(period) == 4 and period.isdigit(): return f"{period}-12-31"
            if re.fullmatch(r"\d{4}-Q[1-4]", period):
                year, quarter = period.split("-Q"); return dt.date(int(year), int(quarter) * 3, 1).isoformat()
            if re.fullmatch(r"\d{4}-\d{2}", period):
                year, month = period.split("-"); return dt.date(int(year), int(month), 1).isoformat()
            return dt.date.fromisoformat(period[:10]).isoformat()
        except (TypeError, ValueError): return None


class FREDProvider(SeriesProvider):
    provider_id = "fred"
    base = "https://api.stlouisfed.org/fred"

    @staticmethod
    def _require_key(requested: str, endpoint: str) -> str:
        if FRED_API_KEY and re.fullmatch(r"[a-z0-9]{32}", FRED_API_KEY):
            return FRED_API_KEY
        if FRED_API_KEY:
            diagnostic = RequestDiagnostic(
                provider="fred", requested_series=requested,
                final_endpoint=endpoint, http_status="INVALID_CONFIGURATION",
                content_type="application/json", tested_at=_utc_now(),
                message=("FRED_API_KEY is configured but does not match the "
                         "required 32-character lowercase alphanumeric format."),
            )
            raise ProviderError(diagnostic.message, diagnostic)
        diagnostic = RequestDiagnostic(
            provider="fred", requested_series=requested,
            final_endpoint=endpoint, http_status="NOT_CONFIGURED",
            content_type="application/json", tested_at=_utc_now(),
            message=("FRED API key is not configured. Set the FRED_API_KEY "
                     "environment variable, restart EMDASH, then run Source Test."),
        )
        raise ProviderError(diagnostic.message, diagnostic)

    def definition_for(self, request: SeriesRequest) -> IndicatorDefinition:
        if request.indicator in FRED_INDICATORS:
            return FRED_INDICATORS[request.indicator]
        supplied = (request.options or {}).get("fred_definition") or {}
        if supplied and supplied.get("code") == request.indicator:
            return IndicatorDefinition(
                "fred", supplied["code"], supplied.get("label") or supplied["code"],
                supplied.get("frequency") or "Irregular",
                supplied.get("unit") or "Unspecified",
                supplied.get("description") or "FRED searched series.", "FRED",
                supplied.get("source_url") or f"https://fred.stlouisfed.org/series/{supplied['code']}",
                notes=supplied.get("notes") or "",
                semantic_type=supplied.get("semantic_type") or infer_semantic_type(
                    supplied.get("unit", ""), supplied.get("label", "")),
            )
        raise ProviderError(
            "FRED series metadata is unavailable. Search for the series again or choose a curated series."
        )

    def fetch(self, request: SeriesRequest, history: HistoryWindow) -> ProviderResult:
        definition = self.definition_for(request)
        endpoint = f"{self.base}/series/observations"
        key = self._require_key(definition.code, endpoint)
        start, end = history.bounds()
        params = {"series_id": definition.code, "api_key": key,
                  "file_type": "json", "sort_order": "asc"}
        if start: params["observation_start"] = start
        if end: params["observation_end"] = end
        planned = _planned_diag(self.provider_id, definition.code, endpoint, params)
        try:
            response = self.session.get(endpoint, params=params, headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
        except Exception as exc:
            planned.http_status = "NETWORK_ERROR"; planned.message = safe_error(exc)
            raise ProviderError(planned.message, planned) from exc
        diagnostic = _response_diag(self.provider_id, definition.code, response)
        if response.status_code in (429, 503):
            diagnostic.message = (
                f"FRED is temporarily {'rate-limiting requests' if response.status_code == 429 else 'unavailable'} "
                f"(HTTP {response.status_code}). No rapid retries were attempted; cached data will be used when available."
            )
            raise ProviderError(diagnostic.message, diagnostic)
        try:
            response.raise_for_status()
            records, parsed = self.parse_observations(response.json())
            diagnostic.detected_columns = parsed["columns"]
            diagnostic.available_series = [definition.code]
            diagnostic.parsed_row_count = len(records)
            if not records:
                diagnostic.message = "FRED returned no numeric observations for the selected history."
                raise ProviderError(diagnostic.message, diagnostic)
        except ProviderError:
            raise
        except Exception as exc:
            diagnostic.message = safe_error(exc)
            raise ProviderError(diagnostic.message, diagnostic) from exc
        fred_request = SeriesRequest(request.request_id, request.provider, "USA", request.indicator, request.options)
        return ProviderResult(records, _base_meta(fred_request, definition, response.url, records), diagnostic)

    @staticmethod
    def parse_observations(body: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        observations = (body or {}).get("observations", []) if isinstance(body, dict) else []
        columns = sorted({key for row in observations for key in row.keys()})
        records = []
        for row in observations:
            if row.get("value") in (None, ".", ""):
                continue
            try:
                value = float(row["value"])
                date = dt.date.fromisoformat(str(row.get("date", ""))[:10]).isoformat()
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                records.append({"date": date, "period": date, "value": value,
                                "is_projection": False,
                                "observation_status": row.get("status", "")})
        return records, {"columns": columns}

    def search(self, search_text: str, limit: int = 20) -> tuple[list[dict[str, Any]], RequestDiagnostic]:
        endpoint = f"{self.base}/series/search"
        key = self._require_key(search_text, endpoint)
        params = {"search_text": search_text, "api_key": key, "file_type": "json",
                  "limit": min(max(int(limit), 1), 50), "order_by": "search_rank"}
        planned = _planned_diag(self.provider_id, search_text, endpoint, params)
        try:
            response = self.session.get(endpoint, params=params, headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
        except Exception as exc:
            planned.http_status = "NETWORK_ERROR"; planned.message = safe_error(exc)
            raise ProviderError(planned.message, planned) from exc
        diagnostic = _response_diag(self.provider_id, search_text, response)
        if response.status_code in (429, 503):
            diagnostic.message = f"FRED search is temporarily unavailable (HTTP {response.status_code})."
            raise ProviderError(diagnostic.message, diagnostic)
        try:
            response.raise_for_status()
            results = self.parse_search(response.json())
            diagnostic.detected_columns = sorted({key for row in ((response.json() or {}).get("seriess") or []) for key in row})
            diagnostic.available_series = [item["code"] for item in results]
            diagnostic.parsed_row_count = len(results)
            diagnostic.message = f"Found {len(results)} FRED series."
            return results, diagnostic
        except ProviderError:
            raise
        except Exception as exc:
            diagnostic.message = safe_error(exc)
            raise ProviderError(diagnostic.message, diagnostic) from exc

    @staticmethod
    def parse_search(body: Any) -> list[dict[str, Any]]:
        rows = (body or {}).get("seriess", []) if isinstance(body, dict) else []
        out = []
        for row in rows:
            code = str(row.get("id") or "").strip()
            if not code:
                continue
            frequency = str(row.get("frequency") or row.get("frequency_short") or "Irregular")
            unit = str(row.get("units") or row.get("units_short") or "Unspecified")
            label = str(row.get("title") or code)
            out.append({
                "code": code, "label": label, "frequency": frequency, "unit": unit,
                "description": str(row.get("notes") or "FRED searched series."),
                "notes": str(row.get("seasonal_adjustment") or ""),
                "semantic_type": infer_semantic_type(unit, label),
                "source_url": f"https://fred.stlouisfed.org/series/{code}",
                "observation_start": row.get("observation_start", ""),
                "observation_end": row.get("observation_end", ""),
                "last_updated": row.get("last_updated", ""),
                "geography": "United States",
            })
        return out


class YahooMarketProvider(SeriesProvider):
    provider_id = "yahoo_market"
    base = "https://query1.finance.yahoo.com/v8/finance/chart"

    def fetch(self, request: SeriesRequest, history: HistoryWindow) -> ProviderResult:
        definition = self.definition(request.indicator)
        start, end = history.bounds()
        start_date = dt.date.fromisoformat(start) if start else dt.date(1970, 1, 1)
        end_date = dt.date.fromisoformat(end) if end else TODAY + dt.timedelta(days=1)
        params = {"period1": int(dt.datetime.combine(start_date, dt.time(), UTC).timestamp()), "period2": int(dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time(), UTC).timestamp()), "interval": "1d", "events": "history", "includeAdjustedClose": "true"}
        url = f"{self.base}/{definition.key_template}"
        planned = _planned_diag(self.provider_id, definition.key_template, url, params)
        try:
            response = self.session.get(url, params=params, headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
        except Exception as exc:
            planned.http_status = "NETWORK_ERROR"; planned.message = safe_error(exc)
            raise ProviderError(planned.message, planned) from exc
        diagnostic = _response_diag(self.provider_id, definition.key_template, response)
        try:
            response.raise_for_status(); body = response.json()
            records, parsed = self.parse(body)
            diagnostic.detected_columns = parsed["columns"]
            diagnostic.available_series = parsed["series"]
            diagnostic.parsed_row_count = len(records)
            if not records:
                diagnostic.message = "Yahoo returned no usable closes for this ticker and history window."
                raise ProviderError(diagnostic.message, diagnostic)
        except ProviderError: raise
        except Exception as exc:
            diagnostic.message = safe_error(exc); raise ProviderError(diagnostic.message, diagnostic) from exc
        market_request = SeriesRequest(request.request_id, request.provider, definition.asset or "Market", request.indicator, request.options)
        return ProviderResult(records, _base_meta(market_request, definition, response.url, records), diagnostic)

    @staticmethod
    def parse(body: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        chart = (body or {}).get("chart", {}); error = chart.get("error")
        if error: raise ProviderError(f"Yahoo chart error: {error.get('description') or error}")
        results = chart.get("result") or []
        if not results: return [], {"columns": [], "series": []}
        result = results[0]; timestamps = result.get("timestamp") or []
        quote = (((result.get("indicators") or {}).get("quote") or [{}])[0]); closes = quote.get("close") or []
        symbol = ((result.get("meta") or {}).get("symbol") or "")
        records = []
        for stamp, value in zip(timestamps, closes):
            if value is None: continue
            try: numeric = float(value)
            except (TypeError, ValueError): continue
            if math.isfinite(numeric):
                date = dt.datetime.fromtimestamp(int(stamp), UTC).date().isoformat()
                records.append({"date": date, "period": date, "value": numeric, "is_projection": False, "observation_status": ""})
        return records, {"columns": ["timestamp", "close"], "series": [symbol] if symbol else []}


class GembridgeExcelProvider(SeriesProvider):
    provider_id = "gembridge_excel"
    REQUIRED_LONG = ["date", "series_id", "value", "unit", "frequency", "source", "geography", "label"]

    def fetch(self, request: SeriesRequest, history: HistoryWindow) -> ProviderResult:
        options = request.options or {}; path = options.get("path", ""); sheet = options.get("sheet", "")
        table = options.get("table", ""); fmt = options.get("format", "auto"); mapping_sheet = options.get("mapping_sheet", "Mapping")
        entries, diagnostic = self.read_catalogue(path, sheet, table, fmt, mapping_sheet)
        entry = next((item for item in entries if item["series_id"] == request.indicator), None)
        if not entry:
            diagnostic.message = f"Series ID '{request.indicator}' was not found."
            raise ProviderError(diagnostic.message, diagnostic)
        records = entry.pop("records")
        start, end = history.bounds()
        if start: records = [row for row in records if row["date"] >= start]
        if end: records = [row for row in records if row["date"] <= end]
        diagnostic.parsed_row_count = len(records)
        if not records:
            diagnostic.message = "Workbook series exists but has no rows in the selected Fetch History."
            raise ProviderError(diagnostic.message, diagnostic)
        definition = IndicatorDefinition("gembridge_excel", entry["series_id"], entry["label"], entry["frequency"], entry["unit"], "Gembridge workbook series.", entry["source"], diagnostic.final_endpoint, asset=entry["geography"], semantic_type=entry.get("semantic_type") or infer_semantic_type(entry["unit"], entry["label"]))
        excel_request = SeriesRequest(request.request_id, request.provider, entry["geography"], request.indicator, request.options)
        return ProviderResult(records, _base_meta(excel_request, definition, diagnostic.final_endpoint, records), diagnostic)

    @classmethod
    def discover(cls, path: str, sheet: str = "", table: str = "", fmt: str = "auto", mapping_sheet: str = "Mapping") -> tuple[list[dict[str, Any]], RequestDiagnostic]:
        entries, diagnostic = cls.read_catalogue(path, sheet, table, fmt, mapping_sheet)
        catalogue = []
        for item in entries:
            metadata = {key: value for key, value in item.items() if key != "records"}
            dates = [row.get("date") for row in item.get("records", []) if row.get("date")]
            metadata["first"] = min(dates) if dates else ""
            metadata["last"] = max(dates) if dates else ""
            catalogue.append(metadata)
        return catalogue, diagnostic

    @classmethod
    def read_catalogue(cls, path: str, sheet: str = "", table: str = "", fmt: str = "auto", mapping_sheet: str = "Mapping") -> tuple[list[dict[str, Any]], RequestDiagnostic]:
        diagnostic = RequestDiagnostic(provider="gembridge_excel", final_endpoint=f"file://{Path(path).expanduser().resolve() if path else ''}", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", tested_at=_utc_now())
        try:
            if not path: raise ProviderError("Enter a workbook path.", diagnostic)
            workbook_path = Path(path).expanduser()
            if not workbook_path.exists(): raise ProviderError(f"Workbook not found: {workbook_path}", diagnostic)
            wb = load_workbook(workbook_path, read_only=False, data_only=True)
            target_sheet = sheet or wb.sheetnames[0]
            if target_sheet not in wb.sheetnames: raise ProviderError(f"Sheet '{target_sheet}' not found. Available: {', '.join(wb.sheetnames)}", diagnostic)
            ws = wb[target_sheet]; rows = cls._rows(ws, table)
            if not rows: raise ProviderError("Selected sheet/table is empty.", diagnostic)
            headers = [str(value).strip() if value is not None else "" for value in rows[0]]
            diagnostic.detected_columns = headers; diagnostic.response_preview = " | ".join(headers) + "\n" + "\n".join(" | ".join(str(v)[:80] for v in row) for row in rows[1:4])
            lower = [h.lower() for h in headers]
            detected = "long" if all(col in lower for col in cls.REQUIRED_LONG) else "wide"
            if fmt not in ("auto", detected): raise ProviderError(f"Selected format '{fmt}' does not match detected {detected} format.", diagnostic)
            entries = cls._parse_long(headers, rows[1:]) if detected == "long" else cls._parse_wide(wb, target_sheet, headers, rows[1:], mapping_sheet)
            diagnostic.available_series = sorted(item["series_id"] for item in entries)
            diagnostic.available_countries = sorted({item["geography"] for item in entries if item["geography"]})
            diagnostic.parsed_row_count = sum(len(item["records"]) for item in entries)
            diagnostic.http_status = "LOCAL_OK"; diagnostic.message = f"Validated {len(entries)} series from {target_sheet} ({detected} format)."
            return entries, diagnostic
        except ProviderError: raise
        except Exception as exc:
            diagnostic.message = safe_error(exc); raise ProviderError(diagnostic.message, diagnostic) from exc

    @staticmethod
    def _rows(ws, table: str) -> list[list[Any]]:
        if table:
            if table not in ws.tables: raise ProviderError(f"Excel table '{table}' not found. Available: {', '.join(ws.tables.keys()) or 'none'}")
            min_col, min_row, max_col, max_row = range_boundaries(ws.tables[table].ref)
            return [[ws.cell(r, c).value for c in range(min_col, max_col + 1)] for r in range(min_row, max_row + 1)]
        return [list(row) for row in ws.iter_rows(values_only=True) if any(value is not None for value in row)]

    @classmethod
    def _parse_long(cls, headers: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
        index = {header.lower(): pos for pos, header in enumerate(headers)}; grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            def get(name): return row[index[name]] if index[name] < len(row) else None
            series_id = str(get("series_id") or "").strip()
            if not series_id: continue
            date = cls._date(get("date")); value = cls._number(get("value"))
            if not date or value is None: continue
            unit = str(get("unit") or "Unspecified")
            label = str(get("label") or series_id)
            semantic_declared = str(get("semantic_type") or "") if "semantic_type" in index else ""
            entry = grouped.setdefault(series_id, {"series_id": series_id, "unit": unit, "frequency": str(get("frequency") or "Irregular"), "source": str(get("source") or "Gembridge Excel"), "geography": str(get("geography") or ""), "label": label, "semantic_type": infer_semantic_type(unit, label, semantic_declared), "records": []})
            entry["records"].append({"date": date, "period": date, "value": value, "is_projection": False, "observation_status": ""})
        return cls._finish(grouped)

    @classmethod
    def _parse_wide(cls, wb, data_sheet: str, headers: list[str], rows: list[list[Any]], mapping_sheet: str) -> list[dict[str, Any]]:
        if not headers or headers[0].lower() != "date": raise ProviderError("Wide format requires 'date' as the first column.")
        mapping: dict[str, dict[str, str]] = {}
        if mapping_sheet and mapping_sheet in wb.sheetnames:
            mrows = cls._rows(wb[mapping_sheet], "")
            if mrows:
                mh = [str(v or "").strip().lower() for v in mrows[0]]; mi = {v: i for i, v in enumerate(mh)}
                for row in mrows[1:]:
                    sid = str(row[mi["series_id"]] if "series_id" in mi and mi["series_id"] < len(row) else "").strip()
                    if sid: mapping[sid] = {key: str(row[pos] or "") for key, pos in mi.items() if pos < len(row)}
        grouped = {}
        for col, series_id in enumerate(headers[1:], 1):
            sid = str(series_id or "").strip()
            if not sid: continue
            meta = mapping.get(sid, {})
            unit = meta.get("unit") or "Unspecified"
            label = meta.get("label") or sid
            grouped[sid] = {"series_id": sid, "unit": unit, "frequency": meta.get("frequency") or "Irregular", "source": meta.get("source") or f"{Path(wb.path or '').name if getattr(wb, 'path', None) else 'Gembridge Excel'}", "geography": meta.get("geography") or "", "label": label, "semantic_type": infer_semantic_type(unit, label, meta.get("semantic_type", "")), "records": []}
        for row in rows:
            date = cls._date(row[0] if row else None)
            if not date: continue
            for col, sid in enumerate(headers[1:], 1):
                if not sid or col >= len(row): continue
                value = cls._number(row[col])
                if value is not None: grouped[str(sid)]["records"].append({"date": date, "period": date, "value": value, "is_projection": False, "observation_status": ""})
        return cls._finish(grouped)

    @staticmethod
    def _finish(grouped):
        for item in grouped.values(): item["records"].sort(key=lambda row: row["date"])
        return sorted((item for item in grouped.values() if item["records"]), key=lambda item: item["label"])

    @staticmethod
    def _date(value) -> str | None:
        if isinstance(value, dt.datetime): return value.date().isoformat()
        if isinstance(value, dt.date): return value.isoformat()
        try: return dt.date.fromisoformat(str(value)[:10]).isoformat()
        except Exception: return None

    @staticmethod
    def _number(value) -> float | None:
        try: number = float(value)
        except (TypeError, ValueError): return None
        return number if math.isfinite(number) else None


class JsonCache:
    def __init__(self, root: str | Path = DEFAULT_CACHE_DIR, ttl_hours: float = DEFAULT_CACHE_HOURS):
        self.root = Path(root); self.ttl = dt.timedelta(hours=float(ttl_hours)); self._lock = threading.RLock()
    def _path(self, key): return self.root / f"{hashlib.sha256(key.encode()).hexdigest()}.json"
    def read(self, key):
        try:
            body = json.loads(self._path(key).read_text(encoding="utf-8")); saved = dt.datetime.fromisoformat(body["cache_saved_at"].replace("Z", "+00:00"))
            return body, dt.datetime.now(UTC) - saved <= self.ttl
        except (OSError, ValueError, KeyError, TypeError): return None, False
    def write(self, key, payload):
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True); path = self._path(key); tmp = path.with_suffix(".tmp")
            body = json.loads(json.dumps(payload)); body["cache_saved_at"] = _utc_now(); tmp.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"); os.replace(tmp, path)

class ProviderStatusRegistry:
    def __init__(self, path: Path = PROVIDER_STATUS_PATH):
        self.path = path
        self._lock = threading.RLock()

    def read(self) -> dict[str, Any]:
        try:
            body = json.loads(self.path.read_text(encoding="utf-8"))
            return body if isinstance(body, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def write(self, provider: str, diagnostic: dict[str, Any],
              availability: str) -> None:
        with self._lock:
            body = self.read()
            body[provider] = {
                "availability": availability,
                "tested_at": diagnostic.get("tested_at") or _utc_now(),
                "http_status": diagnostic.get("http_status", ""),
                "message": diagnostic.get("message", ""),
                "requested_series": diagnostic.get("requested_series", ""),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def seed_missing(self, entries: dict[str, dict[str, Any]]) -> None:
        """Install target-machine status facts without overwriting newer tests."""
        with self._lock:
            body = self.read()
            changed = False
            for provider, entry in entries.items():
                if provider not in body:
                    body[provider] = dict(entry)
                    changed = True
            if changed:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp, self.path)


def demo_status_seed() -> dict[str, dict[str, Any]]:
    tested = "2026-10-24T09:45:00Z"
    entries = {
        "world_bank": {"availability": "available", "tested_at": tested,
                       "http_status": "200", "message": "Target-machine request succeeded.",
                       "requested_series": "NY.GDP.MKTP.KD.ZG"},
        "yahoo_market": {"availability": "available", "tested_at": tested,
                         "http_status": "200", "message": "Target-machine request succeeded.",
                         "requested_series": "BZ=F"},
        "imf_datamapper": {"availability": "temporarily unavailable", "tested_at": tested,
                           "http_status": "403", "message": "Target-machine request blocked by Akamai Access Denied.",
                           "requested_series": "GGXWDG_NGDP"},
        "imf_sdmx": {"availability": "temporarily unavailable", "tested_at": tested,
                     "http_status": "503", "message": "Target-machine IMF SDMX returned no healthy upstream.",
                     "requested_series": "CPI_ALL_ITEMS_INDEX_M"},
    }
    if not FRED_API_KEY:
        entries["fred"] = {"availability": "not configured", "tested_at": tested,
                           "http_status": "NOT_CONFIGURED",
                           "message": "FRED_API_KEY is not configured.",
                           "requested_series": "DGS10"}
    return entries


class ProviderService:
    def __init__(self, providers=None, cache=None):
        self.providers = providers or {"world_bank": WorldBankProvider(), "imf_datamapper": IMFDataMapperProvider(), "imf_sdmx": IMFSDMXProvider(), "fred": FREDProvider(), "yahoo_market": YahooMarketProvider(), "gembridge_excel": GembridgeExcelProvider()}
        self.cache = cache or JsonCache(); self.status = ProviderStatusRegistry(self.cache.root / "provider_status.json"); self.status.seed_missing(demo_status_seed()); self._locks = {}; self._guard = threading.Lock()
    @staticmethod
    def cache_key(request, history): return json.dumps({"schema": 4, "request": asdict(request), "history": asdict(history)}, sort_keys=True, separators=(",", ":"))
    def _lock_for(self, key):
        with self._guard: return self._locks.setdefault(key, threading.Lock())
    def fetch_one(self, request, history, force=False):
        if request.provider not in self.providers: raise ProviderError("Selected provider is not enabled.")
        key = self.cache_key(request, history)
        with self._lock_for(key):
            cached, fresh = self.cache.read(key)
            if cached and fresh and not force:
                cached = json.loads(json.dumps(cached)); cached["meta"]["cache_status"] = "fresh cache"; return cached
            try:
                result = self.providers[request.provider].fetch(request, history).to_dict(); result["meta"]["cache_status"] = "live"; self.cache.write(key, result)
                self.status.write(request.provider, result["meta"].get("diagnostic", {}), "available")
                return result
            except Exception as exc:
                diagnostic = error_diagnostic(exc, request.provider) or {}
                http_status = str(diagnostic.get("http_status", ""))
                availability = ("not configured" if http_status in ("NOT_CONFIGURED", "INVALID_CONFIGURATION")
                                else "temporarily unavailable" if http_status in ("429", "503", "NETWORK_ERROR")
                                else "error")
                self.status.write(request.provider, diagnostic, availability)
                if cached:
                    cached = json.loads(json.dumps(cached)); cached["meta"]["cache_status"] = "stale cache"; cached["meta"]["warning"] = f"Live refresh failed; cached observations shown. {safe_error(exc)}"; cached["meta"]["live_error_diagnostic"] = error_diagnostic(exc, request.provider); return cached
                raise
    def fetch_many(self, requests_, history, force=False):
        requests_list = list(requests_)[:MAX_SERIES]; results, errors = [], []
        if not requests_list: return {"series": [], "errors": [{"request_id": "", "message": "Add and include at least one series."}]}
        with ThreadPoolExecutor(max_workers=min(MAX_SERIES, len(requests_list))) as pool:
            futures = {pool.submit(self.fetch_one, request, history, force): request for request in requests_list}
            for future in as_completed(futures):
                request = futures[future]
                try: results.append(future.result())
                except Exception as exc: errors.append({"request_id": request.request_id, "message": safe_error(exc), "diagnostic": error_diagnostic(exc, request.provider)})
        order = {request.request_id: i for i, request in enumerate(requests_list)}; results.sort(key=lambda item: order.get(item["meta"]["request_id"], 999)); errors.sort(key=lambda item: order.get(item["request_id"], 999))
        return {"series": results, "errors": errors, "fetched_at": _utc_now()}
    def test_source(self, request, history):
        provider = self.providers.get(request.provider)
        if not provider: return RequestDiagnostic(provider=request.provider, message="Provider is not enabled.", tested_at=_utc_now()).to_dict()
        diagnostic = provider.test(request, history).to_dict()
        http_status = str(diagnostic.get("http_status", ""))
        availability = ("available" if http_status in ("200", "LOCAL_OK") and diagnostic.get("parsed_row_count", 0) > 0
                        else "not configured" if http_status in ("NOT_CONFIGURED", "INVALID_CONFIGURATION")
                        else "temporarily unavailable" if http_status in ("429", "503", "NETWORK_ERROR")
                        else "error")
        self.status.write(request.provider, diagnostic, availability)
        return diagnostic

    def search_fred(self, search_text: str, limit: int = 20):
        provider = self.providers.get("fred")
        if not isinstance(provider, FREDProvider):
            raise ProviderError("FRED provider is not enabled.")
        try:
            results, diagnostic = provider.search(search_text, limit)
            self.status.write("fred", diagnostic.to_dict(), "available")
            return results, diagnostic
        except Exception as exc:
            diagnostic = error_diagnostic(exc, "fred") or {}
            status = str(diagnostic.get("http_status", ""))
            availability = "not configured" if status in ("NOT_CONFIGURED", "INVALID_CONFIGURATION") else "temporarily unavailable"
            self.status.write("fred", diagnostic, availability)
            raise


SERVICE = ProviderService()


# ---------------------------------------------------------------------------
# Market Watch snapshots
# ---------------------------------------------------------------------------
# Market Watch deliberately consumes the same provider contract and JsonCache as
# Indicator Analysis.  The UI passes provider/code pairs; this layer owns the
# history request, return calculations and freshness labels.  A future approved
# Bloomberg/Fabric adapter can therefore be registered on ProviderService and
# used here without changing the Market Watch component contract.

def _month_shift(value: dt.date, months: int) -> dt.date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return dt.date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _market_watch_baseline(records: list[dict[str, Any]], target: dt.date | None = None,
                           previous_observation: bool = False) -> float | None:
    baseline = None
    if previous_observation and len(records) > 1:
        baseline = records[-2].get("value")
    elif target is not None:
        for row in reversed(records):
            try:
                if dt.date.fromisoformat(str(row.get("date", ""))[:10]) <= target:
                    baseline = row.get("value"); break
            except ValueError:
                continue
    try:
        value = float(baseline)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _market_watch_change(records: list[dict[str, Any]], latest_value: float,
                         semantic_type: str = "price", target: dt.date | None = None,
                         previous_observation: bool = False) -> float | None:
    baseline = _market_watch_baseline(records, target, previous_observation)
    if baseline is None:
        return None
    latest = float(latest_value)
    if semantic_type in ("rate", "spread"):
        return (latest - baseline) * 100.0
    return None if baseline == 0 else (latest / baseline - 1.0) * 100.0


def market_watch_snapshot(result: dict[str, Any], now: dt.datetime | None = None,
                          spark_points: int = 30) -> dict[str, Any]:
    """Convert one provider result into a latest-available delayed daily snapshot."""
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    records = []
    for row in result.get("records", []):
        try:
            numeric = float(row.get("value")); date = dt.date.fromisoformat(str(row.get("date", ""))[:10])
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            records.append({**row, "date": date.isoformat(), "value": numeric})
    records.sort(key=lambda row: row["date"])
    if not records:
        raise ProviderError("Market Watch received no usable observations.")
    meta = result.get("meta", {}); latest = records[-1]
    latest_date = dt.date.fromisoformat(latest["date"]); latest_value = float(latest["value"])
    semantic_type = str(meta.get("semantic_type") or "price").lower()
    age_days = max(0, (now.date() - latest_date).days)
    if age_days <= 3: freshness, freshness_tone = "Latest daily", "fresh"
    elif age_days <= 7: freshness, freshness_tone = "Delayed", "delayed"
    else: freshness, freshness_tone = "Stale", "stale"
    prior_year_close = dt.date(latest_date.year, 1, 1) - dt.timedelta(days=1)
    spark = records[-max(2, int(spark_points or 30)):]
    def change(**kwargs):
        return _market_watch_change(records, latest_value, semantic_type, **kwargs)
    return {
        "request_id": meta.get("request_id", ""), "provider": meta.get("provider", ""),
        "provider_label": meta.get("provider_label", ""),
        "indicator": meta.get("series_code", meta.get("indicator", "")),
        "label": meta.get("label", meta.get("series_code", "")),
        "asset": meta.get("geography_label", meta.get("geography", "Market")),
        "unit": meta.get("unit", ""), "semantic_type": semantic_type,
        "change_unit": "bp" if semantic_type in ("rate", "spread") else "%",
        "last": latest_value, "as_of": latest_date.isoformat(),
        "change_1d": change(previous_observation=True),
        "change_1w": change(target=latest_date - dt.timedelta(days=7)),
        "change_1m": change(target=_month_shift(latest_date, -1)),
        "change_ytd": change(target=prior_year_close),
        "sparkline": [{"date": row["date"], "value": row["value"]} for row in spark],
        "retrieved_at": meta.get("retrieved_at", ""), "cache_status": meta.get("cache_status", ""),
        "freshness": freshness, "freshness_tone": freshness_tone, "age_days": age_days,
        "warning": meta.get("warning", ""), "source_url": meta.get("source_url", ""),
        "data_basis": "Latest available delayed daily observation",
    }

class MarketWatchService:
    """Provider-neutral, cache-reusing snapshot service for at most 20 rows."""

    def __init__(self, provider_service: ProviderService = SERVICE):
        self.provider_service = provider_service

    @staticmethod
    def _request(item: dict[str, Any]) -> SeriesRequest:
        provider = str(item.get("provider") or "yahoo_market")
        indicator = str(item.get("indicator") or "")
        if not indicator:
            raise ProviderError("Market Watch instrument has no series code.")
        geography = str(item.get("geography") or
                        ("Market" if provider == "yahoo_market" else ""))
        return SeriesRequest(str(item.get("uid") or indicator), provider,
                             geography, indicator, dict(item.get("options") or {}))

    @staticmethod
    def history(now: dt.datetime | None = None) -> HistoryWindow:
        now = now or dt.datetime.now(UTC)
        # Previous calendar-year close is needed for YTD.  An extra year also
        # provides a resilient sparkline/cache window around holidays.
        return HistoryWindow("custom", f"{now.year - 2}-01-01", now.date().isoformat())

    def fetch(self, instruments: Iterable[dict[str, Any]], force: bool = False,
              now: dt.datetime | None = None) -> dict[str, Any]:
        now = now or dt.datetime.now(UTC)
        rows = list(instruments or [])[:MAX_MARKET_WATCH]
        requests_list, errors = [], []
        for item in rows:
            try:
                requests_list.append(self._request(item))
            except Exception as exc:
                errors.append({"request_id": str(item.get("uid", "")),
                               "message": safe_error(exc)})
        if not requests_list:
            return {"instruments": [], "errors": errors,
                    "fetched_at": _utc_now()}

        snapshots = []
        history = self.history(now)
        with ThreadPoolExecutor(max_workers=min(8, len(requests_list))) as pool:
            futures = {pool.submit(self.provider_service.fetch_one, request,
                                   history, force): request
                       for request in requests_list}
            for future in as_completed(futures):
                request = futures[future]
                try:
                    snapshots.append(market_watch_snapshot(future.result(), now))
                except Exception as exc:
                    errors.append({"request_id": request.request_id,
                                   "message": safe_error(exc),
                                   "diagnostic": error_diagnostic(exc, request.provider)})
        order = {request.request_id: index
                 for index, request in enumerate(requests_list)}
        snapshots.sort(key=lambda item: order.get(item["request_id"], 999))
        errors.sort(key=lambda item: order.get(item.get("request_id", ""), 999))
        return {"instruments": snapshots, "errors": errors,
                "fetched_at": _utc_now()}


MARKET_WATCH_SERVICE = MarketWatchService()
