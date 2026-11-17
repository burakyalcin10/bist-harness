"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

MCP server exposing the deterministic analysis tools (project brief, section 22).

Tools read the active market-data snapshot and never download. Every tool
* returns a summary, never a raw series,
* rounds percentages and prices to two decimals,
* reports bad input as ``{"error": {"code", "message"}}`` instead of raising,
* names the ``snapshot_id`` it read and carries a ``result_id`` that is identical for
  identical input and data.

Run over stdio:  uv run python -m bist_harness.mcp_server.server
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta

import pandas as pd
from mcp.server.mcpserver import MCPServer

from bist_harness.backtest.periods import TEST as TEST_PERIOD
from bist_harness.backtest.runner import run_variant
from bist_harness.backtest.strategies import FEATURE_FILTERS, StrategyContext
from bist_harness.data import fundamentals as fundamentals_data
from bist_harness.data import kap as kap_data
from bist_harness.data import macro as macro_data
from bist_harness.data import peers, snapshot
from bist_harness.data.market import DATA_SOURCE
from bist_harness.errors import DataUnavailableError
from bist_harness.features.table import build_feature_table
from bist_harness.tools import calendar_patterns, events, support_resistance
from bist_harness.tools.disclosure import quarter_reactions, summarize_reactions
from bist_harness.tools.fundamentals import fundamental_change, fundamental_metrics
from bist_harness.tools.indicators import add_all_indicators, indicator_state
from bist_harness.tools.macro import macro_context
from bist_harness.tools.news import TOPICS as NEWS_TOPICS
from bist_harness.tools.news import news_events
from bist_harness.tools.schemas import (
    INDICATORS,
    REVERSAL_EVENT_TYPES,
    STRATEGY_VARIANTS,
    TOOL_SCHEMAS,
    WEEKDAY_PATTERNS,
)
from bist_harness.tools.sector import rank_sector_relative_strength as rank_sector
from bist_harness.universe import is_in_universe, load_universe, normalize_ticker

FORWARD_DAYS = (1, 3, 5, 10)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SECTOR_HORIZONS = (5, 10, 20, 60)
BENCHMARK = "XU100"
COVERAGE_SLACK_DAYS = 7

server = MCPServer(
    "bist-harness",
    instructions=(
        "Deterministic analysis tools for an educational BIST 100 research system. "
        "Outputs are historical evidence only, not investment advice."
    ),
)


def load_history(symbol: str) -> pd.DataFrame:
    """Full daily history of one stock or index from the active snapshot."""
    return snapshot.load_history(symbol)


def current_snapshot_id() -> str:
    return snapshot.active_snapshot_id()


def current_adjustments_id() -> str:
    return snapshot.adjustments_id()


def _parse_date(text: str) -> date | None:
    """A date written exactly as YYYY-MM-DD, or ``None``."""
    if not isinstance(text, str) or not _ISO_DATE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _versions() -> dict:
    """What identifies the data behind a result: snapshot, corrections file and source."""
    return {
        "snapshot_id": current_snapshot_id(),
        "adjustments_id": current_adjustments_id(),
        "data_source": DATA_SOURCE,
    }


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _with_result_id(tool: str, args: dict, output: dict) -> dict:
    canonical = json.dumps(
        {"tool": tool, "args": args, "output": output}, sort_keys=True, default=str
    )
    return {**output, "result_id": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]}


def _coverage(history: pd.DataFrame, start: str, end: str) -> dict:
    """Say which dates the cached data really covers, and warn if the request goes beyond.

    The snapshot is only refreshed on purpose, so a request can ask for days it does not
    hold. The output must show that instead of silently answering for a shorter period.
    """
    first_day, last_day = history.index[0].date(), history.index[-1].date()
    first, last = str(first_day), str(last_day)
    # A few days without bars at either edge are weekends or holidays, not missing data.
    slack = timedelta(days=COVERAGE_SLACK_DAYS)
    starts_early = date.fromisoformat(start) < first_day - slack
    ends_late = date.fromisoformat(end) > last_day + slack
    warning = None
    if starts_early or ends_late:
        warning = (
            f"Requested period {start} to {end} extends beyond the available data "
            f"({first} to {last}); results cover the available part only."
        )
    return {"data_first_date": first, "data_last_date": last, "coverage_warning": warning}


