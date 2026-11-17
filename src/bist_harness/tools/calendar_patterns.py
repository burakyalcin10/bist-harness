"""Weekday and multi-day return patterns (project brief, section 7; Scenario 2).

Data preparation, weekday statistics, complete-week rule, transaction cost (0.001) and
the 70/30 time split follow the instructor's Scenario 2 script.

One deliberate difference. The script defines its pattern as Mon, Tue, Wed < 0 *and*
Thu, Fri > 0, and then reports the Thu-Fri return of those weeks as the "return after
the pattern". That return is positive by construction. Here a condition only reads days
that come *before* the measured outcome; the script's full-pattern count is still
reported (``instructor_full_pattern_count``) so the two can be compared.

Every conditional pattern is a set of units (weeks or days) with a condition known
before the outcome. Reported: how often the condition occurred, the outcome when it
did, the outcome in general, the result after cost, a train/test comparison and a
permutation p-value with a Bonferroni correction for the five patterns of the family.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bist_harness.tools.events import sample_warning
from bist_harness.tools.schemas import WEEKDAY_PATTERNS

PATTERNS: tuple[str, ...] = tuple(WEEKDAY_PATTERNS)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
TRANSACTION_COST = 0.001
TRAIN_RATIO = 0.70
PERMUTATIONS = 2000
SEED = 42
ALPHA = 0.05
VOLATILITY_WINDOW = 60
LARGE_DROP_SIGMAS = 2.0
MIN_GROUP = 3  # observations needed on each side for a studentized test

DEFINITIONS = {
    "WEEKDAY_MEANS": (
        "Average, median and share of positive daily returns for each weekday. The p-value "
        "tests whether the gap between the best and the worst weekday could be chance."
    ),
    "MON_WEAK_FRI_STRONG": (
        "Weeks with all five trading days. Condition: Monday's return is negative. "
        "Outcome: Friday's return of the same week."
    ),
    "THREE_DOWN_TWO_UP": (
        "Weeks with all five trading days. Condition: Monday, Tuesday and Wednesday all "
        "negative. Outcome: the compound Thursday-Friday return of the same week."
    ),
    "POST_LARGE_DOWN_REVERSION": (
        "Condition: a daily return below minus 2 standard deviations of the previous 60 "
        "daily returns. Outcome: the next day's return."
    ),
    "END_OF_WEEK_CONTINUATION": (
        "Weeks with all five trading days. Outcome: Friday's return counted in the direction "
        "of the compound Monday-Thursday return, so a positive value means Friday continued "
        "the week's direction."
    ),
}


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Daily returns with weekday and ISO week columns (the script's loader)."""
    out = pd.DataFrame({"Close": df["Close"]})
    out["Return"] = out["Close"].pct_change()
    out["Weekday"] = pd.Series(out.index.day_of_week, index=out.index).map(
        dict(enumerate(WEEKDAYS))
    )
    iso = out.index.isocalendar()
    out["ISO_Year"] = iso.year.astype(int)
    out["ISO_Week"] = iso.week.astype(int)
    return out.dropna(subset=["Return"])


