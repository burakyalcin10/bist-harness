"""Unified point-in-time feature table (project brief, section 10).

One row per stock and trading day, holding what was known at that day's close from every
layer: technical states, sector lag scores, event counts, the latest public quarter,
macro context and recent disclosures. Each layer is joined by the date its information
became public, never by the period it describes:

* technical, sector and event features: the day's own close;
* fundamentals: the ``known_from`` day of the reporting period;
* policy rate: the decision date; CPI: its release day; FX: the day's close;
* KAP disclosures: the first close after their publication time.

The table is the input of strategy variants C to E and of the fine-tuning examples.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Any

import numpy as np
import pandas as pd

from bist_harness.backtest.strategies import ENTRY_EVENTS
from bist_harness.data.fundamentals import known_from
from bist_harness.data.peers import peer_group_of
from bist_harness.errors import DataUnavailableError
from bist_harness.tools.events import (
    EVENT_TYPES,
    counted_mask,
    effective_direction,
    state_frame,
)
from bist_harness.tools.fundamentals import fundamental_change, known_periods
from bist_harness.tools.indicators import add_all_indicators
from bist_harness.tools.sector import lag_score_series

LAG_HORIZONS = (5, 10, 20, 60)
EVENT_WINDOW_DAYS = 60
FX_WINDOW_DAYS = 20
POLICY_WINDOW_DAYS = 60
NEWS_WINDOW_DAYS = 5


def _dates(values) -> np.ndarray:
    return pd.DatetimeIndex(values).to_numpy(dtype="datetime64[ns]")


def _datetimes(values) -> pd.DatetimeIndex:
    """Dates at one fixed resolution, so that columns compare equal whatever they hold."""
    return pd.DatetimeIndex(pd.to_datetime(values)).astype("datetime64[ns]")


def _as_of(index: pd.DatetimeIndex, dates, values) -> np.ndarray:
    """For each day of ``index``, the value whose date is the latest one on or before it.

    ``dates`` must be sorted. Days before the first date get ``None``.
    """
    positions = np.searchsorted(_dates(dates), _dates(index), side="right") - 1
    values = np.asarray(values, dtype=object)
    out = np.full(len(index), None, dtype=object)
    found = positions >= 0
    out[found] = values[positions[found]]
    return out


def _technical(history: pd.DataFrame) -> pd.DataFrame:
    frame = add_all_indicators(history)
    table = state_frame(frame)
    entry = pd.Series(False, index=frame.index)
    for event_type in ENTRY_EVENTS:
        entry |= counted_mask(frame, event_type, "BULLISH")
    table["entry_event"] = entry
    for direction in ("BULLISH", "BEARISH"):
        count = pd.Series(0, index=frame.index)
        for event_type in EVENT_TYPES:
            if effective_direction(event_type, direction) == direction:
                count += counted_mask(frame, event_type, direction).astype(int)
        column = f"{direction.lower()}_events_{EVENT_WINDOW_DAYS}d"
        table[column] = count.rolling(EVENT_WINDOW_DAYS, min_periods=1).sum().astype(int)
    return table


def _sector(table: pd.DataFrame, ticker: str, peer_closes: dict, benchmark) -> None:
    group = peer_group_of(ticker)
    for horizon in LAG_HORIZONS:
        lag = lag_score_series(
            peer_closes, group, ticker, horizon_days=horizon, benchmark=benchmark
        ).reindex(table.index)
        table[f"lag_score_{horizon}d_pct"] = lag["lag_score"] * 100
        if horizon == 20:
            table["sector_strong_20d"] = lag["sector_strong"].fillna(False).astype(bool)


def _fundamentals(table: pd.DataFrame, ticker: str, statements, calendar, cpi_index) -> None:
    periods, days, trends = [], [], []
    if statements is not None and calendar is not None:
        known = known_periods(calendar, ticker, str(table.index[-1].date()))
        for day in sorted(set(known["known_from"])):
            change = fundamental_change(
                statements,
                calendar,
                ticker=ticker,
                as_of=str(pd.Timestamp(day).date()),
                cpi=cpi_index,
            )
            if change is not None:
                days.append(pd.Timestamp(day))
                periods.append(change["period"])
                trends.append(change["fundamental_trend"])
    table["fundamental_period"] = _as_of(table.index, days, periods)
    table["fundamental_known_from"] = _datetimes(_as_of(table.index, days, days))
    table["fundamental_trend"] = _as_of(table.index, days, trends)


def _macro(table: pd.DataFrame, macro: dict | None) -> None:
    macro = macro or {}
    fx = macro.get("fx")
    if fx is not None and "USDTRY" in fx:
        change = (fx["USDTRY"] / fx["USDTRY"].shift(FX_WINDOW_DAYS) - 1) * 100
        # Yahoo's FX close is struck hours after the BIST close: day t sees day t-1.
        change.index = pd.DatetimeIndex(change.index) + pd.Timedelta(days=1)
        table["usdtry_change_20d_pct"] = change.reindex(table.index, method="ffill")
    else:
        table["usdtry_change_20d_pct"] = np.nan

    policy = macro.get("policy_rate")
    if policy is not None and len(policy):
        policy = policy.sort_values("effective_date")
        rates = policy["rate"].to_numpy(dtype=float)
        table["policy_rate"] = pd.to_numeric(_as_of(table.index, policy["effective_date"], rates))
        raises = policy[policy["rate"] > policy["rate"].shift(1)]
        last_raise = _datetimes(
            _as_of(table.index, raises["effective_date"], raises["effective_date"])
        )
        since = pd.Series(table.index - last_raise, index=table.index).dt.days
        table["policy_rate_raised_60d"] = (since <= POLICY_WINDOW_DAYS).fillna(False).to_numpy()
    else:
        table["policy_rate"] = np.nan
        table["policy_rate_raised_60d"] = False

    cpi = macro.get("cpi")
    if cpi is not None and len(cpi):
        cpi = cpi.sort_values("published")
        table["cpi_annual_pct"] = pd.to_numeric(
            _as_of(table.index, cpi["published"], cpi["annual_pct"].to_numpy(dtype=float))
        )
        table["cpi_published"] = _datetimes(_as_of(table.index, cpi["published"], cpi["published"]))
    else:
        table["cpi_annual_pct"] = np.nan
        table["cpi_published"] = _datetimes([pd.NaT] * len(table))


def _news(table: pd.DataFrame, ticker: str, disclosures) -> None:
    counts = pd.Series(0.0, index=table.index)
    legal = pd.Series(0.0, index=table.index)
    if disclosures is not None and len(disclosures):
        own = disclosures[disclosures["ticker"] == ticker]
        for published, topic in zip(own["published_at"], own["topic"], strict=True):
            day = known_from(pd.Timestamp(published), table.index)
            if pd.isna(day):
                continue
            counts.at[day] += 1
            if topic == "regulation_legal":
                legal.at[day] += 1
    window = f"{NEWS_WINDOW_DAYS}D"
    table["kap_events_5d"] = counts.rolling(window).sum().astype(int)
    table["kap_regulation_legal_5d"] = legal.rolling(window).sum() > 0


def _build_feature_table(
    ticker: str,
    history: pd.DataFrame,
    *,
    peer_closes: dict[str, pd.Series],
    benchmark: pd.Series | None,
    statements: pd.DataFrame | None = None,
    calendar: pd.DataFrame | None = None,
    cpi_index: pd.Series | None = None,
    macro: dict[str, pd.DataFrame] | None = None,
    disclosures: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Features of one stock for every trading day of ``history``.

    A layer that is not supplied leaves its columns empty. ``info_date`` is the day
    whose close completes the row; no column carries information dated after it.
    """
    table = _technical(history)
    _sector(table, ticker, peer_closes, benchmark)
    _fundamentals(table, ticker, statements, calendar, cpi_index)
    _macro(table, macro)
    _news(table, ticker, disclosures)
    table["info_date"] = table.index
    return table