def _load_window(
    symbol: str, start: str, end: str, *, index: bool = False
) -> tuple[str, pd.DataFrame, dict] | dict:
    """Validate the request; return (symbol, history up to ``end``, metadata) or an error.

    The metadata (data coverage, snapshot id, data source) goes into every tool output.
    """
    if index:
        if normalize_ticker(symbol) not in snapshot.INDEX_SYMBOLS:
            known = ", ".join(snapshot.INDEX_SYMBOLS)
            return _error("UNKNOWN_INDEX", f"{symbol!r} is not available; indices: {known}.")
    elif not is_in_universe(symbol):
        return _error("UNKNOWN_TICKER", f"{symbol!r} is not one of the 30 study-universe stocks.")
    start_date, end_date = _parse_date(start), _parse_date(end)
    if start_date is None or end_date is None:
        return _error("INVALID_DATE", "Dates must be written as YYYY-MM-DD.")
    if start_date >= end_date:
        return _error("INVALID_DATE_RANGE", "start must be earlier than end.")
    if end_date > date.today():
        return _error("FUTURE_DATE", "end is in the future; tools only report history.")
    name = normalize_ticker(symbol)
    try:
        history = load_history(name)
        versions = _versions()
    except (DataUnavailableError, ValueError) as exc:  # ValueError: a broken corrections file
        return _error("DATA_UNAVAILABLE", str(exc))
    meta = {**_coverage(history, start, end), **versions}
    history = history.loc[: pd.Timestamp(end)]
    if history.loc[pd.Timestamp(start) :].empty:
        return _error("DATA_UNAVAILABLE", f"No market data for {name} between {start} and {end}.")
    return name, history, meta


def _history_summary(tool: str, key: str, symbol: str, start: str, end: str) -> dict:
    loaded = _load_window(symbol, start, end, index=key == "index")
    if isinstance(loaded, dict):
        return loaded
    name, history, meta = loaded
    close = history.loc[pd.Timestamp(start) :, "Close"]
    first, last = float(close.iloc[0]), float(close.iloc[-1])
    args = {key: name, "start": start, "end": end}
    output = {
        **args,
        "rows": int(len(close)),
        "first_date": str(close.index[0].date()),
        "last_date": str(close.index[-1].date()),
        "first_close": round(first, 2),
        "last_close": round(last, 2),
        "period_return_pct": round((last / first - 1) * 100, 2),
        **meta,
    }
    return _with_result_id(tool, args, output)


@server.tool(description=TOOL_SCHEMAS["get_stock_history"]["description"])
def get_stock_history(ticker: str, start: str, end: str) -> dict:
    return _history_summary("get_stock_history", "ticker", ticker, start, end)


@server.tool(description=TOOL_SCHEMAS["get_index_history"]["description"])
def get_index_history(index: str, start: str, end: str) -> dict:
    return _history_summary("get_index_history", "index", index, start, end)


@server.tool(description=TOOL_SCHEMAS["calculate_indicators"]["description"])
def calculate_indicators(ticker: str, start: str, end: str, indicators: list[str]) -> dict:
    loaded = _load_window(ticker, start, end)
    if isinstance(loaded, dict):
        return loaded
    name, history, meta = loaded
    unknown = [i for i in indicators if i not in INDICATORS]
    if unknown:
        return _error("INVALID_ARGUMENT", f"indicators must be chosen from {INDICATORS}.")
    groups = list(indicators) or list(INDICATORS)
    args = {"ticker": name, "start": start, "end": end, "indicators": groups}
    output = {**args, **indicator_state(add_all_indicators(history), groups), **meta}
    return _with_result_id("calculate_indicators", args, output)


SUPPORT_RESISTANCE_METHOD = (
    "Pivot highs and lows of an 11-day centred window, known 5 trading days after they "
    "happen; pivots within the tolerance form one level. Strength = touches + 1.5 x "
    "touches in the last 60 trading days + 1.2 x high-volume reactions + one point per 5% "
    "of average move away from the level (at most 3). The list holds the strongest levels; "
    "the nearest support and resistance are taken from all levels found."
)
MAX_TOLERANCE = 0.10
MAX_LEVELS = 6


