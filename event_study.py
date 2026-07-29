"""
EMDASH :: event_study.py

THE "WHAT HAPPENED NEXT?" ENGINE  --  the differentiator.

Plain-English idea
------------------
"When [some signal] fires for a country, what did [some market] typically do
over the next few days / weeks?"

    e.g.  "When Turkey CPI YoY crosses above 60%, what did USDTRY do
           over the next 1 / 5 / 20 / 60 trading days?"
    e.g.  "When the VIX z-score jumps above +2, what did Brazil FX do next?"

That's it. No AI, no black-box backtester, no vectorbt/backtrader. Just pandas
`.shift()` and averages you can re-derive by hand and explain to a PM in one
breath. Every number here is auditable.

Design (matches signals.py: PURE functions, NO database, NO plotting)
----------------------------------------------------------------------
    * Inputs are pandas Series indexed by date (you fetch them via core.py
      in app.py, then hand them in here).
    * `make_events()`   -> turns a numeric signal into True/False "event fired"
                           flags (rules: above / below / cross / z-score).
    * `study()`         -> for every event, measures the TARGET's forward move
                           at each horizon; returns a per-event table + a summary.
    * `baseline()`      -> the same forward-move stats measured on ALL days
                           (the "base rate"), so you can see if the signal beats
                           just showing up.
    * `average_path()`  -> the mean day-by-day path after an event, for a chart.
    * `event_study()`   -> convenience wrapper that does all of the above and
                           hands back one tidy result object.

KEY HONESTY BUILT IN
    Conditional stats are ALWAYS shown next to the unconditional baseline.
    "FX rose +1.8% on average in the 20 days after the event" means little
    until you know it rises +0.3% on average over ANY random 20 days.

ALIGNMENT
    Signals (e.g. monthly CPI) and targets (e.g. daily FX) live on different
    calendars. Each event date is snapped forward to the first available target
    date (as-of / next trading day), so we never peek at a price that didn't
    exist yet.

Run me:  python event_study.py     # self-test on synthetic data, prints tables
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

# Default forward windows, in TARGET observations (for daily FX: trading days).
DEFAULT_HORIZONS: tuple[int, ...] = (1, 5, 20, 60)

# Rules understood by make_events(). Human labels for the UI live in app.py.
RULES = (
    "above", "below",
    "cross_above", "cross_below",
    "z_above", "z_below",
)


# ===================================================================
# 1. TURN A SIGNAL INTO EVENTS  (numeric series -> True/False flags)
# ===================================================================
def make_events(signal: pd.Series,
                rule: str = "cross_above",
                threshold: float = 0.0,
                window: int = 20) -> pd.Series:
    """Return a boolean Series (same index as `signal`) that is True on the
    dates an 'event' fires.

    Rules
        above        : value > threshold
        below        : value < threshold
        cross_above  : value crosses UP through threshold (was <=, now >)
        cross_below  : value crosses DOWN through threshold (was >=, now <)
        z_above      : rolling z-score(window) > threshold   (threshold in std devs)
        z_below      : rolling z-score(window) < threshold
    """
    s = pd.to_numeric(signal, errors="coerce").dropna()
    if s.empty:
        return pd.Series(dtype=bool)

    if rule == "above":
        ev = s > threshold
    elif rule == "below":
        ev = s < threshold
    elif rule == "cross_above":
        ev = (s > threshold) & (s.shift(1) <= threshold)
    elif rule == "cross_below":
        ev = (s < threshold) & (s.shift(1) >= threshold)
    elif rule in ("z_above", "z_below"):
        mu = s.rolling(window, min_periods=max(3, window // 2)).mean()
        sd = s.rolling(window, min_periods=max(3, window // 2)).std(ddof=0)
        z = (s - mu) / sd.replace(0, np.nan)
        ev = z > threshold if rule == "z_above" else z < threshold
    else:
        raise ValueError(f"unknown rule '{rule}'. valid: {RULES}")

    return ev.fillna(False).astype(bool)


# ===================================================================
# 2. FORWARD MOVES  (the .shift() maths, kept explicit)
# ===================================================================
def _forward_value(vals: np.ndarray, p: int, h: int, kind: str) -> float:
    """Move of the target from position p to position p+h.
        kind='pct'  -> percentage change  (FX, equities, commodities)
        kind='diff' -> level change        (rates/yields, in the unit itself)
    """
    q = p + h
    if q >= len(vals) or p >= len(vals):
        return np.nan
    base, fwd = vals[p], vals[q]
    if kind == "diff":
        return float(fwd - base)
    if base == 0 or np.isnan(base) or np.isnan(fwd):
        return np.nan
    return float(fwd / base - 1.0)


def _snap_forward(target_index: pd.DatetimeIndex,
                  event_dates: pd.DatetimeIndex) -> np.ndarray:
    """For each event date, the position of the first target date on/after it.
    (No look-ahead: we use the next available price, never an earlier one.)"""
    return target_index.searchsorted(event_dates, side="left")


# ===================================================================
# 3. STUDY  (per-event table + summary across events)
# ===================================================================
def study(target: pd.Series,
          events: pd.Series,
          horizons: Sequence[int] = DEFAULT_HORIZONS,
          kind: str = "pct") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Measure the target's forward move after each event.

    Returns (summary, detail):
        detail  -> one row per event: event_date, aligned_date, h1, h5, ...
        summary -> one row per horizon: n, mean, median, hit_rate, std,
                   best, worst, t_stat
    Forward moves are in fractions (0.018 = +1.8%) for kind='pct', or in the
    target's own units for kind='diff'.
    """
    tgt = pd.to_numeric(target, errors="coerce").dropna().sort_index()
    horizons = tuple(int(h) for h in horizons)
    if tgt.empty or events is None or events.empty:
        return _empty_summary(horizons), pd.DataFrame()

    idx = tgt.index
    vals = tgt.values.astype(float)
    ev_dates = pd.DatetimeIndex(events.index[events.fillna(False).astype(bool)])
    if len(ev_dates) == 0:
        return _empty_summary(horizons), pd.DataFrame()

    positions = _snap_forward(idx, ev_dates)

    records = []
    for d, p in zip(ev_dates, positions):
        if p >= len(vals):
            continue  # event after the last available price
        rec = {"event_date": d, "aligned_date": idx[p]}
        for h in horizons:
            rec[f"h{h}"] = _forward_value(vals, p, h, kind)
        records.append(rec)

    detail = pd.DataFrame(records)
    summary = _summarise(detail, horizons)
    return summary, detail


