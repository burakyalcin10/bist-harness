"""Pre-registered studies of Scenarios 1 to 3 (``docs/preregistration.md``, section 3).

Each study takes the price data of one research period and returns plain numbers. The
definitions are fixed by the protocol; the choices it left open were made before the
test period was run and are recorded in ``docs/decision-log.md``:

* Scenario 1: an outcome counts only if its 10-day window ends inside the period; the
  peer median of the outcome leaves the stock itself out (as the Scenario 4 reaction).
* Scenario 2: for ``WEEKDAY_MEANS`` the "excess" is the mean of the discovery period's
  best weekday minus the mean of all days, measured for that same weekday in the test
  period. The test-period half is computed only in a test run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from bist_harness.tools.calendar_patterns import PATTERNS, _edge, evaluate_pattern
from bist_harness.tools.events import (
    DIRECTIONS,
    EVENT_TYPES,
    counted_mask,
    effective_direction,
    event_records,
    sample_warning,
)
from bist_harness.tools.indicators import add_all_indicators

LAG_PRIMARY = -0.05  # 20-day lag score at or below -5 percentage points
OUTCOME_DAYS = 10
EPISODE_GAP_DAYS = 10
ALPHA = 0.05
HORIZONS = (1, 3, 5, 10)
REGIME_DAYS = 200
NOT_PREREGISTERED = ("THYAO",)  # its calendar results were seen before the protocol


def _round(value: float | None) -> float | None:
    return None if value is None or pd.isna(value) else round(float(value), 2)


def _episodes(positions: Sequence[int]) -> int:
    count, previous = 0, None
    for position in positions:
        if previous is None or position - previous - 1 >= EPISODE_GAP_DAYS:
            count += 1
        previous = position
    return count


def laggard_study(
    closes: Mapping[str, pd.Series],
    peer_closes: Mapping[str, Mapping[str, pd.Series]],
    lags: Mapping[str, pd.DataFrame],
    *,
    start: str,
    end: str,
) -> dict:
    """Scenario 1: laggard days in a strong sector and the next 10 days' catch-up."""
    outcomes: dict[str, list[float]] = {"primary": [], "secondary": []}
    days = {"primary": 0, "secondary": 0}
    episodes = {"primary": 0, "secondary": 0}
    per_stock = []
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    for ticker, close in closes.items():
        if ticker not in lags:
            continue
        close = close[close.index <= last]
        forward = close.shift(-OUTCOME_DAYS) / close - 1
        peers = pd.DataFrame(
            {
                m: (s := series[series.index <= last].reindex(close.index, method="ffill")).shift(
                    -OUTCOME_DAYS
                )
                / s
                - 1
                for m, series in peer_closes.get(ticker, {}).items()
            },
            index=close.index,
        )
        outcome = (forward - peers.median(axis=1)) * 100
        lag = lags[ticker].reindex(close.index)
        inside = (close.index >= first) & outcome.notna().to_numpy()
        strong = lag["sector_strong"].fillna(False).astype(bool).to_numpy()
        score = lag["lag_score"].to_numpy(dtype=float)
        row = {"ticker": ticker}
        for name, condition in (
            ("primary", score <= LAG_PRIMARY),
            ("secondary", score < 0),
        ):
            chosen = inside & strong & np.nan_to_num(condition, nan=False).astype(bool)
            positions = np.flatnonzero(chosen)
            days[name] += len(positions)
            episodes[name] += _episodes(positions)
            outcomes[name].extend(outcome.to_numpy()[positions].tolist())
            row[f"{name}_days"] = int(len(positions))
        per_stock.append(row)

    def summary(name: str) -> dict:
        values = np.asarray(outcomes[name], dtype=float)
        return {
            "laggard_days": int(days[name]),
            "episodes": int(episodes[name]),
            "hit_rate_pct": _round((values > 0).mean() * 100) if len(values) else None,
            "median_catch_up_pct": _round(np.median(values)) if len(values) else None,
            "false_positive_rate_pct": _round((values <= 0).mean() * 100) if len(values) else None,
            "sample_warning": sample_warning(int(episodes[name])),
        }

    return {
        "primary": summary("primary"),
        "secondary": summary("secondary"),
        "per_stock": per_stock,
        "definition": {
            "laggard_primary": "sector_strong and 20-day lag score <= -5 percentage points",
            "laggard_secondary": "sector_strong and 20-day lag score < 0",
            "outcome_days": OUTCOME_DAYS,
            "outcome": "stock return minus the median return of its peers (stock excluded), "
            "from the close of day t, window ending inside the period",
            "episode_gap_days": EPISODE_GAP_DAYS,
        },
    }


def pattern_supported(discovery: Mapping, test: Mapping) -> bool:
    """Significant after the correction in discovery and the same sign in the test period."""
    p_value = discovery.get("p_value_bonferroni")
    before, after = discovery.get("edge_pct"), test.get("edge_pct")
    if p_value is None or p_value >= ALPHA or before is None or after is None:
        return False
    return (before > 0) == (after > 0) and before != 0 and after != 0


def pattern_counts(rows: Sequence[Mapping], *, stocks: int) -> dict:
    """Per pattern: stocks passing at 5% before and after the correction, and chance."""
    out: dict[str, dict] = {}
    for row in rows:
        entry = out.setdefault(
            row["pattern"],
            {
                "significant_before_correction": 0,
                "significant_after_correction": 0,
                "expected_by_chance_before": round(ALPHA * stocks, 2),
                "expected_by_chance_after": round(ALPHA / len(PATTERNS) * stocks, 2),
            },
        )
        found = row["discovery"]
        if found.get("p_value") is not None and found["p_value"] < ALPHA:
            entry["significant_before_correction"] += 1
        if found.get("p_value_bonferroni") is not None and found["p_value_bonferroni"] < ALPHA:
            entry["significant_after_correction"] += 1
    return out