@server.tool(description=TOOL_SCHEMAS["find_support_resistance"]["description"])
def find_support_resistance(ticker: str, start: str, end: str, tolerance: float = 0.015) -> dict:
    loaded = _load_window(ticker, start, end)
    if isinstance(loaded, dict):
        return loaded
    name, history, meta = loaded
    if not 0 < tolerance <= MAX_TOLERANCE:
        return _error("INVALID_ARGUMENT", f"tolerance must be above 0 and at most {MAX_TOLERANCE}.")
    window = history.loc[pd.Timestamp(start) :]
    found = support_resistance.find_support_resistance(window, tolerance=tolerance, max_levels=None)
    supports = [lv["level"] for lv in found if lv["kind"] == "support"]
    resistances = [lv["level"] for lv in found if lv["kind"] == "resistance"]
    warnings = []
    if len(window) < support_resistance.MIN_ROWS:
        warnings.append(
            f"TOO_FEW_BARS: the period has {len(window)} trading days; levels need at "
            f"least {support_resistance.MIN_ROWS}."
        )
    args = {"ticker": name, "start": start, "end": end, "tolerance": tolerance}
    output = {
        **args,
        "last_close": round(float(window["Close"].iloc[-1]), 2),
        "levels_found": len(found),
        "levels": found[:MAX_LEVELS],
        "nearest_support": max(supports) if supports else None,
        "nearest_resistance": min(resistances) if resistances else None,
        "warnings": warnings,
        "method": SUPPORT_RESISTANCE_METHOD,
        **meta,
    }
    return _with_result_id("find_support_resistance", args, output)


@server.tool(description=TOOL_SCHEMAS["detect_reversal_events"]["description"])
def detect_reversal_events(
    ticker: str,
    start: str,
    end: str,
    event_type: str = "BOLLINGER_LOWER_TOUCH",
    forward_days: int = 5,
    direction: str = "BULLISH",
) -> dict:
    loaded = _load_window(ticker, start, end)
    if isinstance(loaded, dict):
        return loaded
    name, history, meta = loaded
    if event_type not in REVERSAL_EVENT_TYPES:
        return _error("INVALID_ARGUMENT", f"event_type must be one of {REVERSAL_EVENT_TYPES}.")
    if forward_days not in FORWARD_DAYS:
        return _error("INVALID_ARGUMENT", f"forward_days must be one of {list(FORWARD_DAYS)}.")
    if direction not in events.DIRECTIONS:
        return _error("INVALID_ARGUMENT", f"direction must be one of {list(events.DIRECTIONS)}.")

    result = events.detect_events(
        history, event_type, direction, forward_days=forward_days, since=start
    )
    args = {
        "ticker": name,
        "start": start,
        "end": end,
        "event_type": event_type,
        "forward_days": forward_days,
        "direction": result["direction"],
    }
    return _with_result_id("detect_reversal_events", args, {**args, **result, **meta})


@server.tool(description=TOOL_SCHEMAS["test_weekday_pattern"]["description"])
def test_weekday_pattern(ticker: str, pattern: str, start: str, end: str) -> dict:
    loaded = _load_window(ticker, start, end)
    if isinstance(loaded, dict):
        return loaded
    name, history, meta = loaded
    if pattern not in WEEKDAY_PATTERNS:
        return _error("INVALID_ARGUMENT", f"pattern must be one of {WEEKDAY_PATTERNS}.")
    result = calendar_patterns.evaluate_pattern(history, pattern, since=start)
    args = {"ticker": name, "pattern": pattern, "start": start, "end": end}
    return _with_result_id("test_weekday_pattern", args, {**args, **result, **meta})


def _check_as_of(as_of: str) -> dict | None:
    day = _parse_date(as_of)
    if day is None:
        return _error("INVALID_DATE", "Dates must be written as YYYY-MM-DD.")
    if day > date.today():
        return _error("FUTURE_DATE", "as_of is in the future; tools only report history.")
    return None