CACHE_LIMIT = 64
_CACHE: OrderedDict[str, pd.DataFrame] = OrderedDict()
_FINGERPRINTS: OrderedDict[int, tuple[Any, tuple, str]] = OrderedDict()
FINGERPRINT_LIMIT = 64


def _identity_parts() -> dict[str, str]:
    from bist_harness.data import snapshot

    return {
        "snapshot": snapshot.active_snapshot_id(),
        "adjustments": snapshot.adjustments_id(),
        "layers": snapshot.layers_id(),
    }


def _cache_identity() -> dict[str, str] | None:
    """The data versions a feature table depends on; ``None`` when they cannot be read
    (no snapshot built), in which case the cache is bypassed."""
    try:
        return _identity_parts()
    except (DataUnavailableError, ValueError, OSError):
        return None


def _frame_digest(frame: pd.DataFrame) -> str:
    """Hash of a frame, remembered per object so a frame shared by many calls (the
    disclosures or macro layer of a backtest) is hashed once."""
    known = _FINGERPRINTS.get(id(frame))
    if known is not None and known[0] is frame and known[1] == frame.shape:
        return known[2]
    digest = hashlib.sha256(_hash_frame(frame)).hexdigest()
    _FINGERPRINTS[id(frame)] = (frame, frame.shape, digest)
    while len(_FINGERPRINTS) > FINGERPRINT_LIMIT:
        _FINGERPRINTS.popitem(last=False)
    return digest


def _fingerprint(value: Any) -> Any:
    """A stable, hashable description of an argument for the cache key."""
    if isinstance(value, pd.DataFrame):
        return ("frame", value.shape, _frame_digest(value))
    if isinstance(value, pd.Series):
        return ("series", value.name, _frame_digest(value.to_frame()))
    if isinstance(value, dict):
        return tuple((str(k), _fingerprint(v)) for k, v in sorted(value.items(), key=str))
    return repr(value)


def _hash_frame(frame: pd.DataFrame) -> bytes:
    return (
        pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
        + "|".join(map(str, frame.columns)).encode()
    )


def clear_feature_cache() -> None:
    _CACHE.clear()
    _FINGERPRINTS.clear()


def build_feature_table(ticker: str, history: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    """Features of one stock for every trading day of ``history`` (cached in memory).

    The cache key holds the snapshot id, the corrections id, the layers id, the ticker and
    a fingerprint of every argument, so a rebuilt layer or other inputs never return
    stale features. See ``_build_feature_table`` for the arguments.
    """
    identity = _cache_identity()
    if identity is None:
        return _build_feature_table(ticker, history, **kwargs)
    key = repr(
        (
            sorted(identity.items()),
            ticker,
            _fingerprint(history),
            [(name, _fingerprint(value)) for name, value in sorted(kwargs.items())],
        )
    )
    cached = _CACHE.get(key)
    if cached is None:
        cached = _CACHE[key] = _build_feature_table(ticker, history, **kwargs)
        while len(_CACHE) > CACHE_LIMIT:
            _CACHE.popitem(last=False)
    else:
        _CACHE.move_to_end(key)
    return cached.copy()