def _weekday_edge(result: Mapping, weekday: str | None = None) -> tuple[float | None, str | None]:
    rows = [r for r in result.get("weekdays", []) if r.get("average_return_pct") is not None]
    observations = sum(r["observations"] for r in rows)
    if not rows or not observations:
        return None, weekday
    overall = sum(r["average_return_pct"] * r["observations"] for r in rows) / observations
    if weekday is None:
        weekday = max(rows, key=lambda r: r["average_return_pct"])["weekday"]
    chosen = [r for r in rows if r["weekday"] == weekday]
    if not chosen:
        return None, weekday
    return _round(chosen[0]["average_return_pct"] - overall), weekday


def _pattern_numbers(result: Mapping, pattern: str, weekday: str | None = None) -> dict:
    if pattern == "WEEKDAY_MEANS":
        edge, weekday = _weekday_edge(result, weekday)
    else:
        edge = _edge(result, pattern == "END_OF_WEEK_CONTINUATION")
    return {
        "occurrences": result.get("occurrences"),
        "p_value": result.get("p_value"),
        "p_value_bonferroni": result.get("p_value_bonferroni"),
        "edge_pct": _round(edge),
        "best_weekday": weekday if pattern == "WEEKDAY_MEANS" else None,
    }


def calendar_study(
    histories: Mapping[str, pd.DataFrame],
    *,
    discovery: tuple[str, str],
    test: tuple[str, str] | None = None,
) -> dict:
    """Scenario 2: every pattern for every stock; the test half only when ``test`` is given."""
    rows = []
    for ticker, history in histories.items():
        for pattern in PATTERNS:
            found = evaluate_pattern(
                history[history.index <= pd.Timestamp(discovery[1])], pattern, since=discovery[0]
            )
            row = {
                "ticker": ticker,
                "pattern": pattern,
                "preregistered": ticker not in NOT_PREREGISTERED,
                "discovery": _pattern_numbers(found, pattern),
            }
            if test is not None:
                later = evaluate_pattern(
                    history[history.index <= pd.Timestamp(test[1])], pattern, since=test[0]
                )
                row["test"] = _pattern_numbers(later, pattern, row["discovery"]["best_weekday"])
                row["supported"] = pattern_supported(row["discovery"], row["test"])
            rows.append(row)
    out = {"rows": rows, "counts": pattern_counts(rows, stocks=len(histories))}
    if test is not None:
        out["supported"] = [
            {"ticker": r["ticker"], "pattern": r["pattern"], "preregistered": r["preregistered"]}
            for r in rows
            if r["supported"]
        ]
    return out


def summarize_family(records: pd.DataFrame, *, regime: Mapping[str, bool]) -> dict:
    """Scenario 3 numbers of one event family and direction across stocks."""
    bullish = (records["direction"] == "BULLISH").to_numpy()

    def block(frame: pd.DataFrame, is_bullish: np.ndarray) -> dict:
        five = frame["forward_5d_return_pct"].to_numpy(dtype=float)
        done = ~np.isnan(five)
        success = np.where(is_bullish, five > 0, five < 0) & done
        rate = success.sum() / done.sum() * 100 if done.sum() else None
        return {
            "events": int(len(frame)),
            "evaluated_5d": int(done.sum()),
            "bounce_rate_5d_pct": _round(rate),
        }

    out = block(records, bullish)
    for horizon in HORIZONS:
        values = records[f"forward_{horizon}d_return_pct"].dropna()
        out[f"mean_{horizon}d_return_pct"] = _round(values.mean()) if len(values) else None
        out[f"median_{horizon}d_return_pct"] = _round(values.median()) if len(values) else None
    out["mean_reversal_strength_pct"] = _round(records["reversal_strength_pct"].mean())
    out["sample_warning"] = sample_warning(int(len(records)))
    above = records["date"].map(lambda d: bool(regime.get(d, False))).to_numpy()
    out["by_regime"] = {
        "XU100_ABOVE_200D": block(records[above], bullish[above]),
        "XU100_BELOW_200D": block(records[~above], bullish[~above]),
    }
    return out


def event_study(
    histories: Mapping[str, pd.DataFrame], benchmark: pd.Series, *, start: str, end: str
) -> dict:
    """Scenario 3: every event family and direction across the universe, one period."""
    last = pd.Timestamp(end)
    index = benchmark[benchmark.index <= last]
    regime = {
        str(day.date()): bool(above)
        for day, above in (index > index.rolling(REGIME_DAYS).mean()).items()
    }
    frames = {t: add_all_indicators(h[h.index <= last]) for t, h in histories.items()}
    out: dict[str, dict] = {}
    for event_type in EVENT_TYPES:
        for direction in DIRECTIONS:
            actual = effective_direction(event_type, direction)
            key = f"{event_type}:{actual}"
            if key in out:
                continue
            parts = [
                event_records(
                    frame,
                    counted_mask(frame, event_type, actual),
                    ticker=ticker,
                    event_type=event_type,
                    direction=actual,
                    horizons=HORIZONS,
                    since=start,
                )
                for ticker, frame in frames.items()
            ]
            records = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
            out[key] = summarize_family(records, regime=regime) if len(records) else {"events": 0}
    return out