@server.tool(description=TOOL_SCHEMAS["rank_sector_relative_strength"]["description"])
def rank_sector_relative_strength(sector: str, horizon_days: int, as_of: str) -> dict:
    problem = _check_as_of(as_of)
    if problem:
        return problem
    if horizon_days not in SECTOR_HORIZONS:
        return _error("INVALID_ARGUMENT", f"horizon_days must be one of {list(SECTOR_HORIZONS)}.")
    try:
        group = peers.resolve_sector(sector)
    except KeyError:
        names = ", ".join(peers.load_peer_groups())
        return _error("UNKNOWN_SECTOR", f"{sector!r} is not a sector of the universe: {names}.")
    try:
        versions = _versions()
    except DataUnavailableError as exc:
        return _error("DATA_UNAVAILABLE", str(exc))

    closes: dict[str, pd.Series] = {}
    for symbol in (*group.members, BENCHMARK):
        try:
            closes[symbol] = load_history(symbol)["Close"]
        except DataUnavailableError:
            continue
        except ValueError as exc:  # a broken corrections file must not pass silently
            return _error("DATA_UNAVAILABLE", str(exc))
    result = rank_sector(
        closes, group, horizon_days=horizon_days, as_of=as_of, benchmark=closes.get(BENCHMARK)
    )
    if not result["members"]:
        return _error("DATA_UNAVAILABLE", f"No market data for the {group.name} group on {as_of}.")
    args = {"sector": group.name, "horizon_days": horizon_days, "as_of": as_of}
    output = {**result, "benchmark": BENCHMARK, **versions}
    return _with_result_id("rank_sector_relative_strength", args, output)


def load_statements() -> pd.DataFrame:
    """Statement items of every stock from the active snapshot."""
    return fundamentals_data.load_statements()


def load_disclosure_calendar() -> pd.DataFrame:
    return fundamentals_data.load_disclosure_calendar()


FUNDAMENTAL_SOURCES = (
    "Statements: İş Yatırım public financial-statement service (cumulative values per "
    "reporting period). Publication times: KAP financial-report disclosures. A period is "
    "used from the first trading day whose close follows its publication."
)
MAX_QUARTERS = 8


def _fundamental_inputs(ticker: str, as_of: str) -> dict | tuple:
    """Validate and load what both fundamental tools need, or return an error object."""
    if not is_in_universe(ticker):
        return _error("UNKNOWN_TICKER", f"{ticker!r} is not one of the 30 study-universe stocks.")
    problem = _check_as_of(as_of)
    if problem:
        return problem
    name = normalize_ticker(ticker)
    try:
        statements, calendar = load_statements(), load_disclosure_calendar()
        versions = _versions()
    except (DataUnavailableError, ValueError) as exc:
        return _error("DATA_UNAVAILABLE", str(exc))
    try:
        cpi = macro_data.cpi_index(load_macro("cpi"))
    except DataUnavailableError:
        cpi = None
    try:
        close = load_history(name)["Close"]
    except (DataUnavailableError, ValueError):
        close = None
    versions["data_source"] = FUNDAMENTAL_SOURCES
    return name, statements, calendar, cpi, close, versions


def _no_statement(name: str, as_of: str) -> dict:
    return _error("DATA_UNAVAILABLE", f"No financial statement of {name} was public on {as_of}.")


