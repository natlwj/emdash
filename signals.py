"""
EMDASH :: signals.py

THE TRANSFORM TOOLBOX. The only file that does math on the raw numbers.
Raw series in -> readable/comparable series out. Nothing here touches the
database and nothing here scores or ranks countries (that is deferred to a
later regime/scoring module). These are pure functions -- borrowed by
rules_mrc.py, eventstudy.py and app.py so the same math is written once.

MENTAL MODEL
    Raw data by itself is meaningless ("CPI = 110" tells you nothing).
    A transform turns it into something a human can judge:
        yoy(cpi)        -> "+10% inflation"        (react to this)
        momentum(fx,6m) -> "real weakened 8%"      (trend)
        zscore(x)       -> "2.3 std-devs, unusual" (is it noise?)
        corr(a, b)      -> "0.7, they move together"

CONVENTIONS
    * Inputs are pandas Series indexed by date (what core.get_* returns
      once you set the date as the index), OR a DataFrame for panel helpers.
    * Every function is null-safe: gaps are handled, never faked.
    * Percentages are returned in PERCENT (10.0 = 10%), not 0.10.
    * `periods` is measured in ROWS, not calendar time. For monthly data
      12 rows = 1 year; for daily data ~252 rows = 1 year. Helpers below
      (PERIODS_PER_YEAR) give sensible defaults but you pass what you want.

USAGE
    import signals as sig
    s = core.get_series("IDN", "CPI_YOY").set_index("date")["value"]
    infl_yoy = sig.yoy(s, periods=1)      # annual WB data: 1 row = 1 year
    z        = sig.zscore(s, window=20)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Rough rows-per-year by data cadence -- handy defaults for callers.
PERIODS_PER_YEAR = {
    "annual":  1,
    "quarter": 4,
    "month":   12,
    "week":    52,
    "day":     252,   # trading days
}


# ===================================================================
# INTERNAL HELPERS
# ===================================================================
def _as_series(x) -> pd.Series:
    """Coerce input to a float Series; empty Series if nothing usable."""
    if x is None:
        return pd.Series(dtype="float64")
    if isinstance(x, pd.DataFrame):
        # assume a core.get_* frame with columns [date, value]
        if "value" in x.columns:
            s = x.set_index("date")["value"] if "date" in x.columns else x["value"]
        else:
            s = x.iloc[:, 0]
    else:
        s = pd.Series(x)
    return pd.to_numeric(s, errors="coerce")


# ===================================================================
# LEVEL CHANGES  -- % change over N rows
# ===================================================================
def pct_change(series, periods: int = 1):
    """Simple % change over `periods` rows. Returned in percent."""
    s = _as_series(series)
    return s.pct_change(periods) * 100.0


def yoy(series, periods: int = 12):
    """Year-over-year % change. `periods` = rows in one year
    (12 monthly, 4 quarterly, 1 annual, 252 daily)."""
    return pct_change(series, periods)


def qoq(series, periods: int = 1):
    """Quarter-over-quarter % change (periods=1 on quarterly data)."""
    return pct_change(series, periods)


def mom(series, periods: int = 1):
    """Month-over-month % change (periods=1 on monthly data)."""
    return pct_change(series, periods)


def diff(series, periods: int = 1):
    """Absolute change (level, not %). Useful for rates/yields where a
    move from 4% to 5% is '+1 point', not '+25%'."""
    s = _as_series(series)
    return s.diff(periods)


# ===================================================================
# MOMENTUM & TREND
# ===================================================================
def momentum(series, periods: int = 20):
    """% change over the last `periods` rows -- the 'is it trending?' read.
    Default 20 ~ one trading month on daily data."""
    return pct_change(series, periods)


def rolling_mean(series, window: int = 20):
    """Smoothed line (moving average) to strip out day-to-day noise."""
    s = _as_series(series)
    return s.rolling(window, min_periods=max(2, window // 2)).mean()


def rolling_vol(series, window: int = 20, annualize: str | None = None):
    """Rolling volatility = std-dev of % returns. If `annualize` is a key in
    PERIODS_PER_YEAR (e.g. 'day'), scales by sqrt(periods/yr)."""
    s = _as_series(series)
    rets = s.pct_change() * 100.0
    vol = rets.rolling(window, min_periods=max(2, window // 2)).std()
    if annualize and annualize in PERIODS_PER_YEAR:
        vol = vol * np.sqrt(PERIODS_PER_YEAR[annualize])
    return vol


# ===================================================================
# NORMALISATION  -- makes different countries/series comparable
# ===================================================================
def zscore(series, window: int | None = None):
    """How many std-devs from normal? window=None -> whole-history z-score;
    window=N -> rolling z-score (compare 'now' to the last N rows).
    This is the key cross-country comparability tool."""
    s = _as_series(series)
    if window:
        mu = s.rolling(window, min_periods=max(2, window // 2)).mean()
        sd = s.rolling(window, min_periods=max(2, window // 2)).std()
    else:
        mu, sd = s.mean(), s.std()
    return (s - mu) / sd.replace(0, np.nan) if isinstance(sd, pd.Series) \
        else (s - mu) / (sd if sd else np.nan)


def minmax(series, window: int | None = None):
    """Scale to 0..1 (0 = period low, 1 = period high). Handy for gauges."""
    s = _as_series(series)
    if window:
        lo = s.rolling(window, min_periods=2).min()
        hi = s.rolling(window, min_periods=2).max()
    else:
        lo, hi = s.min(), s.max()
    rng = (hi - lo)
    return (s - lo) / rng.replace(0, np.nan) if isinstance(rng, pd.Series) \
        else (s - lo) / (rng if rng else np.nan)


def percentile_rank(series, window: int | None = None):
    """Where does the latest value sit historically? 0..100.
    window=None -> vs full history; window=N -> vs trailing N rows."""
    s = _as_series(series)
    if window:
        return s.rolling(window, min_periods=2).apply(
            lambda w: (w.rank(pct=True).iloc[-1]) * 100.0, raw=False)
    return s.rank(pct=True) * 100.0


# ===================================================================
# RELATIONSHIPS  -- how two series move together
# ===================================================================
def correlation(a, b, window: int | None = None):
    """Correlation between two series (aligned on their shared dates).
    window=None -> single number (full history);
    window=N -> rolling correlation Series (how the relationship evolves)."""
    sa, sb = _as_series(a), _as_series(b)
    df = pd.concat([sa.rename("a"), sb.rename("b")], axis=1).dropna()
    if df.empty:
        return np.nan if window is None else pd.Series(dtype="float64")
    if window:
        return df["a"].rolling(window, min_periods=max(2, window // 2)).corr(df["b"])
    return df["a"].corr(df["b"])


def beta(y, x, window: int | None = None):
    """Sensitivity of y to x (slope of y on x), on % returns.
    e.g. beta(BRL_returns, copper_returns) = 'how much the Real moves
    per 1% copper move'. window=None -> full sample; N -> rolling."""
    ry = _as_series(y).pct_change()
    rx = _as_series(x).pct_change()
    df = pd.concat([ry.rename("y"), rx.rename("x")], axis=1).dropna()
    if df.empty:
        return np.nan if window is None else pd.Series(dtype="float64")
    if window:
        cov = df["y"].rolling(window, min_periods=max(2, window // 2)).cov(df["x"])
        var = df["x"].rolling(window, min_periods=max(2, window // 2)).var()
        return cov / var.replace(0, np.nan)
    cov = df["y"].cov(df["x"])
    var = df["x"].var()
    return cov / var if var else np.nan


# ===================================================================
# CROSS-SECTION  -- one number per country, for a given day (panel in)
# ===================================================================
def cross_section_z(panel: pd.DataFrame) -> pd.DataFrame:
    """Given a wide panel (rows=date, cols=iso3) e.g. from core.get_panel(),
    return the cross-sectional z-score per date: for each day, how does each
    country compare to the OTHER countries that day. Lets you say
    'today Turkey's inflation is +2 std-devs vs the EM set'."""
    if panel is None or panel.empty:
        return pd.DataFrame()
    mu = panel.mean(axis=1)
    sd = panel.std(axis=1).replace(0, np.nan)
    return panel.sub(mu, axis=0).div(sd, axis=0)


# ===================================================================
# SELF-TEST  -- run `python signals.py` to sanity-check the math
# ===================================================================
if __name__ == "__main__":
    idx = pd.date_range("2020-01-31", periods=36, freq="ME")
    # fake monthly CPI index rising ~ +0.8%/mo, plus a wobble
    cpi = pd.Series(100 * (1.008 ** np.arange(36)), index=idx) \
        + np.sin(np.arange(36)) * 0.5
    fx = pd.Series(5.0 + np.linspace(0, 0.4, 36), index=idx)  # LCY weakening

    print("[signals] self-test")
    print("  yoy(cpi, 12) last     :", round(yoy(cpi, 12).iloc[-1], 2), "%")
    print("  mom(cpi, 1) last      :", round(mom(cpi, 1).iloc[-1], 2), "%")
    print("  momentum(fx, 6) last  :", round(momentum(fx, 6).iloc[-1], 2), "%")
    print("  zscore(cpi,12) last   :", round(zscore(cpi, 12).iloc[-1], 2))
    print("  pctile(cpi) last      :", round(percentile_rank(cpi).iloc[-1], 1))
    print("  corr(cpi, fx) full    :", round(correlation(cpi, fx), 2))
    print("  beta(fx, cpi) full    :", round(beta(fx, cpi), 4))
    print("  rolling_vol(fx,6) last:", round(rolling_vol(fx, 6).iloc[-1], 3))
    print("[signals] ok -- all transforms returned numbers.")