def split_by_time(prepared: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """First 70% of the rows for training, the rest for testing (the script's split)."""
    cut = int(len(prepared) * TRAIN_RATIO)
    return prepared.iloc[:cut], prepared.iloc[cut:]


def weekly_table(prepared: pd.DataFrame) -> pd.DataFrame:
    """One row per ISO week: the five daily returns, the week's last date, completeness."""
    if prepared.empty:
        empty = pd.DataFrame(columns=[*WEEKDAYS, "date"], dtype=float)
        return empty.assign(complete=pd.Series(dtype=bool))
    keys = ["ISO_Year", "ISO_Week"]
    weekly = prepared.pivot_table(index=keys, columns="Weekday", values="Return", aggfunc="first")
    weekly = weekly.reindex(columns=WEEKDAYS)
    dates = prepared.reset_index(names="date").groupby(keys)["date"].max()
    weekly["date"] = dates
    weekly["complete"] = weekly[WEEKDAYS].notna().all(axis=1)
    return weekly


def _week_units(weekly: pd.DataFrame, pattern: str) -> pd.DataFrame:
    """Units of a weekly pattern: weight (condition or direction), outcome and date."""
    complete = weekly[weekly["complete"].astype(bool)]
    mon, tue, wed, thu, fri = (complete[d].astype(float) for d in WEEKDAYS)
    if pattern == "MON_WEAK_FRI_STRONG":
        weight, outcome = (mon < 0).astype(float), fri
    elif pattern == "THREE_DOWN_TWO_UP":
        weight = ((mon < 0) & (tue < 0) & (wed < 0)).astype(float)
        outcome = (1 + thu) * (1 + fri) - 1
    else:  # END_OF_WEEK_CONTINUATION
        weight = np.sign((1 + mon) * (1 + tue) * (1 + wed) * (1 + thu) - 1)
        outcome = fri
    units = pd.DataFrame(
        {"weight": weight.to_numpy(), "outcome": outcome.to_numpy(), "date": complete["date"]}
    )
    return units[units["weight"] != 0] if pattern == "END_OF_WEEK_CONTINUATION" else units


def _day_units(prepared: pd.DataFrame) -> pd.DataFrame:
    """Units of the large-drop pattern: one per day with a known volatility and a next day."""
    returns = prepared["Return"]
    volatility = returns.rolling(VOLATILITY_WINDOW).std().shift(1)
    units = pd.DataFrame(
        {
            "weight": (returns < -LARGE_DROP_SIGMAS * volatility).astype(float),
            "outcome": returns.shift(-1),
            "date": pd.Series(prepared.index, index=prepared.index).shift(-1),
            "known": volatility.notna(),
        }
    )
    return units[units["known"] & units["outcome"].notna()].drop(columns="known")


def _pct(value: float | None) -> float | None:
    return None if value is None or np.isnan(value) else round(float(value) * 100, 2)


def _selected(units: pd.DataFrame, signed: bool) -> pd.Series:
    """Outcomes that count: all units in direction terms, or the units meeting the condition."""
    if signed:
        return units["weight"] * units["outcome"]
    return units.loc[units["weight"] == 1, "outcome"]


def _summary(units: pd.DataFrame, signed: bool) -> dict:
    chosen = _selected(units, signed)
    if chosen.empty:
        return {
            "occurrences": 0,
            "conditional_mean_return_pct": None,
            "unconditional_mean_return_pct": _pct(units["outcome"].mean()) if len(units) else None,
        }
    return {
        "occurrences": int(len(chosen)),
        "conditional_mean_return_pct": _pct(chosen.mean()),
        "unconditional_mean_return_pct": _pct(units["outcome"].mean()),
    }


def two_sided_p_value(observed: float, simulated: np.ndarray) -> float:
    """Share of shuffles at least as far from the shuffles' own mean as the observed value.

    Centring on the permutation mean matters when that mean is not zero, as for a
    direction pattern in a market that mostly rises.
    """
    centre = float(simulated.mean())
    extreme = int((np.abs(simulated - centre) >= abs(observed - centre) - 1e-15).sum())
    return round((1 + extreme) / (len(simulated) + 1), 4)


def _permutation_p_value(units: pd.DataFrame, signed: bool) -> float | None:
    """Two-sided permutation test: outcomes are shuffled against the conditions.

    Direction pattern: the statistic is the mean outcome in the direction of the week.

    Condition pattern: the statistic is the Welch t-statistic between the outcomes under
    the condition and the others (difference of means over its own standard error).
    Studentizing matters because the condition often selects volatile days: after a
    large drop the next day's return varies more, and a plain difference of means would
    then look significant far too often. It needs at least three observations on each
    side; with fewer there is no p-value.
    """
    weight = units["weight"].to_numpy(dtype=float)
    outcome = units["outcome"].to_numpy(dtype=float)
    if not signed:
        return _studentized_p_value(weight, outcome)
    used = len(outcome) if signed else int(weight.sum())
    if used == 0 or len(outcome) < 2 or (not signed and used == len(outcome)):
        return None
    baseline = 0.0 if signed else float(outcome.mean())
    observed = float(weight @ outcome) / used - baseline
    rng = np.random.default_rng(SEED)
    shuffled = rng.permuted(np.tile(outcome, (PERMUTATIONS, 1)), axis=1)
    simulated = shuffled @ weight / used - baseline
    return two_sided_p_value(observed, simulated)


def _studentized_p_value(weight: np.ndarray, outcome: np.ndarray) -> float | None:
    inside, outside = int(weight.sum()), int(len(weight) - weight.sum())
    if inside < MIN_GROUP or outside < MIN_GROUP:
        return None
    total, total_squares = float(outcome.sum()), float((outcome**2).sum())

    def welch(sums, squares):
        mean_in, mean_out = sums / inside, (total - sums) / outside
        var_in = (squares - inside * mean_in**2) / (inside - 1)
        var_out = (total_squares - squares - outside * mean_out**2) / (outside - 1)
        spread = np.sqrt(np.clip(var_in, 0, None) / inside + np.clip(var_out, 0, None) / outside)
        with np.errstate(divide="ignore", invalid="ignore"):
            return (mean_in - mean_out) / spread

    observed = float(welch(weight @ outcome, weight @ outcome**2))
    if not np.isfinite(observed):
        return None
    rng = np.random.default_rng(SEED)
    shuffled = rng.permuted(np.tile(outcome, (PERMUTATIONS, 1)), axis=1)
    simulated = welch(shuffled @ weight, shuffled**2 @ weight)
    simulated = simulated[np.isfinite(simulated)]
    return two_sided_p_value(observed, simulated) if len(simulated) else None


def _bonferroni(p_value: float | None) -> float | None:
    return None if p_value is None else min(1.0, round(p_value * len(PATTERNS), 4))


def _edge(summary: dict, signed: bool) -> float | None:
    """What the pattern claims: the signed mean for a direction pattern, otherwise the
    conditional mean in excess of the unconditional one."""
    if summary["conditional_mean_return_pct"] is None:
        return None
    if signed:
        return summary["conditional_mean_return_pct"]
    return summary["conditional_mean_return_pct"] - summary["unconditional_mean_return_pct"]


def is_unstable(train: dict, test: dict, *, signed: bool) -> bool:
    """True when the edge changes sign between train and test, or one part has none."""
    train_edge, test_edge = _edge(train, signed), _edge(test, signed)
    if train_edge is None or test_edge is None:
        return True
    return (train_edge > 0) != (test_edge > 0)


def _conditional_pattern(prepared: pd.DataFrame, pattern: str, full: pd.DataFrame) -> dict:
    """``prepared`` is the requested period; ``full`` also holds the rows before it, so
    the volatility of the large-drop pattern is warmed up when the period starts."""
    signed = pattern == "END_OF_WEEK_CONTINUATION"
    weekly = weekly_table(prepared)
    if pattern == "POST_LARGE_DOWN_REVERSION":
        units = _day_units(full)
        units = units[units.index >= prepared.index[0]] if len(prepared) else units.iloc[:0]
    else:
        units = _week_units(weekly, pattern)
    train_rows, _ = split_by_time(prepared)
    last_train_day = train_rows.index[-1] if len(train_rows) else pd.Timestamp.min
    in_train = pd.to_datetime(units["date"]) <= last_train_day
    train, test = _summary(units[in_train], signed), _summary(units[~in_train], signed)

    chosen = _selected(units, signed)
    summary = _summary(units, signed)
    mean_after_cost = None
    if len(chosen):
        mean_after_cost = round(float(chosen.mean() - TRANSACTION_COST) * 100, 2)
    p_value = _permutation_p_value(units, signed)
    p_adjusted = _bonferroni(p_value)

    flags = []
    if p_adjusted is None or p_adjusted >= ALPHA:
        flags.append("NOT_SIGNIFICANT")
    if summary["occurrences"] and is_unstable(train, test, signed=signed):
        flags.append("UNSTABLE_OUT_OF_SAMPLE")
    if mean_after_cost is not None and mean_after_cost <= 0:
        flags.append("NEGATIVE_AFTER_COST")

    output = {
        **summary,
        "conditional_median_return_pct": _pct(chosen.median()) if len(chosen) else None,
        "positive_rate_pct": _pct((chosen > 0).mean()) if len(chosen) else None,
        "mean_after_cost_pct": mean_after_cost,
        "transaction_cost_pct": round(TRANSACTION_COST * 100, 2),
        "train": train,
        "test": test,
        "p_value": p_value,
        "patterns_in_family": len(PATTERNS),
        "p_value_bonferroni": p_adjusted,
        "sample_warning": sample_warning(summary["occurrences"]),
        "interpretation_flags": flags,
    }
    if pattern != "POST_LARGE_DOWN_REVERSION":
        output["complete_weeks"] = int(weekly["complete"].sum())
        output["incomplete_weeks_skipped"] = int((~weekly["complete"]).sum())
    if pattern == "THREE_DOWN_TWO_UP":
        complete = weekly[weekly["complete"]]
        full = (complete[["Mon", "Tue", "Wed"]] < 0).all(axis=1) & (
            complete[["Thu", "Fri"]] > 0
        ).all(axis=1)
        output["instructor_full_pattern_count"] = int(full.sum())
    return output


def _weekday_table(prepared: pd.DataFrame) -> pd.DataFrame:
    stats = prepared.groupby("Weekday")["Return"].agg(
        observations="count",
        average="mean",
        median="median",
        positive=lambda x: (x > 0).mean(),
    )
    return stats.reindex(WEEKDAYS)


def _best_worst(prepared: pd.DataFrame) -> dict:
    stats = _weekday_table(prepared)["average"].dropna()
    if stats.empty:
        return {"best_day": None, "worst_day": None, "spread_pct": None}
    return {
        "best_day": str(stats.idxmax()),
        "worst_day": str(stats.idxmin()),
        "spread_pct": _pct(stats.max() - stats.min()),
    }


def _weekday_spread_p_value(prepared: pd.DataFrame) -> float | None:
    """Permutation test of the best-minus-worst weekday gap: returns shuffled across days."""
    returns = prepared["Return"].to_numpy(dtype=float)
    one_hot = np.stack([(prepared["Weekday"] == d).to_numpy(dtype=float) for d in WEEKDAYS], axis=1)
    counts = one_hot.sum(axis=0)
    if len(returns) < 2 or (counts == 0).any():
        return None
    means = returns @ one_hot / counts
    observed = float(means.max() - means.min())
    rng = np.random.default_rng(SEED)
    shuffled = rng.permuted(np.tile(returns, (PERMUTATIONS, 1)), axis=1) @ one_hot / counts
    simulated = shuffled.max(axis=1) - shuffled.min(axis=1)
    extreme = int((simulated >= observed - 1e-15).sum())
    return round((1 + extreme) / (PERMUTATIONS + 1), 4)


def _weekday_means(prepared: pd.DataFrame) -> dict:
    stats = _weekday_table(prepared)
    rows = [
        {
            "weekday": day,
            "observations": int(
                0 if pd.isna(stats.at[day, "observations"]) else stats.at[day, "observations"]
            ),
            "average_return_pct": _pct(stats.at[day, "average"]),
            "median_return_pct": _pct(stats.at[day, "median"]),
            "positive_rate_pct": _pct(stats.at[day, "positive"]),
        }
        for day in WEEKDAYS
    ]
    overall = _best_worst(prepared)
    train_rows, test_rows = split_by_time(prepared)
    train, test = _best_worst(train_rows), _best_worst(test_rows)
    p_value = _weekday_spread_p_value(prepared)
    p_adjusted = _bonferroni(p_value)
    best_average = stats["average"].max()
    mean_after_cost = (
        None if pd.isna(best_average) else round(float(best_average - TRANSACTION_COST) * 100, 2)
    )

    flags = []
    if p_adjusted is None or p_adjusted >= ALPHA:
        flags.append("NOT_SIGNIFICANT")
    if train["best_day"] != test["best_day"]:
        flags.append("UNSTABLE_OUT_OF_SAMPLE")
    if mean_after_cost is not None and mean_after_cost <= 0:
        flags.append("NEGATIVE_AFTER_COST")
    smallest = min((row["observations"] for row in rows), default=0)
    return {
        "occurrences": int(len(prepared)),
        "weekdays": rows,
        **overall,
        "mean_after_cost_pct": mean_after_cost,
        "transaction_cost_pct": round(TRANSACTION_COST * 100, 2),
        "train": train,
        "test": test,
        "p_value": p_value,
        "patterns_in_family": len(PATTERNS),
        "p_value_bonferroni": p_adjusted,
        "sample_warning": sample_warning(smallest),
        "interpretation_flags": flags,
    }


def evaluate_pattern(df: pd.DataFrame, pattern: str, *, since: str | None = None) -> dict:
    """Test one pattern on daily closes; ``since`` drops earlier returns."""
    if pattern not in PATTERNS:
        raise ValueError(f"unknown pattern: {pattern}")
    full = prepare(df)
    prepared = full if since is None else full.loc[pd.Timestamp(since) :]
    if pattern == "WEEKDAY_MEANS":
        result = _weekday_means(prepared)
    else:
        result = _conditional_pattern(prepared, pattern, full)
    return {"pattern": pattern, **result, "definition": DEFINITIONS[pattern]}
