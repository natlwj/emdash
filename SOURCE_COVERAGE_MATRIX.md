# EMDASH Indicator Analysis — source coverage matrix

| Provider | Implemented catalogue | Geography / asset selection | Frequency | Retrieval implementation | Automated verification | Live verification in build sandbox | Important limits |
|---|---|---|---|---|---|---|---|
| World Bank WDI | 13 curated indicators: real GDP growth, CPI inflation, current account, central-government debt, unemployment, exports, imports, FDI, reserves, GDP per capita, savings, broad money and population | EMDASH country list, subject to WDI availability | Annual | Official `api.worldbank.org/v2/country/{ISO3}/indicator/{code}` JSON request with source 2 and targeted date bounds | URL/query assertions, representative JSON parsing, metadata, diagnostics, caching and zero-row handling | Attempted; sandbox policy returned HTTP 403. Diagnostic captured endpoint, status, content type and preview. | Curated only. No claim of the complete World Bank indicator catalogue. Country coverage differs by indicator. |
| IMF SDMX 3.0 CPI | Monthly all-items CPI index only | EMDASH country ISO3 codes, subject to IMF CPI availability | Monthly | `api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/CPI/5.0.0/{ISO3}.CPI._T.IX.M`, primary SDMX-CSV 2.0 with `attributes=none` and no `dimensionAtObservation`; automatic SDMX-JSON time-index fallback when numeric CSV rows have blank periods | Exact endpoint/key/header assertions; blank-period regression from the target-machine HTTP 200 diagnostic; CSV and JSON parsing; USA/Canada dimension fixtures; per-attempt diagnostics | Target machine proved the endpoint/key returned HTTP 200 and numeric CPI values; the former AllDimensions parameter produced blank periods. The finishing patch removes it. Final dated-live validation remains a target-machine step. | No claim of full IMF, WEO or IFS coverage. Flow version can be overridden with `EMDASH_IMF_CPI_VERSION`. Optional subscription key can be supplied with `EMDASH_IMF_API_KEY`; it is never written to diagnostics. |
| Yahoo chart market data | Brent, WTI, gold, copper; EUR/USD, GBP/USD, USD/JPY, AUD/USD; S&P 500, Nasdaq Composite, DJIA, Nikkei 225, Hang Seng; BTC/USD and ETH/USD | Curated ticker list | Daily closes | Direct Yahoo Finance chart JSON endpoint; explicit ticker, epoch bounds and daily interval | URL/query and parser tests, null-close handling, units, identifiers, diagnostics and cache behavior | Attempted; sandbox policy returned HTTP 403. Must be source-tested on the EMDASH machine before presentation. | Unofficial public Yahoo endpoint, not an exchange or official statistical source. Subject to availability, rate limits, delayed data and futures roll effects. No investment-grade entitlement is implied. |
| Gembridge Excel | Any user-provided series in documented long format; wide format supported with optional Mapping sheet | Workbook metadata | User-declared: Daily, Weekly, Monthly, Quarterly, Annual, Event or Irregular | Local `.xlsx` file, configurable path, sheet, optional Excel table, format and mapping sheet | Long/wide ingestion, table selection, required-column validation, mapping, date/value validation, catalogue discovery, filtering and shipped-template tests | Fully tested locally with generated workbooks and the shipped template. | Values are only as reliable as the workbook. EMDASH does not fabricate CDS or auction observations. The sample rows are explicitly labelled illustrative and must be replaced or deleted. |

## Per-series metadata contract

Every loaded series supplies:

- source and provider;
- geography or asset;
- indicator label and code;
- frequency and unit;
- retrieved time and request URL or workbook location;
- latest observation and observation count;
- live, fresh-cache or stale-cache status;
- a copyable diagnostic record where available.

## Future provider examples

The same provider contract can add SQL-fed CDS, sovereign-auction, internal risk, or approved market data. These are extension examples only; no CDS or sovereign-auction observations are included in this release.
