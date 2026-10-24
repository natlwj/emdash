from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
import requests
from openpyxl import Workbook
from openpyxl.worksheet.table import Table

import indicator_providers as ip


class FakeResponse:
    def __init__(self, *, body=None, text="", url="https://provider.test/data", status=200,
                 content_type="application/json"):
        self._body = body
        self.text = text or (json.dumps(body) if body is not None else "")
        self.url = url
        self.status_code = status
        self.content = self.text.encode()
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        full_url = f"{url}?{urlencode(params or [], doseq=True)}" if params else url
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        response.url = full_url
        return response


def world_bank_body(country="USA"):
    return [{"page": 1, "pages": 1, "total": 2}, [
        {"countryiso3code": country, "date": "2024", "value": 2.8,
         "indicator": {"id": "NY.GDP.MKTP.KD.ZG"}, "obs_status": ""},
        {"countryiso3code": country, "date": "2023", "value": 2.5,
         "indicator": {"id": "NY.GDP.MKTP.KD.ZG"}, "obs_status": ""},
    ]]


def imf_csv(country="USA"):
    return f"""STRUCTURE,STRUCTURE_ID,ACTION,COUNTRY,INDEX_TYPE,COICOP_1999,TYPE_OF_TRANSFORMATION,FREQUENCY,TIME_PERIOD,OBS_VALUE,OBS_STATUS
DATAFLOW,IMF.STA:CPI(5.0.0),Information,{country},CPI,_T,IX,M,2024-01,308.417,A
DATAFLOW,IMF.STA:CPI(5.0.0),Information,{country},CPI,_T,IX,M,2024-02,310.326,A
"""


def imf_blank_time_csv(country="USA"):
    return f"""STRUCTURE,STRUCTURE_ID,ACTION,COUNTRY,INDEX_TYPE,COICOP_1999,TYPE_OF_TRANSFORMATION,FREQUENCY,TIME_PERIOD,OBS_VALUE,OBS_STATUS
DATAFLOW,IMF.STA:CPI(5.0.0),Information,{country},CPI,_T,IX,M,,308.417,A
DATAFLOW,IMF.STA:CPI(5.0.0),Information,{country},CPI,_T,IX,M,,310.326,A
"""


def imf_json_fixture():
    return {"data": {
        "dataSets": [{"series": {
            "0:0:0:0:0": {"observations": {"0": [308.417], "1": [310.326]}},
            "1:0:0:0:0": {"observations": {"0": [150.0], "1": [151.0]}},
        }}],
        "structures": [{"dimensions": {
            "series": [
                {"id": "COUNTRY", "values": [{"id": "USA"}, {"id": "CAN"}]},
                {"id": "INDEX_TYPE", "values": [{"id": "CPI"}]},
                {"id": "COICOP_1999", "values": [{"id": "_T"}]},
                {"id": "TYPE_OF_TRANSFORMATION", "values": [{"id": "IX"}]},
                {"id": "FREQUENCY", "values": [{"id": "M"}]},
            ],
            "observation": [{"id": "TIME_PERIOD", "values": [
                {"id": "2024-01"}, {"id": "2024-02"}
            ]}],
        }}],
    }}


def yahoo_body(symbol="BZ=F"):
    return {"chart": {"result": [{
        "meta": {"symbol": symbol},
        "timestamp": [1704067200, 1704153600],
        "indicators": {"quote": [{"close": [75.1, 76.4]}]},
    }], "error": None}}


def test_history_windows_and_secret_scrubbing():
    today = ip.dt.date(2026, 10, 23)
    assert ip.HistoryWindow("5y").bounds(today) == ("2021-01-01", "2026-10-23")
    assert ip.HistoryWindow("max").bounds(today) == (None, None)
    with pytest.raises(ip.ProviderError):
        ip.HistoryWindow("custom", None, "2026-01-01").bounds(today)
    safe = ip.sanitize_url("https://x.test/data?api_key=secret&start=2020")
    assert "secret" not in safe and "%5Bredacted%5D" in safe


def test_world_bank_targeted_request_and_diagnostic():
    session = FakeSession([FakeResponse(body=world_bank_body())])
    result = ip.WorldBankProvider(session).fetch(
        ip.SeriesRequest("a", "world_bank", "USA", "NY.GDP.MKTP.KD.ZG"),
        ip.HistoryWindow("custom", "2020-01-01", "2024-12-31"),
    )
    assert [row["period"] for row in result.records] == ["2023", "2024"]
    assert session.calls[0]["params"]["date"] == "2020:2024"
    assert result.diagnostic.http_status == "200"
    assert result.diagnostic.parsed_row_count == 2
    assert result.diagnostic.available_countries == ["USA"]
    assert result.diagnostic.available_series == ["NY.GDP.MKTP.KD.ZG"]