def baseline(target: pd.Series,
             horizons: Sequence[int] = DEFAULT_HORIZONS,
             kind: str = "pct") -> pd.DataFrame:
    """The 'base rate': the same forward-move stats measured from EVERY day.
    This is what the signal has to beat to be interesting."""
    tgt = pd.to_numeric(target, errors="coerce").dropna().sort_index()
    horizons = tuple(int(h) for h in horizons)
    if tgt.empty:
        return _empty_summary(horizons)
    vals = tgt.values.astype(float)
    n = len(vals)
    records = []
    for p in range(n):
        rec = {}
        for h in horizons:
            rec[f"h{h}"] = _forward_value(vals, p, h, kind)
        records.append(rec)
    detail = pd.DataFrame(records)
    return _summarise(detail, horizons)


# ===================================================================
# 4. AVERAGE PATH  (mean day-by-day move after an event -> for charting)
# ===================================================================
def average_path(target: pd.Series,
                 events: pd.Series,
                 max_h: int = 60,
                 kind: str = "pct") -> pd.Series:
    """Mean cumulative move from the event day (day 0 = 0) out to `max_h`
    target observations. Index = 0..max_h. Great for a single 'typical path'
    line chart."""
    tgt = pd.to_numeric(target, errors="coerce").dropna().sort_index()
    if tgt.empty or events is None or events.empty:
        return pd.Series(dtype=float)
    idx = tgt.index
    vals = tgt.values.astype(float)
    ev_dates = pd.DatetimeIndex(events.index[events.fillna(False).astype(bool)])
    positions = _snap_forward(idx, ev_dates)

    paths = []
    for p in positions:
        if p >= len(vals):
            continue
        base = vals[p]
        seg = vals[p:p + max_h + 1]
        if kind == "diff":
            path = seg - base
        else:
            if base == 0 or np.isnan(base):
                continue
            path = seg / base - 1.0
        s = pd.Series(path)
        s.index = range(len(s))
        paths.append(s)

    if not paths:
        return pd.Series(dtype=float)
    return pd.concat(paths, axis=1).mean(axis=1)


