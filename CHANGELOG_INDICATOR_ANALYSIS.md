# EMDASH Indicator Analysis — focused finishing patch

## IMF CPI live retrieval — highest-priority repair

- Removed `dimensionAtObservation=AllDimensions` from the primary IMF CPI request.
- Primary request now uses only:
  - the existing CPI key `COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY`;
  - `attributes=none`;
  - `startPeriod` and `endPeriod`;
  - standard SDMX-CSV 2.0 response headers.
- Added regression coverage for the target-machine response: HTTP 200, numeric `OBS_VALUE`, valid `COUNTRY=USA` and `INDEX_TYPE=CPI`, but blank `TIME_PERIOD` and zero parsed rows.
- Numeric values with blank/unparseable periods are no longer reported as generic “no observations.”
- When the CSV contains values but unusable periods, EMDASH automatically retries the same endpoint/key/date query as SDMX-JSON 2.0.
- Added SDMX-JSON time-index decoding for dated observations.
- Diagnostics preserve every attempt, including endpoint, HTTP status, content type, preview, fields, row count, countries, series identifiers and explicit fallback result.
- Added representative USA and Canada fixtures to validate country decoding and dimension order.
- IMF scope remains monthly all-items CPI only. No broader IMF coverage is claimed.

## Semantic transformation safeguards

- Added semantic types to series metadata: index, price, raw level, growth rate, rate, ratio, spread, stock, flow and event.
- Curated provider series now carry semantic metadata.
- Excel series infer semantic type from unit/label; an optional `semantic_type` metadata column is recognised when provided.
- Transformation menus now depend on frequency and semantic type.
- Existing `% YoY` growth/inflation series no longer offer another YoY/MoM/QoQ/period-percent transformation.
- Growth rates, rates and ratios use Level, percentage-point difference, rolling average and rolling Z-score.
- CPI index defaults to YoY when newly selected.
- Market prices, reserves/stocks and CDS-style spreads default to Level.
- Added percentage-point difference with explicit `pp` units.
- Units distinguish percentages, percentage points, basis points, prices and indexes.

## Focused interface fixes

- Removed the Window/Colour label collision through responsive grid sizing, wrapped labels and hiding the rolling-window input unless a rolling transformation is selected.
- Market series show an Asset class display instead of a meaningless Geography selector.
- Excel series show geography from workbook metadata.
- Added Collapse All and Expand All.
- Newly added and duplicated cards open expanded; collapsed state remains in persisted series configuration.
- Add and Duplicate automatically use the next unused EMDASH colour.
- Manual duplicate colours remain allowed and produce a visible warning.
- Collapsed headers retain series label, source, frequency, transformation and colour marker.

## Chart and statistics correctness

- Added Native-mode scale-dominance detection for same-unit series. It warns when one series is at least 100× another without changing the selected mode.
- Native mode still uses at most two compatible units with left/right axes and blocks more than two units.
- No interpolation, forward fill or silent mode changes were added.
- Series Statistics now include Previous and contextual Change.
- Change uses percentage points for percentage/rate series and basis points for spread series.
- Formatting is contextual for prices, FX, indexes, percentages, pp, bp and large values.
- Statistics explicitly identify Source level versus Transformed values.
- Underlying data remains collapsed by default.

## Scope deliberately unchanged

No new provider or instrument catalogue was added. This patch retains the next release’s:

- curated World Bank WDI provider;
- curated Yahoo market provider;
- Gembridge Excel long/wide provider;
- market and workbook catalogues.

## Protected areas

Unchanged:

- Event Study
- MRC
- News Feed
- `event_study.py`
- `mrc.py`
- `news_ingest.py`
- `core.py`
- `emdash.sqlite`
- Data Coverage backend logic

`database_tab.py` retains only the approved user-facing label change to **Data Coverage & Updates**.