def test_imf_current_sdmx_request_columns_and_identifiers():
    session = FakeSession([FakeResponse(text=imf_csv(), content_type="application/vnd.sdmx.data+csv;version=2.0.0")])
    result = ip.IMFSDMXProvider(session).fetch(
        ip.SeriesRequest("b", "imf_sdmx", "USA", "CPI_ALL_ITEMS_INDEX_M"),
        ip.HistoryWindow("custom", "2024-01-01", "2024-12-31"),
    )
    call = session.calls[0]
    assert call["url"].endswith("/IMF.STA/CPI/5.0.0/USA.CPI._T.IX.M")
    assert call["headers"]["Accept"] == "application/vnd.sdmx.data+csv;version=2.0.0"
    assert ("attributes", "none") in call["params"]
    assert not any(key == "dimensionAtObservation" for key, _value in call["params"])
    assert result.diagnostic.detected_columns[:4] == ["STRUCTURE", "STRUCTURE_ID", "ACTION", "COUNTRY"]
    assert result.diagnostic.available_countries == ["USA"]
    assert result.diagnostic.available_series == ["CPI"]
    assert result.diagnostic.parsed_row_count == 2


def test_imf_zero_matching_rows_retains_diagnostic_not_generic_error():
    provider = ip.IMFSDMXProvider(FakeSession([
        FakeResponse(text=imf_csv("CAN"), content_type="application/vnd.sdmx.data+csv;version=2.0.0")
    ]))
    with pytest.raises(ip.ProviderError) as captured:
        provider.fetch(ip.SeriesRequest("b", "imf_sdmx", "USA", "CPI_ALL_ITEMS_INDEX_M"), ip.HistoryWindow("5y"))
    diag = captured.value.diagnostic
    assert diag is not None
    assert diag.http_status == "200"
    assert diag.parsed_row_count == 0
    assert diag.available_countries == ["CAN"]
    assert "no dated matching CPI observations" in diag.message


def test_imf_blank_time_csv_uses_json_time_index_fallback():
    session = FakeSession([
        FakeResponse(text=imf_blank_time_csv(), content_type="application/vnd.sdmx.data+csv;version=2.0.0"),
        FakeResponse(body=imf_json_fixture(), content_type="application/vnd.sdmx.data+json;version=2.0.0"),
    ])
    result = ip.IMFSDMXProvider(session).fetch(
        ip.SeriesRequest("b", "imf_sdmx", "USA", "CPI_ALL_ITEMS_INDEX_M"),
        ip.HistoryWindow("custom", "2024-01-01", "2024-12-31"),
    )
    assert [row["period"] for row in result.records] == ["2024-01", "2024-02"]
    assert len(session.calls) == 2
    assert session.calls[0]["headers"]["Accept"].endswith("csv;version=2.0.0")
    assert session.calls[1]["headers"]["Accept"].endswith("json;version=2.0.0")
    assert all(not any(key == "dimensionAtObservation" for key, _value in call["params"])
               for call in session.calls)
    diagnostic = result.diagnostic.to_dict()
    assert len(diagnostic["attempts"]) == 2
    assert diagnostic["attempts"][0]["parsed_row_count"] == 0
    assert "fallback succeeded" in diagnostic["fallback_result"]
    assert result.meta["imf_fallback"] == "sdmx_json_time_index"


def test_imf_json_time_index_multiple_countries_and_dimension_order():
    usa, parsed_usa = ip.IMFSDMXProvider.parse_json(imf_json_fixture(), "USA")
    can, parsed_can = ip.IMFSDMXProvider.parse_json(imf_json_fixture(), "CAN")
    assert [row["value"] for row in usa] == pytest.approx([308.417, 310.326])
    assert [row["value"] for row in can] == pytest.approx([150.0, 151.0])
    assert parsed_usa["columns"][:5] == [
        "COUNTRY", "INDEX_TYPE", "COICOP_1999",
        "TYPE_OF_TRANSFORMATION", "FREQUENCY",
    ]
    assert parsed_usa["countries"] == ["CAN", "USA"]
    assert parsed_can["series"] == ["CPI"]


