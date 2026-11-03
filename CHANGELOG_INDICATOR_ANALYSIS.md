# EMDASH Data Coverage & Updates — provider catalogue enhancement

## Source-coverage interface

- Replaced the high-level Indicator Analysis source table with six individually collapsible provider summaries.
- Initial view remains compact; all provider details are closed by default.
- Added **Expand All** and **Collapse All** controls.
- Each summary shows:
  - provider name;
  - plain-English purpose;
  - live API versus workbook/internal type;
  - latest dynamic availability/configuration status;
  - provider-universe scope;
  - current EMDASH-exposed scope.

## Full EMDASH catalogues

Expanded details now enumerate every currently exposed item:

- World Bank WDI — 13 indicators
- IMF DataMapper — 7 annual indicators
- IMF SDMX — 1 monthly CPI route
- FRED — 19 curated series plus any persisted searched FRED series
- Yahoo market data — 15 instruments
- Gembridge Excel — dynamically discovered configured-workbook series

Each row shows, where available:

- display label;
- provider code, ticker or series ID;
- category;
- unit;
- frequency;
- geography or asset class;
- earliest available/retrieved observation;
- latest available/retrieved observation;
- metadata/retrieval timestamp;
- concise source or methodology note.

Unqueried coverage is labelled **Not yet queried** rather than inferred or hard-coded.

## Provider-specific detail

- World Bank is described as cross-country development/macro WDI data. All 13 curated indicators are listed individually; retrieved country/date coverage is used when available.
- IMF DataMapper lists all 7 implemented annual headline series with semantic units and dynamic dates.
- IMF SDMX explains its broader multidimensional universe while listing only the one tested monthly all-items CPI route.
- FRED lists all 19 curated series. Observation dates/metadata appear after retrieval or FRED search metadata; otherwise fields show Not yet queried. Additional search remains described separately.
- Yahoo instruments are grouped through asset-class categories and include the public-feed methodology caveat.
- Gembridge Excel lists workbook-discovered series only when configured. The empty state documents the accepted schema and frequencies and creates no fake series.

## Dynamic status and coverage

- Status continues to use actual configuration and latest source-test information.
- Current target states remain honest for World Bank, Yahoo, IMF DataMapper, IMF SDMX, FRED and Excel.
- Observation coverage is internally aggregated by provider/series to enrich catalogue rows only.
- The UI is not a cache inventory and does not enumerate files or imply any relationship to `emdash.sqlite`.

## Preserved behavior

Unchanged:

- Indicator Analysis UI and calculations
- provider retrieval logic, except Excel catalogue start/end metadata and FRED search last-updated metadata now being retained for this view
- current state migration/default workspace
- World Bank/Yahoo functionality
- IMF/FRED diagnostics
- Gembridge Excel ingestion
- Event Study
- MRC
- News Feed
- `core.py`
- `emdash.sqlite`
- existing Data Coverage pull panels, matrices, controls and backend computations