def _add_reactions(result: dict, name: str, calendar, close, as_of: str) -> None:
    """Attach the post-disclosure price reaction to each quarter and a summary of all."""
    fields = (
        ("reaction_1d_pct", "return_1d_pct"),
        ("reaction_5d_pct", "return_5d_pct"),
        ("reaction_20d_pct", "return_20d_pct"),
        ("abnormal_vs_index_5d_pct", "abnormal_vs_index_5d_pct"),
        ("abnormal_vs_peers_5d_pct", "abnormal_vs_peers_5d_pct"),
    )
    if close is None:
        for quarter in result["quarters"]:
            quarter.update({key: None for key, _ in fields})
        result["reaction_summary"] = None
        return
    peer_closes: dict[str, pd.Series] = {}
    for member in peers.peer_group_of(name).members:
        if member != name:
            try:
                peer_closes[member] = load_history(member)["Close"]
            except (DataUnavailableError, ValueError):
                continue
    try:
        benchmark = load_history(BENCHMARK)["Close"]
    except (DataUnavailableError, ValueError):
        benchmark = None
    known = calendar[calendar["ticker"] == name]
    table = quarter_reactions(known, close, benchmark=benchmark, peers=peer_closes, as_of=as_of)
    by_period = {row["period"]: row for row in table.to_dict("records")}
    for quarter in result["quarters"]:
        row = by_period.get(quarter["period"], {})
        for key, column in fields:
            value = row.get(column)
            quarter[key] = None if value is None or pd.isna(value) else float(value)
    result["reaction_summary"] = summarize_reactions(table)


@server.tool(description=TOOL_SCHEMAS["get_fundamental_metrics"]["description"])
def get_fundamental_metrics(ticker: str, as_of: str) -> dict:
    loaded = _fundamental_inputs(ticker, as_of)
    if isinstance(loaded, dict):
        return loaded
    name, statements, calendar, cpi, close, versions = loaded
    result = fundamental_metrics(
        statements, calendar, ticker=name, as_of=as_of, close=close, cpi=cpi
    )
    if result is None:
        return _no_statement(name, as_of)
    args = {"ticker": name, "as_of": as_of}
    return _with_result_id("get_fundamental_metrics", args, {**result, **versions})


@server.tool(description=TOOL_SCHEMAS["calculate_fundamental_change"]["description"])
def calculate_fundamental_change(ticker: str, as_of: str, periods: int = 4) -> dict:
    loaded = _fundamental_inputs(ticker, as_of)
    if isinstance(loaded, dict):
        return loaded
    name, statements, calendar, cpi, close, versions = loaded
    if (
        isinstance(periods, bool)
        or not isinstance(periods, int)
        or not 1 <= periods <= MAX_QUARTERS
    ):
        return _error(
            "INVALID_ARGUMENT", f"periods must be a whole number from 1 to {MAX_QUARTERS}."
        )
    result = fundamental_change(
        statements, calendar, ticker=name, as_of=as_of, periods=periods, cpi=cpi
    )
    if result is None:
        return _no_statement(name, as_of)
    _add_reactions(result, name, calendar, close, as_of)
    args = {"ticker": name, "as_of": as_of, "periods": periods}
    return _with_result_id("calculate_fundamental_change", args, {**args, **result, **versions})


def load_disclosures() -> pd.DataFrame:
    """KAP disclosure metadata from the active snapshot."""
    return kap_data.load_disclosures()


NEWS_SOURCE = (
    "KAP (public disclosure platform) material-event disclosures: metadata only, with "
    "the official publication time. Context, not a substitute for numerical data."
)


@server.tool(description=TOOL_SCHEMAS["get_news_events"]["description"])
def get_news_events(
    start: str, end: str, ticker: str | None = None, topic: str | None = None
) -> dict:
    problem = _period_problem(start, end)
    if problem:
        return problem
    if ticker is not None and not is_in_universe(ticker):
        return _error("UNKNOWN_TICKER", f"{ticker!r} is not one of the 30 study-universe stocks.")
    if topic is not None and topic not in NEWS_TOPICS:
        return _error("INVALID_ARGUMENT", f"topic must be one of {list(NEWS_TOPICS)}.")
    try:
        disclosures = load_disclosures()
        versions = _versions()
    except DataUnavailableError as exc:
        return _error("DATA_UNAVAILABLE", str(exc))
    result = news_events(disclosures, start=start, end=end, ticker=ticker, topic=topic)
    first_held = disclosures["published_at"].min() if len(disclosures) else None
    result["data_first_date"] = None if first_held is None else str(first_held.date())
    if first_held is not None and pd.Timestamp(start) < first_held.normalize():
        result["warnings"].append(
            f"COVERAGE_STARTS_LATER: disclosures are held from {first_held.date()}; "
            "earlier days are not covered, which is not the same as no disclosure."
        )
    versions["data_source"] = NEWS_SOURCE
    args = {"start": start, "end": end, "ticker": result["ticker"], "topic": topic}
    return _with_result_id("get_news_events", args, {**result, **versions})