def test_imf_blank_time_values_are_never_reported_as_generic_no_observations():
    session = FakeSession([
        FakeResponse(text=imf_blank_time_csv(), content_type="text/csv"),
        FakeResponse(body={"data": {"dataSets": [], "structures": []}},
                     content_type="application/json"),
    ])
    with pytest.raises(ip.ProviderError) as captured:
        ip.IMFSDMXProvider(session).fetch(
            ip.SeriesRequest("b", "imf_sdmx", "USA", "CPI_ALL_ITEMS_INDEX_M"),
            ip.HistoryWindow("5y"),
        )
    message = str(captured.value)
    assert "numeric values" in message and "blank/unusable TIME_PERIOD" in message
    assert "no observations" not in message.lower()
    assert len(captured.value.diagnostic.attempts) == 2


def test_imf_malformed_response_exposes_detected_columns():
    provider = ip.IMFSDMXProvider(FakeSession([
        FakeResponse(text="COUNTRY,VALUE\nUSA,1\n", content_type="text/csv")
    ]))
    with pytest.raises(ip.ProviderError) as captured:
        provider.fetch(ip.SeriesRequest("b", "imf_sdmx", "USA", "CPI_ALL_ITEMS_INDEX_M"), ip.HistoryWindow("5y"))
    assert captured.value.diagnostic.detected_columns == ["COUNTRY", "VALUE"]


def test_market_catalogue_and_yahoo_parser_diagnostic():
    required = {"BRENT", "WTI", "GOLD", "COPPER", "EURUSD", "USDJPY", "SPX", "NIKKEI", "BTCUSD", "ETHUSD"}
    assert required <= set(ip.MARKET_INDICATORS)
    provider = ip.YahooMarketProvider(FakeSession([FakeResponse(body=yahoo_body())]))
    result = provider.fetch(ip.SeriesRequest("m", "yahoo_market", "Market", "BRENT"), ip.HistoryWindow("5y"))
    assert [row["value"] for row in result.records] == pytest.approx([75.1, 76.4])
    assert result.meta["unit"] == "USD/bbl"
    assert result.diagnostic.available_series == ["BZ=F"]
    assert result.diagnostic.detected_columns == ["timestamp", "close"]


def make_excel(path: Path, wide=False):
    wb = Workbook(); ws = wb.active; ws.title = "Data_Wide" if wide else "Data_Long"
    if wide:
        ws.append(["date", "SERIES_A", "SERIES_B"])
        ws.append(["2024-01-01", 1.0, 10.0]); ws.append(["2024-02-01", 2.0, 11.0])
        ws.add_table(Table(displayName="GembridgeWide", ref="A1:C3"))
        mp = wb.create_sheet("Mapping")
        mp.append(["series_id", "unit", "frequency", "source", "geography", "label"])
        mp.append(["SERIES_A", "bps", "Monthly", "Internal", "Brazil", "Brazil CDS sample"])
        mp.append(["SERIES_B", "%", "Monthly", "Internal", "Mexico", "Auction yield sample"])
    else:
        ws.append(ip.GembridgeExcelProvider.REQUIRED_LONG)
        ws.append(["2024-01-01", "SERIES_A", 1.0, "bps", "Monthly", "Internal", "Brazil", "Brazil CDS sample"])
        ws.append(["2024-02-01", "SERIES_A", 2.0, "bps", "Monthly", "Internal", "Brazil", "Brazil CDS sample"])
        ws.add_table(Table(displayName="GembridgeSeries", ref="A1:H3"))
    wb.save(path)


def test_excel_long_discovery_fetch_and_validation(tmp_path):
    path = tmp_path / "long.xlsx"; make_excel(path)
    catalog, diag = ip.GembridgeExcelProvider.discover(str(path), "Data_Long", "GembridgeSeries", "long", "Mapping")
    assert catalog[0]["series_id"] == "SERIES_A"
    assert diag.http_status == "LOCAL_OK" and diag.parsed_row_count == 2
    request = ip.SeriesRequest("x", "gembridge_excel", "", "SERIES_A",
                               {"path": str(path), "sheet": "Data_Long", "table": "GembridgeSeries", "format": "long", "mapping_sheet": "Mapping"})
    result = ip.GembridgeExcelProvider().fetch(request, ip.HistoryWindow("max"))
    assert len(result.records) == 2 and result.meta["unit"] == "bps"


def test_excel_wide_with_mapping(tmp_path):
    path = tmp_path / "wide.xlsx"; make_excel(path, wide=True)
    catalog, diag = ip.GembridgeExcelProvider.discover(str(path), "Data_Wide", "GembridgeWide", "wide", "Mapping")
    assert {row["series_id"] for row in catalog} == {"SERIES_A", "SERIES_B"}
    assert next(row for row in catalog if row["series_id"] == "SERIES_B")["label"] == "Auction yield sample"
    assert diag.available_countries == ["Brazil", "Mexico"]


