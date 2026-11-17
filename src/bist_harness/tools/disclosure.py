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


def quarter_reactions(
    known: pd.DataFrame,
    close: pd.Series,
    *,
    benchmark: pd.Series | None,
    peers: dict[str, pd.Series],
    as_of: str,
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    """Reaction to each reporting period of ``known`` (rows with year, quarter, known_from).

    Prices are cut at ``as_of`` first, so a horizon that was not complete on that day is
    missing, and a period that was not usable yet has no row.
    """
    day = pd.Timestamp(as_of)
    usable = known[known["known_from"].notna() & (known["known_from"] <= day)]
    usable = usable.sort_values(["year", "quarter"])
    cut_peers = {name: series.loc[:day] for name, series in peers.items()}
    cut_benchmark = None if benchmark is None else benchmark.loc[:day]
    rows = []
    for _, row in usable.iterrows():
        reaction = post_disclosure_returns(
            close.loc[:day],
            [row["known_from"]],
            benchmark=cut_benchmark,
            peers=cut_peers,
            horizons=horizons,
        )
        if reaction.empty:
            continue
        entry = reaction.iloc[0].to_dict()
        entry["period"] = f"{int(row['year'])}Q{int(row['quarter'])}"
        rows.append(entry)
    table = pd.DataFrame(rows)
    if table.empty:
        table = post_disclosure_returns(close, [], benchmark=None, peers={}, horizons=horizons)
        table["period"] = pd.Series(dtype=object)
    return table


def reaction_study(
    statements: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    closes: dict[str, pd.Series],
    benchmark: pd.Series | None,
    peer_closes: dict[str, dict[str, pd.Series]],
    cpi: pd.Series | None,
    start: str,
    end: str,
    horizons: Sequence[int] = HORIZONS,
) -> dict:
    """Scenario 4: the reaction to every report that became usable between ``start`` and
    ``end``, labelled with the fundamental trend that was computable on that day.

    Returns ``{"events": DataFrame, "summary": dict}``; the summary is broken down by
    trend. Nothing after ``end`` is used.
    """
    from bist_harness.tools.fundamentals import fundamental_change

    first, last = pd.Timestamp(start), pd.Timestamp(end)
    parts = []
    for ticker, close in closes.items():
        known = calendar[
            (calendar["ticker"] == ticker)
            & calendar["known_from"].notna()
            & (calendar["known_from"] >= first)
            & (calendar["known_from"] <= last)
        ]
        if known.empty:
            continue
        table = quarter_reactions(
            known,
            close,
            benchmark=benchmark,
            peers=peer_closes.get(ticker, {}),
            as_of=end,
            horizons=horizons,
        )
        if table.empty:
            continue
        trends = []
        for event_day in table["event_day"]:
            change = fundamental_change(
                statements, calendar, ticker=ticker, as_of=event_day, cpi=cpi
            )
            trends.append(None if change is None else change["fundamental_trend"])
        table.insert(0, "ticker", ticker)
        table["fundamental_trend"] = trends
        parts.append(table)
    if not parts:
        events = quarter_reactions(
            calendar.iloc[:0], pd.Series(dtype=float), benchmark=None, peers={}, as_of=end
        )
        events.insert(0, "ticker", pd.Series(dtype=object))
        events["fundamental_trend"] = pd.Series(dtype=object)
    else:
        events = pd.concat(parts, ignore_index=True)
    groups = events["fundamental_trend"].fillna("No trend")
    return {"events": events, "summary": summarize_reactions(events, groups)}