def _period_problem(start: str, end: str) -> dict | None:
    """Error object for a bad period, or ``None``."""
    start_date, end_date = _parse_date(start), _parse_date(end)
    if start_date is None or end_date is None:
        return _error("INVALID_DATE", "Dates must be written as YYYY-MM-DD.")
    if start_date >= end_date:
        return _error("INVALID_DATE_RANGE", "start must be earlier than end.")
    if end_date > date.today():
        return _error("FUTURE_DATE", "end is in the future; tools only report history.")
    return None


def load_macro(name: str) -> pd.DataFrame:
    """One macro series from the active snapshot."""
    return macro_data.load_macro(name)


MACRO_SOURCES = (
    "USD/TRY and EUR/TRY: Yahoo Finance daily closes. Policy rate: TCMB one-week repo "
    "decision table. Fed target range: Federal Reserve open-market page. CPI: TCMB "
    "consumer-price table (TÜİK figures), counted from its release day."
)


@server.tool(description=TOOL_SCHEMAS["get_macro_context"]["description"])
def get_macro_context(start: str, end: str) -> dict:
    problem = _period_problem(start, end)
    if problem:
        return problem
    series: dict[str, pd.DataFrame] = {}
    missing = None
    for name in macro_data.SERIES:
        try:
            series[name] = load_macro(name)
        except DataUnavailableError as exc:
            missing = exc
    if not series:
        return _error("DATA_UNAVAILABLE", str(missing))
    try:
        versions = _versions()
    except DataUnavailableError as exc:
        return _error("DATA_UNAVAILABLE", str(exc))
    args = {"start": start, "end": end}
    output = {**macro_context(series, start=start, end=end), **versions}
    output["data_source"] = MACRO_SOURCES
    return _with_result_id("get_macro_context", args, output)


def _feature_layers(strategy: str) -> dict:
    """Load the layers a variant needs for its feature table, or return an error object."""
    try:
        layers: dict = {
            "statements": load_statements(),
            "calendar": load_disclosure_calendar(),
            "disclosures": None,
        }
    except (DataUnavailableError, ValueError) as exc:
        return _error("DATA_UNAVAILABLE", str(exc))
    macro: dict[str, pd.DataFrame] = {}
    for name in macro_data.SERIES:
        try:
            macro[name] = load_macro(name)
        except DataUnavailableError as exc:
            if name == "policy_rate" and "macro" in FEATURE_FILTERS[strategy]:
                return _error("DATA_UNAVAILABLE", str(exc))
    layers["macro"] = macro
    layers["cpi_index"] = macro_data.cpi_index(macro["cpi"]) if "cpi" in macro else None
    if "news" in FEATURE_FILTERS[strategy]:
        try:
            layers["disclosures"] = load_disclosures()
        except DataUnavailableError as exc:
            return _error("DATA_UNAVAILABLE", str(exc))
    return layers


