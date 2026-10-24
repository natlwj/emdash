# EMDASH Indicator Analysis — focused finishing patch

## Minimal swap for the existing BAT workflow

1. Close EMDASH.
2. Back up the current EMDASH folder or the files being replaced.
3. Extract `EMDASH_indicator_analysis_finishing_patch.zip`.
4. Copy the extracted contents over the existing EMDASH folder, preserving subfolders. Allow Windows to replace matching files.
5. Run this one command in PowerShell from the EMDASH folder:

```powershell
py -3 -m pip install -r requirements.txt
```

6. Double-click the existing `EMDASH.bat`.

No database migration, ingest run or BAT-file change is required.

## Files replaced or added

```text
app.py
indicator_analysis.py
indicator_providers.py
assets/indicator_analysis.css
database_tab.py                       approved label only
requirements.txt
requirements-dev.txt
templates/Gembridge_Indicator_Series_Template.xlsx
tests/test_indicator_providers.py
tests/test_indicator_analysis.py
tests/smoke_app_structure.py
CHANGELOG_INDICATOR_ANALYSIS.md
SOURCE_COVERAGE_MATRIX.md
API_TEST_INSTRUCTIONS.md
VERIFICATION_REPORT.txt
REPLACEMENT_MANIFEST.txt
```

Do not replace `event_study.py`, `mrc.py`, `news_ingest.py`, `core.py`, `emdash.sqlite`, or other backend files.

## IMF verification on the target machine

The primary CPI request no longer sends `dimensionAtObservation=AllDimensions`.

Expected endpoint shape:

```text
https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/CPI/5.0.0/USA.CPI._T.IX.M
```

Expected query parameters:

```text
attributes=none
startPeriod=YYYY-MM
endPeriod=YYYY-MM
```

Test in one step:

1. Open **Indicator Analysis**.
2. Expand **Data sources and diagnostics**.
3. Choose **IMF SDMX — CPI**.
4. Click **Run Source Test**.
5. Copy the diagnostic box with `Ctrl+A`, `Ctrl+C`.

A successful primary response shows dated rows and:

```text
fallback_result: Primary SDMX-CSV succeeded with dated observations.
```

If CSV contains numeric values but blank periods, EMDASH retries SDMX-JSON and decodes observation time indexes. A successful fallback shows:

```text
fallback_result: Primary CSV contained values with blank/unusable periods; SDMX-JSON time-index fallback succeeded.
```

The diagnostic contains every attempt and excludes request headers and secrets.

Optional settings:

```powershell
$env:EMDASH_IMF_CPI_VERSION = "5.0.0"
$env:EMDASH_IMF_API_KEY = "YOUR_KEY_IF_REQUIRED"
```

IMF coverage remains monthly all-items CPI only.

## Transformation rules

Per-series transformations now use both frequency and semantic type.

Examples:

- World Bank real GDP growth and CPI inflation are already `% YoY`; use Level or percentage-point difference rather than applying YoY again.
- IMF CPI is an index and defaults to YoY when newly selected.
- Market prices use Level by default.
- Debt/GDP and current-account/GDP ratios use Level or percentage-point difference.
- Excel CDS spreads inferred from `bp` units use Level by default and changes are formatted in bp.

Global comparison modes remain Native, Indexed, Change from Chart Start and Standardised.

## Focused UI controls

- **Collapse All** and **Expand All** are available beside Add Series.
- Add/Duplicate selects the next unused colour; manual duplicates remain allowed with a warning.
- Market cards show Asset class instead of Geography.
- Rolling window appears only for rolling average or rolling Z-score.
- Scale-dominance warnings appear in Native mode without changing the mode.
- Series Statistics show Source level/Transformed, Previous and contextual Change.
- Underlying data remains collapsed.

## Existing providers retained

No new provider or catalogue expansion is included in this patch. See `SOURCE_COVERAGE_MATRIX.md` for existing implemented coverage and limitations.

## Optional tests

```powershell
py -3 -m pip install -r requirements-dev.txt
py -3 -m pytest -q tests\test_indicator_providers.py tests\test_indicator_analysis.py
py -3 event_study.py
py -3 mrc.py
py -3 news_ingest.py --selftest
```

See `VERIFICATION_REPORT.txt` for the full regression and live-test limits.
