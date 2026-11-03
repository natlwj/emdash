# EMDASH Data Source Test instructions

## One-step in-app test

1. Launch with the existing `EMDASH.bat`.
2. Open **Indicator Analysis**.
3. Expand **Data sources and diagnostics**.
4. Select a provider.
5. Click **Run Source Test**.
6. Copy the complete diagnostic box with `Ctrl+A`, `Ctrl+C`.

The diagnostic excludes request headers and redacts API keys.

## IMF DataMapper — Annual

Expected endpoint shape:

```text
https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH/USA?periods=...
```

Expected successful diagnostic:

```text
HTTP 200
content type JSON
available_countries includes USA
available_series includes the selected indicator
parsed_row_count > 0
fallback_result: DataMapper JSON route succeeded.
```

DataMapper covers only the curated annual headline series listed in the coverage matrix.

## IMF SDMX — CPI

Expected endpoint shape:

```text
https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/CPI/5.0.0/USA.CPI._T.IX.M
```

Primary query parameters:

```text
attributes=none
startPeriod=YYYY-MM
endPeriod=YYYY-MM
```

`dimensionAtObservation` must not be present.

If primary CSV values have blank periods, EMDASH requests SDMX-JSON and decodes the time index. Diagnostics retain both attempts.

### IMF 503 during current maintenance

The IMF officially announced maintenance from Saturday October 24, 2026 01:00 EST through Monday October 26, 2026 08:00 EST, with intermittent outages or inability to access data. An HTTP 503 during this window is treated as temporary unavailability, not proof that the query is invalid. EMDASH avoids rapid retries and uses stale cache where available.

## FRED

### Key setup

Persistent user setting for double-click BAT use:

```powershell
setx FRED_API_KEY "YOUR_32_CHARACTER_FRED_KEY"
```

Restart File Explorer/PowerShell before launching EMDASH.

Current session only:

```powershell
$env:FRED_API_KEY = "YOUR_32_CHARACTER_FRED_KEY"
.\EMDASH.bat
```

### Source test

Expected observations endpoint:

```text
https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key=[redacted]&file_type=json...
```

Successful diagnostics show HTTP 200, observation fields, numeric parsed rows and the selected series identifier.

When no key is set:

```text
http_status: NOT_CONFIGURED
message: FRED API key is not configured...
```

This does not block other providers.

### Search test

1. Enter a term in **FRED series search**.
2. Click **Search FRED**.
3. Confirm the status reports returned series.
4. Open a series card, choose FRED, and select a search result.

Search uses the official `fred/series/search` endpoint; observations use `fred/series/observations`.

## Temporary errors

- IMF 503: maintenance/unavailable message, no rapid retry, stale-cache fallback.
- IMF/FRED 429: rate-limit message, no rapid retry, Retry-After surfaced when supplied.
- FRED 503: temporary-unavailable message and stale-cache fallback.
- Other provider errors remain available in **Retrieval details and errors**.
