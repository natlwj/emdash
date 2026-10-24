# EMDASH Data Source Test — one-step instructions

## In-app test

1. Launch EMDASH with the existing `EMDASH.bat`.
2. Open **Indicator Analysis**.
3. Expand **Data sources and diagnostics**.
4. Select **IMF SDMX — CPI**, **World Bank WDI**, **Market Data — Yahoo**, or **Gembridge Excel**.
5. Click **Run Source Test**.
6. Click inside the diagnostic box, press `Ctrl+A`, then `Ctrl+C`.

The copied JSON contains no request headers or secrets. URL query parameters with secret-like names are redacted.

## Required diagnostic fields

- `final_endpoint`
- `http_status`
- `content_type`
- `response_preview`
- `detected_columns`
- `parsed_row_count`
- `available_countries`
- `available_series`
- `message`
- `tested_at`

A zero parsed-row count is not the only error output: the endpoint, HTTP response, columns and available identifiers remain visible for diagnosis.

## IMF interpretation

Expected request shape:

```text
https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/CPI/5.0.0/USA.CPI._T.IX.M
```

Expected primary query parameters and response:

```text
attributes=none
startPeriod=YYYY-MM
endPeriod=YYYY-MM
# dimensionAtObservation must not be present

HTTP 200
Content-Type containing SDMX CSV or text/csv
Columns including COUNTRY, FREQUENCY, TIME_PERIOD and OBS_VALUE
TIME_PERIOD populated with parseable periods
available_countries containing USA for a USA request
parsed_row_count greater than zero
```

If numeric OBS_VALUE rows still have blank TIME_PERIOD cells, EMDASH automatically retries the same key/date query as SDMX-JSON, decodes observation time indexes and records both attempts plus an explicit fallback result.

Common outcomes:

- **401/403:** proxy, IMF API access policy, or optional subscription key requirement. If your organisation has an IMF API subscription key, set `EMDASH_IMF_API_KEY` before launching. The key is sent in a header and excluded from diagnostics.
- **404:** CPI flow version may have changed. Confirm the current CPI version and set `EMDASH_IMF_CPI_VERSION` before launch.
- **HTTP 200, zero rows:** compare the requested key to `detected_columns`, `available_countries`, `available_series`, and `response_preview`. This distinguishes a country/key mismatch from a parser problem.
- **HTML content:** a login, gateway or proxy page is being returned instead of SDMX data.

PowerShell examples:

```powershell
$env:EMDASH_IMF_CPI_VERSION = "5.0.0"
$env:EMDASH_IMF_API_KEY = "YOUR_ORGANISATION_KEY_IF_REQUIRED"
.\EMDASH.bat
```

Do not paste an API key into EMDASH controls or diagnostic output.

## Market-data interpretation

Expected endpoint shape:

```text
https://query1.finance.yahoo.com/v8/finance/chart/BZ=F?...&interval=1d
```

Expected response:

```text
HTTP 200
Content-Type application/json
available_series containing BZ=F for Brent
parsed_row_count greater than zero
```

A 401, 403 or 429 indicates endpoint access or rate limiting. EMDASH will use an existing stale cache when available and show the live failure in Retrieval details.

## World Bank interpretation

Expected endpoint shape:

```text
https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.KD.ZG?...&source=2
```

Expected response:

```text
HTTP 200
Content-Type JSON
available_countries containing USA
available_series containing the requested WDI code
```

## Excel test

Enter workbook path, sheet, optional table name, format and mapping sheet, then click **Load Excel Catalogue**. Select **Gembridge Excel** in Data Source Test and click **Run Source Test**. A successful local test reports `LOCAL_OK`, detected columns, parsed rows and available series IDs.
