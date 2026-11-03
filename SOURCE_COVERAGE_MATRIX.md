# EMDASH Indicator Analysis — source coverage matrix

| Provider | Implemented coverage | Frequency | Authentication | Live route | Limits |
|---|---|---:|---|---|---|
| World Bank WDI | 13 curated indicators covering growth, inflation, external balance, debt, labour, trade, FDI, reserves, income, savings, money and population | Annual | None | Official country/indicator JSON API with source 2 and targeted dates | Curated only; country availability varies. |
| IMF DataMapper — Annual | `NGDP_RPCH`, `PCPIPCH`, `BCA`, `BCA_NGDPD`, `LUR`, `GGXCNL_NGDP`, `GGXWDG_NGDP` | Annual | None | `www.imf.org/external/datamapper/api/v1/{indicator}/{country}` JSON route | Curated headline annual macro only. DataMapper does not replace SDMX or imply full IMF coverage. WEO observations may contain estimates/projections. |
| IMF SDMX — CPI | Monthly all-items CPI index only | Monthly | Optional organisational subscription key through `EMDASH_IMF_API_KEY` | IMF SDMX 3.0 CPI dataflow; SDMX-CSV primary and SDMX-JSON time-index fallback | No broader IMF/IFS/WEO SDMX coverage claimed. Planned IMF maintenance Oct 24 01:00 EST–Oct 26 08:00 EST can cause temporary 503s. |
| FRED | Curated US rates, Treasury curve/spreads, credit OAS, volatility/financial conditions, CPI, labour, production, GDP and Federal Reserve assets; additional series via search | Daily, weekly, monthly or quarterly by series | Required: `FRED_API_KEY` | Official `fred/series/search` and `fred/series/observations` JSON APIs | FRED aggregates data from many sources; source methodology, revisions and units vary. Search requires a configured key. |
| Yahoo market | Existing curated Brent, WTI, gold, copper, major FX, major equity indices, BTC and ETH | Daily | None | Existing direct Yahoo chart JSON route | Unofficial public endpoint; availability, delay, rate limits and futures rolls apply. |
| Gembridge Excel | User-supplied long-format or wide-format workbook series, including future internal CDS or auction data | User-declared | Local file access | Existing local workbook adapter | Reliability depends on workbook inputs. No CDS or auction observations are fabricated or shipped. |

## Curated FRED series IDs

| Category | Series IDs |
|---|---|
| Policy and Treasury rates | `DFF`, `DGS2`, `DGS10`, `DGS30`, `DFII10` |
| Curve spreads | `T10Y2Y`, `T10Y3M` |
| Credit spreads | `BAMLC0A0CM`, `BAMLH0A0HYM2`, `BAMLEMCBPIOAS` |
| Volatility and conditions | `VIXCLS`, `NFCI`, `STLFSI4` |
| Macro and balance sheet | `CPIAUCSL`, `UNRATE`, `PAYEMS`, `INDPRO`, `GDPC1`, `WALCL` |

## Metadata contract

Every loaded series retains:

- provider and source;
- geography or coverage;
- label and series code;
- frequency, unit and semantic type;
- latest observation and observation count;
- retrieved time and cache status;
- safe request diagnostics when available.

## Temporary failures

- IMF 503: temporary unavailable/maintenance message; no rapid retries; stale-cache fallback where available.
- IMF/FRED 429: rate-limit message; no rapid retries; Retry-After surfaced where supplied; stale-cache fallback.
- FRED key absent: provider reports `NOT_CONFIGURED`; the rest of EMDASH remains usable.