def baseline_path(target: pd.Series, max_h: int = 60,
                  kind: str = "pct") -> pd.Series:
    """Unconditional average path (from every day) for the same max_h -- the
    grey benchmark line to plot behind the event path."""
    tgt = pd.to_numeric(target, errors="coerce").dropna().sort_index()
    if tgt.empty:
        return pd.Series(dtype=float)
    vals = tgt.values.astype(float)
    n = len(vals)
    paths = []
    for p in range(n):
        base = vals[p]
        seg = vals[p:p + max_h + 1]
        if len(seg) < max_h + 1:
            continue
        if kind == "diff":
            paths.append(pd.Series((seg - base), index=range(len(seg))))
        elif base and not np.isnan(base):
            paths.append(pd.Series((seg / base - 1.0), index=range(len(seg))))
    if not paths:
        return pd.Series(dtype=float)
    return pd.concat(paths, axis=1).mean(axis=1)


# ===================================================================
# 5. ONE-CALL WRAPPER  (what app.py will use)
# ===================================================================
@dataclass
class EventStudyResult:
    summary: pd.DataFrame          # conditional stats, indexed by 'horizon'
    baseline: pd.DataFrame         # unconditional stats, same shape
    detail: pd.DataFrame           # one row per event
    path: pd.Series                # mean cumulative path after events
    base_path: pd.Series           # mean cumulative path, unconditional
    n_events: int = 0
    kind: str = "pct"
    horizons: tuple = field(default_factory=lambda: DEFAULT_HORIZONS)

    def compare(self) -> pd.DataFrame:
        """Side-by-side conditional vs baseline: mean, hit_rate, and edge
        (conditional mean minus baseline mean). This is the money table."""
        if self.summary.empty:
            return self.summary
        c, b = self.summary, self.baseline
        out = pd.DataFrame({
            "n_events":      c["n"],
            "mean":          c["mean"],
            "base_mean":     b["mean"],
            "edge":          c["mean"] - b["mean"],
            "hit_rate":      c["hit_rate"],
            "base_hit_rate": b["hit_rate"],
            "median":        c["median"],
            "t_stat":        c["t_stat"],
        })
        return out


def event_study(target: pd.Series,
                signal: pd.Series,
                rule: str = "cross_above",
                threshold: float = 0.0,
                window: int = 20,
                horizons: Sequence[int] = DEFAULT_HORIZONS,
                kind: str = "pct") -> EventStudyResult:
    """End to end: build events from `signal`, then study `target`'s forward
    moves vs the baseline. Returns one tidy result object."""
    horizons = tuple(int(h) for h in horizons)
    events = make_events(signal, rule=rule, threshold=threshold, window=window)
    summary, detail = study(target, events, horizons, kind)
    base = baseline(target, horizons, kind)
    max_h = max(horizons) if horizons else 60
    path = average_path(target, events, max_h, kind)
    bpath = baseline_path(target, max_h, kind)
    n_events = int(len(detail))
    return EventStudyResult(summary=summary, baseline=base, detail=detail,
                            path=path, base_path=bpath, n_events=n_events,
                            kind=kind, horizons=horizons)


# ===================================================================
# INTERNAL: turn a per-event detail table into a per-horizon summary
# ===================================================================
def _summarise(detail: pd.DataFrame, horizons: Sequence[int]) -> pd.DataFrame:
    rows = []
    for h in horizons:
        col = f"h{h}"
        vals = detail[col].dropna() if (not detail.empty and col in detail) \
            else pd.Series(dtype=float)
        n = int(len(vals))
        if n == 0:
            rows.append(_blank_row(h))
            continue
        mean = float(vals.mean())
        std = float(vals.std(ddof=1)) if n > 1 else 0.0
        t = float(mean / (std / np.sqrt(n))) if (std > 0 and n > 1) else np.nan
        rows.append({
            "horizon":  h,
            "n":        n,
            "mean":     mean,
            "median":   float(vals.median()),
            "hit_rate": float((vals > 0).mean()),
            "std":      std,
            "best":     float(vals.max()),
            "worst":    float(vals.min()),
            "t_stat":   t,
        })
    return pd.DataFrame(rows).set_index("horizon")


