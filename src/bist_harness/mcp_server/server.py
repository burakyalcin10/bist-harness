"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

MCP server exposing the deterministic analysis tools (project brief, section 22).

Sprint 1 implements two tools for the thin end-to-end slice. Every tool
* returns a summary, never a raw series,
* rounds percentages and prices to two decimals,
* reports bad input as ``{"error": {"code", "message"}}`` instead of raising,
* carries a ``result_id`` that is identical for identical input and data.

Run over stdio:  uv run python -m bist_harness.mcp_server.server
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pandas as pd
from mcp.server.mcpserver import MCPServer

from bist_harness.data.market import DATA_SOURCE, load_stock_data
from bist_harness.errors import DataUnavailableError
from bist_harness.tools.reversal import bollinger_lower_touch_summary
from bist_harness.tools.schemas import REVERSAL_EVENT_TYPES, TOOL_SCHEMAS
from bist_harness.universe import is_in_universe, normalize_ticker

HISTORY_START = "2020-01-01"
FORWARD_DAYS = (1, 3, 5, 10)
COVERAGE_SLACK_DAYS = 7
IMPLEMENTED_EVENTS = {"BOLLINGER_LOWER_TOUCH"}
BOLLINGER_LOWER_TOUCH_DEFINITION = (
    "Previous close at or below the lower Bollinger band (20-day mean minus 2 standard "
    "deviations) and today's close back above it. The forward return is measured from "
    "the event day's close."
)

server = MCPServer(
    "bist-harness",
    instructions=(
        "Deterministic analysis tools for an educational BIST 100 research system. "
        "Outputs are historical evidence only, not investment advice."
    ),
)


def load_history(ticker: str) -> pd.DataFrame:
    """Full cached daily history of one stock (one snapshot per ticker)."""
    return load_stock_data(ticker, HISTORY_START)


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


def _load_window(ticker: str, start: str, end: str) -> tuple[str, pd.DataFrame, dict] | dict:
    """Validate the request; return (ticker, history up to ``end``, coverage) or an error."""
    if not is_in_universe(ticker):
        return _error("UNKNOWN_TICKER", f"{ticker!r} is not one of the 30 study-universe stocks.")
    try:
        start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        return _error("INVALID_DATE", "Dates must be written as YYYY-MM-DD.")
    if start_date >= end_date:
        return _error("INVALID_DATE_RANGE", "start must be earlier than end.")
    if end_date > date.today():
        return _error("FUTURE_DATE", "end is in the future; tools only report history.")
    name = normalize_ticker(ticker)
    try:
        history = load_history(name)
    except DataUnavailableError as exc:
        return _error("DATA_UNAVAILABLE", str(exc))
    coverage = _coverage(history, start, end)
    history = history.loc[: pd.Timestamp(end)]
    if history.loc[pd.Timestamp(start) :].empty:
        return _error("DATA_UNAVAILABLE", f"No market data for {name} between {start} and {end}.")
    return name, history, coverage


@server.tool(description=TOOL_SCHEMAS["get_stock_history"]["description"])
def get_stock_history(ticker: str, start: str, end: str) -> dict:
    loaded = _load_window(ticker, start, end)
    if isinstance(loaded, dict):
        return loaded
    name, history, coverage = loaded
    close = history.loc[pd.Timestamp(start) :, "Close"]
    first, last = float(close.iloc[0]), float(close.iloc[-1])
    output = {
        "ticker": name,
        "start": start,
        "end": end,
        "rows": int(len(close)),
        "first_date": str(close.index[0].date()),
        "last_date": str(close.index[-1].date()),
        "first_close": round(first, 2),
        "last_close": round(last, 2),
        "period_return_pct": round((last / first - 1) * 100, 2),
        **coverage,
        "data_source": DATA_SOURCE,
    }
    return _with_result_id(
        "get_stock_history", {"ticker": name, "start": start, "end": end}, output
    )


@server.tool(description=TOOL_SCHEMAS["detect_reversal_events"]["description"])
def detect_reversal_events(
    ticker: str,
    start: str,
    end: str,
    event_type: str = "BOLLINGER_LOWER_TOUCH",
    forward_days: int = 5,
) -> dict:
    loaded = _load_window(ticker, start, end)
    if isinstance(loaded, dict):
        return loaded
    name, history, coverage = loaded
    if event_type not in REVERSAL_EVENT_TYPES:
        return _error("INVALID_ARGUMENT", f"event_type must be one of {REVERSAL_EVENT_TYPES}.")
    if forward_days not in FORWARD_DAYS:
        return _error("INVALID_ARGUMENT", f"forward_days must be one of {list(FORWARD_DAYS)}.")
    if event_type not in IMPLEMENTED_EVENTS:
        return _error("NOT_IMPLEMENTED", f"{event_type} is not available yet.")

    summary = bollinger_lower_touch_summary(history, forward_days=forward_days, since=start)
    args = {
        "ticker": name,
        "start": start,
        "end": end,
        "event_type": event_type,
        "forward_days": forward_days,
    }
    output = {
        **args,
        **summary,
        **coverage,
        "definition": BOLLINGER_LOWER_TOUCH_DEFINITION,
        "data_source": DATA_SOURCE,
    }
    return _with_result_id("detect_reversal_events", args, output)


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
