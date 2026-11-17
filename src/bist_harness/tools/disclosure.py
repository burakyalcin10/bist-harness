"""Price reaction after a financial-report disclosure (project brief, section 14).

The event day is the first trading day whose close follows the publication (the
``known_from`` day of ``data/fundamentals.py``). The reaction runs from the close
**before** the event day to the close 1, 5 and 20 trading days after it, so it contains
the event day itself whether the report came before, during or after the session.

Abnormal return is the stock's return minus the return, over the same two dates, of
XU100 and of the equal-weight average of its sector peers.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from bist_harness.tools.events import sample_warning

HORIZONS = (1, 5, 20)


def _between(series: pd.Series, first: pd.Timestamp, last: pd.Timestamp) -> float:
    """Return between the last closes on or before two dates (NaN when one is missing)."""
    start, end = series.loc[:first], series.loc[:last]
    if start.empty or end.empty:
        return float("nan")
    return float(end.iloc[-1] / start.iloc[-1] - 1)


def post_disclosure_returns(
    close: pd.Series,
    event_days: Sequence[pd.Timestamp],
    *,
    benchmark: pd.Series | None,
    peers: dict[str, pd.Series],
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    """One row per event: raw and abnormal returns in percent for each horizon.

    An event on a day without a bar moves to the stock's next bar. An event with no bar
    before it or none at or after it is left out. A horizon that reaches beyond the data
    is NaN.
    """
    close = close.dropna()
    days = close.index
    rows = []
    for day in event_days:
        position = int(days.searchsorted(pd.Timestamp(day)))
        if position == 0 or position >= len(days):
            continue
        base_day = days[position - 1]
        row: dict = {
            "event_day": str(days[position].date()),
            "base_day": str(base_day.date()),
            "peers_used": 0,
        }
        for horizon in horizons:
            end = position + horizon
            own = index_return = peer_return = float("nan")
            if end < len(days):
                end_day = days[end]
                own = float(close.iloc[end] / close.iloc[position - 1] - 1)
                if benchmark is not None:
                    index_return = _between(benchmark, base_day, end_day)
                peer_returns = [_between(series, base_day, end_day) for series in peers.values()]
                peer_returns = [value for value in peer_returns if not np.isnan(value)]
                row["peers_used"] = max(row["peers_used"], len(peer_returns))
                if peer_returns:
                    peer_return = float(np.mean(peer_returns))
            row[f"return_{horizon}d_pct"] = round(own * 100, 2)
            row[f"abnormal_vs_index_{horizon}d_pct"] = round((own - index_return) * 100, 2)
            row[f"abnormal_vs_peers_{horizon}d_pct"] = round((own - peer_return) * 100, 2)
        rows.append(row)
    columns = ["event_day", "base_day", "peers_used"]
    for horizon in horizons:
        columns += [
            f"return_{horizon}d_pct",
            f"abnormal_vs_index_{horizon}d_pct",
            f"abnormal_vs_peers_{horizon}d_pct",
        ]
    return pd.DataFrame(rows, columns=columns)


def _mean(values: pd.Series) -> float | None:
    values = values.dropna()
    return round(float(values.mean()), 2) if len(values) else None


def _median(values: pd.Series) -> float | None:
    values = values.dropna()
    return round(float(values.median()), 2) if len(values) else None


def _horizons_of(reactions: pd.DataFrame) -> list[int]:
    return [int(c[len("return_") : -len("d_pct")]) for c in reactions if c.startswith("return_")]


def summarize_reactions(reactions: pd.DataFrame, groups: pd.Series | None = None) -> dict:
    """Average reaction per horizon, optionally broken down by a label per event.

    ``groups`` is aligned with the rows of ``reactions`` (for example the fundamental
    trend of the quarter). A horizon counts only the events that have completed it.
    """
    horizons = _horizons_of(reactions)
    output: dict = {"events": int(len(reactions)), "horizons": {}}
    for horizon in horizons:
        raw = reactions[f"return_{horizon}d_pct"]
        output["horizons"][f"{horizon}d"] = {
            "events": int(raw.notna().sum()),
            "mean_return_pct": _mean(raw),
            "median_return_pct": _median(raw),
            "positive_rate_pct": _mean((raw.dropna() > 0) * 100.0),
            "mean_abnormal_vs_index_pct": _mean(reactions[f"abnormal_vs_index_{horizon}d_pct"]),
            "mean_abnormal_vs_peers_pct": _mean(reactions[f"abnormal_vs_peers_{horizon}d_pct"]),
        }
    if groups is not None:
        output["by_group"] = {}
        for name in sorted(set(groups.dropna())):
            part = reactions[(groups == name).to_numpy()]
            entry: dict = {"events": int(len(part))}
            for horizon in horizons:
                entry[f"mean_return_{horizon}d_pct"] = _mean(part[f"return_{horizon}d_pct"])
                entry[f"mean_abnormal_vs_index_{horizon}d_pct"] = _mean(
                    part[f"abnormal_vs_index_{horizon}d_pct"]
                )
                entry[f"mean_abnormal_vs_peers_{horizon}d_pct"] = _mean(
                    part[f"abnormal_vs_peers_{horizon}d_pct"]
                )
            output["by_group"][str(name)] = entry
    output["sample_warning"] = sample_warning(len(reactions))
    return output