def test_excel_missing_columns_has_clear_error(tmp_path):
    path = tmp_path / "bad.xlsx"; wb = Workbook(); wb.active.append(["date", "value"]); wb.save(path)
    with pytest.raises(ip.ProviderError) as captured:
        ip.GembridgeExcelProvider.discover(str(path), "Sheet", "", "long", "Mapping")
    assert "does not match detected wide format" in str(captured.value)


def test_cache_and_stale_fallback_preserve_live_error_diagnostic(tmp_path):
    cache = ip.JsonCache(tmp_path, ttl_hours=12)
    request = ip.SeriesRequest("a", "world_bank", "USA", "NY.GDP.MKTP.KD.ZG")
    service = ip.ProviderService({"world_bank": ip.WorldBankProvider(FakeSession([FakeResponse(body=world_bank_body())]))}, cache)
    live = service.fetch_one(request, ip.HistoryWindow("5y")); cached = service.fetch_one(request, ip.HistoryWindow("5y"))
    assert live["meta"]["cache_status"] == "live" and cached["meta"]["cache_status"] == "fresh cache"
    service.providers["world_bank"] = ip.WorldBankProvider(FakeSession([requests.ConnectionError("offline")]))
    stale = service.fetch_one(request, ip.HistoryWindow("5y"), force=True)
    assert stale["meta"]["cache_status"] == "stale cache"
    assert stale["meta"]["live_error_diagnostic"]["message"]
    assert stale["meta"]["live_error_diagnostic"]["final_endpoint"].startswith("https://api.worldbank.org/")
    assert stale["meta"]["live_error_diagnostic"]["http_status"] == "NETWORK_ERROR"


def test_source_test_is_copyable_and_secret_free():
    provider = ip.IMFSDMXProvider(FakeSession([FakeResponse(text=imf_csv(), content_type="text/csv")]))
    service = ip.ProviderService({"imf_sdmx": provider}, ip.JsonCache(Path("/tmp/unused-emdash-test")))
    diag = service.test_source(ip.SeriesRequest("test", "imf_sdmx", "USA", "CPI_ALL_ITEMS_INDEX_M"), ip.HistoryWindow("5y"))
    text = json.dumps(diag)
    assert "final_endpoint" in diag and "parsed_row_count" in diag
    assert "USA.CPI._T.IX.M" in text
    assert "secret" not in text.lower()


def test_fetch_many_supports_eight_series_and_preserves_order(tmp_path):
    class EchoProvider(ip.SeriesProvider):
        provider_id = "echo"
        def fetch(self, request, history):
            diag = ip.RequestDiagnostic(provider="echo", requested_series=request.indicator,
                                        final_endpoint=f"internal://{request.indicator}",
                                        http_status="OK", content_type="application/x-test",
                                        detected_columns=["date", "value"], parsed_row_count=1,
                                        available_series=[request.indicator], tested_at=ip._utc_now())
            meta = {"request_id": request.request_id, "provider": "echo",
                    "provider_label": "Echo", "source": "Test", "source_url": "",
                    "geography": "", "geography_label": "Test", "indicator": request.indicator,
                    "series_code": request.indicator, "label": request.indicator,
                    "description": "", "frequency": "Daily", "unit": "Index",
                    "dataset_version": "", "notes": "", "request_url": diag.final_endpoint,
                    "retrieved_at": ip._utc_now(), "latest_period": "2026-01-01",
                    "latest_value": 1.0, "observations": 1}
            return ip.ProviderResult([{"date": "2026-01-01", "period": "2026-01-01",
                                       "value": 1.0, "is_projection": False,
                                       "observation_status": ""}], meta, diag)
    service = ip.ProviderService({"echo": EchoProvider(FakeSession([]))}, ip.JsonCache(tmp_path))
    requests_ = [ip.SeriesRequest(str(i), "echo", "", f"S{i}") for i in range(8)]
    result = service.fetch_many(requests_, ip.HistoryWindow("max"))
    assert [series["meta"]["request_id"] for series in result["series"]] == [str(i) for i in range(8)]
    assert not result["errors"]


def test_shipped_excel_template_is_valid_long_format():
    template = Path(__file__).resolve().parents[1] / "templates" / "Gembridge_Indicator_Series_Template.xlsx"
    catalog, diag = ip.GembridgeExcelProvider.discover(
        str(template), "Data_Long", "GembridgeSeries", "long", "Mapping"
    )
    assert catalog[0]["series_id"] == "SAMPLE_SERIES_A"
    assert diag.parsed_row_count == 3
    assert "not real data" in diag.response_preview
