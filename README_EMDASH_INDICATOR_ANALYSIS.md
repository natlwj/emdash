# EMDASH Data Coverage source-catalogue patch

## Minimal swap

1. Close EMDASH.
2. Extract `EMDASH_data_coverage_catalogue_patch.zip`.
3. Copy the extracted files over the existing EMDASH folder, preserving `assets` and `tests`.
4. Double-click the existing `EMDASH.bat`.

Requirements did not change. No pip command, database migration, cache deletion, ingest run or BAT-file edit is needed.

## What changes

Only the Indicator Analysis section inside **Data Coverage & Updates** is enhanced.

The section now contains compact collapsed summaries for:

- World Bank WDI
- IMF DataMapper — Annual
- IMF SDMX — CPI
- FRED
- Market Data — Yahoo
- Gembridge Excel

Expand a provider to view the complete EMDASH-exposed catalogue for that source. Use **Expand All** or **Collapse All** when needed.

## How to read it

Each provider distinguishes:

- **Provider universe** — the broader source/database context;
- **Current EMDASH catalogue** — exactly what this EMDASH release exposes.

Individual rows show label, code/ticker/ID, category, unit, frequency, geography/asset, dynamic earliest/latest dates, metadata/retrieval time and a concise note.

If a series has not been queried, coverage is shown as **Not yet queried**. Dates are not invented.

## Provider details

- World Bank: all 13 curated WDI indicators.
- IMF DataMapper: all 7 implemented annual headline macro indicators.
- IMF SDMX: the single tested monthly all-items CPI route, with broader SDMX context clearly separated.
- FRED: all 19 curated series; additional search remains supported in Indicator Analysis. Metadata dates appear when retrieved/search metadata exists. A missing key remains **API key required / not configured**.
- Yahoo: all 15 curated commodities, FX, equity-index and crypto instruments, with a public-feed caveat.
- Gembridge Excel: configured workbook series only. When absent, the panel shows the accepted schema/frequencies instead of fake examples.

## Important separation

This remains a provider catalogue and coverage view. It does not list Indicator Analysis cache files or present them as a separate inventory. It does not imply that the Indicator Analysis file cache belongs to `emdash.sqlite`.

All existing SQLite warehouse coverage, pull panels, matrices, source sorting and Refresh controls remain unchanged.

## Optional verification

```powershell
py -3 -m pip install -r requirements-dev.txt
py -3 -m pytest -q tests\test_indicator_providers.py tests\test_indicator_analysis.py tests\test_indicator_coverage.py
```

See `CHANGELOG_INDICATOR_ANALYSIS.md` and `VERIFICATION_REPORT.txt` for full details.
