"""Data-quality checks for one daily price series (project brief, sections 26 and 27).

A *hard* finding means the series cannot be trusted and an analysis on it is unsafe.
A *soft* finding is reported with the result but does not block it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

PRICE_COLUMNS = ["Open", "High", "Low", "Close"]
JUMP_LIMIT = 0.40
RELATIVE_TOLERANCE = 1e-6  # adjusted prices carry float noise


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Literal["hard", "soft"]
    message: str
    count: int = 1


def check_price_series(
    df: pd.DataFrame,
    *,
    as_of: str,
    expected_days: pd.DatetimeIndex | None = None,
    min_rows: int = 60,
    stale_after_days: int = 5,
) -> list[Finding]:
    """Return every data-quality finding for ``df`` as seen on ``as_of``.

    ``expected_days`` is the trading calendar (the benchmark index's dates); without it
    missing days are not checked and staleness is counted in weekdays.
    """
    if df.empty:
        return [Finding("EMPTY_SERIES", "hard", "The series has no rows.")]

    findings: list[Finding] = []
    as_of_day = pd.Timestamp(as_of)
    index = pd.DatetimeIndex(df.index)

    if len(df) < min_rows:
        findings.append(
            Finding("SHORT_HISTORY", "soft", f"Only {len(df)} rows; at least {min_rows} expected.")
        )

    duplicates = int(index.duplicated().sum())
    if duplicates:
        findings.append(
            Finding("DUPLICATE_DATES", "hard", f"{duplicates} repeated date(s).", duplicates)
        )
    if not index.is_monotonic_increasing:
        findings.append(Finding("NON_MONOTONIC_INDEX", "hard", "Dates are not in order."))

    non_positive = int((df[PRICE_COLUMNS] <= 0).any(axis=1).sum())
    if non_positive:
        findings.append(
            Finding(
                "NON_POSITIVE_PRICE",
                "hard",
                f"{non_positive} row(s) with a zero or negative price.",
                non_positive,
            )
        )

    body_top = df[["Open", "Close"]].max(axis=1)
    body_bottom = df[["Open", "Close"]].min(axis=1)
    inconsistent = int(
        (
            (df["High"] < body_top * (1 - RELATIVE_TOLERANCE))
            | (df["Low"] > body_bottom * (1 + RELATIVE_TOLERANCE))
        ).sum()
    )
    if inconsistent:
        findings.append(
            Finding(
                "OHLC_INCONSISTENT",
                "hard",
                f"{inconsistent} row(s) where High or Low contradicts Open and Close.",
                inconsistent,
            )
        )

    change = df["Close"].pct_change().replace([np.inf, -np.inf], np.nan)
    jumps = int((change.abs() > JUMP_LIMIT).sum())
    if jumps:
        findings.append(
            Finding(
                "PRICE_JUMP",
                "soft",
                f"{jumps} daily close change(s) above {JUMP_LIMIT:.0%}; "
                "possibly an unadjusted split or rights issue.",
                jumps,
            )
        )

    zero_volume = int((df["Volume"] == 0).sum())
    if zero_volume:
        findings.append(
            Finding("ZERO_VOLUME", "soft", f"{zero_volume} day(s) with zero volume.", zero_volume)
        )

    first, last = index.min(), index.max()
    if expected_days is not None:
        calendar = pd.DatetimeIndex(expected_days)
        window = calendar[(calendar >= first) & (calendar <= min(last, as_of_day))]
        missing = int(len(window.difference(index)))
        if missing:
            findings.append(
                Finding(
                    "MISSING_DAYS",
                    "soft",
                    f"{missing} trading day(s) of the benchmark calendar are absent.",
                    missing,
                )
            )
        days_behind = int(((calendar > last) & (calendar <= as_of_day)).sum())
    else:
        days_behind = int(np.busday_count(last.date(), as_of_day.date()))
    if days_behind > stale_after_days:
        findings.append(
            Finding(
                "STALE_DATA",
                "soft",
                f"Last bar {last.date()} is {days_behind} trading days before {as_of}.",
                days_behind,
            )
        )

    future = int((index > as_of_day).sum())
    if future:
        findings.append(
            Finding("FUTURE_ROWS", "hard", f"{future} row(s) dated after {as_of}.", future)
        )
    return findings
