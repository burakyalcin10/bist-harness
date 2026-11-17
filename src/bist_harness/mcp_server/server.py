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
from datetime import date, timedelta

import pandas as pd
from mcp.server.mcpserver import MCPServer

from bist_harness.data import snapshot
from bist_harness.data.market import DATA_SOURCE
from bist_harness.errors import DataUnavailableError
from bist_harness.tools import events, support_resistance
from bist_harness.tools.indicators import add_all_indicators, indicator_state
from bist_harness.tools.schemas import INDICATORS, REVERSAL_EVENT_TYPES, TOOL_SCHEMAS
from bist_harness.universe import is_in_universe, normalize_ticker

FORWARD_DAYS = (1, 3, 5, 10)
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
    try:
        start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return _error("INVALID_DATE", "Dates must be written as YYYY-MM-DD.")
    if start_date >= end_date:
        return _error("INVALID_DATE_RANGE", "start must be earlier than end.")
    if end_date > date.today():
        return _error("FUTURE_DATE", "end is in the future; tools only report history.")
    name = normalize_ticker(symbol)
    try:
        history = load_history(name)
        snapshot_id = current_snapshot_id()
    except DataUnavailableError as exc:
        return _error("DATA_UNAVAILABLE", str(exc))
    meta = {
        **_coverage(history, start, end),
        "snapshot_id": snapshot_id,
        "data_source": DATA_SOURCE,
    }
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
    "touches in the last 60 trading days + 1.2 x high-volume reactions + average move "
    "away from the level in percent."
)
MAX_TOLERANCE = 0.10


@server.tool(description=TOOL_SCHEMAS["find_support_resistance"]["description"])
def find_support_resistance(ticker: str, start: str, end: str, tolerance: float = 0.015) -> dict:
    loaded = _load_window(ticker, start, end)
    if isinstance(loaded, dict):
        return loaded
    name, history, meta = loaded
    if not 0 < tolerance <= MAX_TOLERANCE:
        return _error("INVALID_ARGUMENT", f"tolerance must be above 0 and at most {MAX_TOLERANCE}.")
    window = history.loc[pd.Timestamp(start) :]
    levels = support_resistance.find_support_resistance(window, tolerance=tolerance)
    supports = [lv["level"] for lv in levels if lv["kind"] == "support"]
    resistances = [lv["level"] for lv in levels if lv["kind"] == "resistance"]
    args = {"ticker": name, "start": start, "end": end, "tolerance": tolerance}
    output = {
        **args,
        "last_close": round(float(window["Close"].iloc[-1]), 2),
        "levels": levels,
        "nearest_support": max(supports) if supports else None,
        "nearest_resistance": min(resistances) if resistances else None,
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