@server.tool(description=TOOL_SCHEMAS["run_backtest"]["description"])
def run_backtest(strategy: str, universe: list[str], start: str, end: str) -> dict:
    problem = _period_problem(start, end)
    if problem:
        return problem
    if strategy not in STRATEGY_VARIANTS:
        return _error("INVALID_ARGUMENT", f"strategy must be one of {STRATEGY_VARIANTS}.")
    if not isinstance(universe, list) or not all(isinstance(t, str) for t in universe):
        return _error("INVALID_ARGUMENT", "universe must be a list of tickers (empty for all).")
    unknown = [t for t in universe if not is_in_universe(t)]
    if unknown:
        return _error("UNKNOWN_TICKER", f"{unknown} are not among the 30 study-universe stocks.")
    needs_features = strategy in FEATURE_FILTERS
    effective_start = start
    if needs_features and end < TEST_PERIOD[0]:
        return _error(
            "INVALID_DATE_RANGE",
            f"{strategy} uses fundamentals and is defined from {TEST_PERIOD[0]} on.",
        )
    tickers = [normalize_ticker(t) for t in universe] or list(load_universe()["ticker"])
    tickers = list(dict.fromkeys(tickers))

    try:
        versions = _versions()
        benchmark = load_history(BENCHMARK)["Close"].loc[: pd.Timestamp(end)]
    except (DataUnavailableError, ValueError) as exc:
        return _error("DATA_UNAVAILABLE", str(exc))
    warnings: list[str] = []
    histories: dict[str, pd.DataFrame] = {}
    peer_closes: dict[str, pd.Series] = {}
    for ticker in tickers:
        try:
            histories[ticker] = load_history(ticker).loc[: pd.Timestamp(end)]
        except DataUnavailableError:
            warnings.append(f"NO_DATA: {ticker} is not in the snapshot and was left out.")
            continue
        except ValueError as exc:
            return _error("DATA_UNAVAILABLE", str(exc))
        for member in peers.peer_group_of(ticker).members:
            if member not in peer_closes:
                try:
                    peer_closes[member] = load_history(member)["Close"].loc[: pd.Timestamp(end)]
                except (DataUnavailableError, ValueError):
                    continue
    in_period = [t for t, h in histories.items() if not h.loc[pd.Timestamp(start) :].empty]
    if not in_period or benchmark.loc[pd.Timestamp(start) :].empty:
        return _error("DATA_UNAVAILABLE", f"No market data between {start} and {end}.")

    data_first = benchmark.index[0]
    if pd.Timestamp(start) < data_first - timedelta(days=COVERAGE_SLACK_DAYS):
        warnings.append(
            f"DATA_STARTS_LATER: market data begin on {data_first.date()}; the backtest "
            f"covers the part of the period from that day on."
        )
    features = None
    if needs_features:
        warnings.append(
            "FUNDAMENTALS_NOT_POINT_IN_TIME: the statement source restates earlier periods "
            "at a later price level, so the fundamental trend behind these signals is not "
            "exactly what was computable on the signal day."
        )
        if start < TEST_PERIOD[0]:
            effective_start = TEST_PERIOD[0]
            warnings.append(
                f"NOT_AVAILABLE_BEFORE_2025: {strategy} uses fundamentals; signals before "
                f"{TEST_PERIOD[0]} were not traded."
            )
        layers = _feature_layers(strategy)
        if "error" in layers:
            return layers
        features = {
            t: build_feature_table(
                t, histories[t], peer_closes=peer_closes, benchmark=benchmark, **layers
            )
            for t in in_period
        }
    context = StrategyContext(
        histories={t: histories[t] for t in in_period},
        peer_closes=peer_closes,
        benchmark=benchmark,
        features=features,
    )
    result = run_variant(strategy, context, start=effective_start, end=end)
    result["effective_start"] = effective_start
    result["data_first_date"] = str(data_first.date())
    args = {"strategy": strategy, "universe": tickers, "start": start, "end": end}
    output = {**args, **result, "benchmark": BENCHMARK, "warnings": warnings, **versions}
    return _with_result_id("run_backtest", args, output)


def unwrap_tool_result(result) -> dict:
    """Turn an MCP ``CallToolResult`` back into the tool's own dictionary.

    When MCP itself rejects the call (arguments that do not fit the tool's signature),
    the result carries an error text instead of JSON. That becomes an ``INVALID_ARGUMENT``
    error object, so a bad call from the model is reported back rather than crashing.
    """
    texts = [
        t for t in (getattr(b, "text", None) for b in getattr(result, "content", None) or []) if t
    ]
    if getattr(result, "is_error", False):
        detail = texts[0].strip().splitlines()[0][:200] if texts else "the call was rejected"
        return _error("INVALID_ARGUMENT", f"The tool rejected the call: {detail}")
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        if set(structured) == {"result"} and isinstance(structured["result"], dict):
            return structured["result"]
        return structured
    for text in texts:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return _error("INVALID_ARGUMENT", "The tool returned a reply that is not JSON.")
        if isinstance(value, dict):
            return value
    return _error("EMPTY_RESULT", "The tool returned no content.")


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