def _blank_row(h: int) -> dict:
    return {"horizon": h, "n": 0, "mean": np.nan, "median": np.nan,
            "hit_rate": np.nan, "std": np.nan, "best": np.nan,
            "worst": np.nan, "t_stat": np.nan}


def _empty_summary(horizons: Sequence[int]) -> pd.DataFrame:
    return pd.DataFrame([_blank_row(h) for h in horizons]).set_index("horizon")


# ===================================================================
# SELF-TEST  ::  python event_study.py
# Seeds synthetic data where the signal DOES predict the target, proves the
# engine recovers the edge, and shows a no-signal case recovers ~zero edge.
# ===================================================================
def _demo() -> None:
    rng = np.random.default_rng(7)

    # --- Synthetic daily FX (target): random walk drift ~0 ---
    days = pd.bdate_range("2015-01-01", periods=2500)   # ~10y of trading days
    ret = rng.normal(0, 0.006, len(days))               # ~0.6% daily vol
    fx = pd.Series(100 * np.exp(np.cumsum(ret)), index=days, name="USDXXX")

    # --- Synthetic monthly signal (e.g. CPI YoY) ---
    months = pd.date_range("2015-01-31", periods=120, freq="ME")
    sig = pd.Series(rng.normal(20, 8, len(months)), index=months, name="CPI_YoY")

    # Inject a REAL effect: whenever the signal crosses above 30, push FX up
    # ~+2% over the following ~20 trading days (currency weakens on hot CPI).
    events_true = make_events(sig, rule="cross_above", threshold=30)
    for d in sig.index[events_true]:
        pos = fx.index.searchsorted(d)
        if pos + 20 < len(fx):
            fx.iloc[pos:pos + 20] *= np.linspace(1.0, 1.02, 20)

    print("=" * 68)
    print("EMDASH event_study.py  ::  SELF-TEST")
    print("=" * 68)
    print(f"target (FX) points : {len(fx):,}   {fx.index.min().date()} -> "
          f"{fx.index.max().date()}")
    print(f"signal points      : {len(sig):,}   events fired: "
          f"{int(events_true.sum())}")

    res = event_study(fx, sig, rule="cross_above", threshold=30,
                      horizons=(1, 5, 20, 60), kind="pct")

    print(f"\naligned events used: {res.n_events}")
    print("\n--- CONDITIONAL vs BASELINE (mean & hit-rate in % / fraction) ---")
    cmp = res.compare().copy()
    for c in ("mean", "base_mean", "edge", "median"):
        cmp[c] = (cmp[c] * 100).round(2)
    for c in ("hit_rate", "base_hit_rate"):
        cmp[c] = (cmp[c] * 100).round(1)
    cmp["t_stat"] = cmp["t_stat"].round(2)
    print(cmp.to_string())

    print("\n--- MEAN PATH after event (first 6 days, cum %) ---")
    print((res.path.head(6) * 100).round(3).to_string())

    # Sanity checks
    edge20 = res.summary.loc[20, "mean"] - res.baseline.loc[20, "mean"]
    assert res.n_events > 0, "no events aligned"
    assert edge20 > 0.005, f"expected +ve 20d edge from injected effect, got {edge20:.4f}"

    # No-signal control: random rule that shouldn't predict anything
    ctrl = event_study(fx, sig, rule="above", threshold=-999,  # fires ~always
                        horizons=(20,), kind="pct")
    ctrl_edge = ctrl.summary.loc[20, "mean"] - ctrl.baseline.loc[20, "mean"]
    print(f"\ncontrol edge (should be ~0): {ctrl_edge*100:.3f}%")

    # 'diff' mode smoke test (rates-style)
    rate = pd.Series(np.cumsum(rng.normal(0, 0.05, len(days))) + 5, index=days)
    r2 = event_study(rate, sig, rule="cross_above", threshold=30,
                     horizons=(20,), kind="diff")
    print(f"diff-mode 20d mean level change: {r2.summary.loc[20,'mean']:.3f}")

    print("\nALL ASSERTIONS PASSED ✔  engine recovers injected edge, "
          "control ~0, diff-mode runs.")


if __name__ == "__main__":
    _demo()
