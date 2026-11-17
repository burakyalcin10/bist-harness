"""Macro context for a period (project brief, section 15).

Every value is what was public on the date it is reported for: a policy decision counts
from its date, a CPI figure from its release day. Nothing dated or released after the
period's end is used.
"""

from __future__ import annotations

import pandas as pd


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _in_effect(table: pd.DataFrame, day: pd.Timestamp) -> pd.Series | None:
    """Last row with an effective date on or before ``day``."""
    rows = table[table["effective_date"] <= day]
    return rows.iloc[-1] if len(rows) else None


def _number(row: pd.Series | None, column: str) -> float | None:
    return None if row is None else round(float(row[column]), 2)


def macro_context(series: dict[str, pd.DataFrame], *, start: str, end: str) -> dict:
    """Summarise FX, policy rate, Fed target and CPI between ``start`` and ``end``.

    ``series`` may lack any of ``fx``, ``policy_rate``, ``fed_target``, ``cpi``; a missing
    one gives ``None`` values and a warning.
    """
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    warnings: list[str] = []
    output: dict = {"start": start, "end": end}

    fx = series.get("fx")
    window = fx.loc[first:last] if fx is not None else _empty(["USDTRY", "EURTRY"])
    if window.empty:
        warnings.append("NO_FX_DATA: no exchange-rate data for the period.")
    for name in ("USDTRY", "EURTRY"):
        key = name.lower()
        values = window[name].dropna() if name in window else pd.Series(dtype=float)
        if values.empty:
            output.update({f"{key}_start": None, f"{key}_end": None, f"{key}_change_pct": None})
            continue
        begin, finish = float(values.iloc[0]), float(values.iloc[-1])
        output[f"{key}_start"] = round(begin, 4)
        output[f"{key}_end"] = round(finish, 4)
        output[f"{key}_change_pct"] = round((finish / begin - 1) * 100, 2)

    policy = series.get("policy_rate")
    if policy is None:
        policy = _empty(["effective_date", "rate"])
    at_start, at_end = _in_effect(policy, first), _in_effect(policy, last)
    if at_end is None:
        warnings.append(f"NO_POLICY_RATE_DATA: no TCMB policy decision known by {end}.")
    inside = policy[(policy["effective_date"] > first) & (policy["effective_date"] <= last)]
    output["policy_rate_start"] = _number(at_start, "rate")
    output["policy_rate_end"] = _number(at_end, "rate")
    output["policy_rate_change_pp"] = (
        None
        if at_start is None or at_end is None
        else round(float(at_end["rate"] - at_start["rate"]), 2)
    )
    output["policy_rate_changes"] = int(len(inside))
    output["last_policy_decision_date"] = (
        None if at_end is None else str(pd.Timestamp(at_end["effective_date"]).date())
    )

    fed = series.get("fed_target")
    if fed is None:
        fed = _empty(["effective_date", "lower", "upper"])
    fed_start, fed_end = _in_effect(fed, first), _in_effect(fed, last)
    if fed_end is None:
        warnings.append(f"NO_FED_TARGET_DATA: no Federal Reserve target known by {end}.")
    output["fed_target_lower_start"] = _number(fed_start, "lower")
    output["fed_target_upper_start"] = _number(fed_start, "upper")
    output["fed_target_lower_end"] = _number(fed_end, "lower")
    output["fed_target_upper_end"] = _number(fed_end, "upper")
    output["fed_changes"] = int(
        ((fed["effective_date"] > first) & (fed["effective_date"] <= last)).sum()
    )

    cpi = series.get("cpi")
    if cpi is None:
        cpi = _empty(["period", "annual_pct", "monthly_pct", "published"])
    public = cpi[cpi["published"] <= last]
    latest = public.sort_values("period").iloc[-1] if len(public) else None
    if latest is None:
        warnings.append(f"NO_CPI_DATA: no consumer-price figure published by {end}.")
    output["cpi_period"] = (
        None if latest is None else pd.Timestamp(latest["period"]).strftime("%Y-%m")
    )
    output["cpi_annual_pct"] = _number(latest, "annual_pct")
    output["cpi_monthly_pct"] = _number(latest, "monthly_pct")
    output["cpi_published"] = (
        None if latest is None else str(pd.Timestamp(latest["published"]).date())
    )
    output["warnings"] = warnings
    return output
