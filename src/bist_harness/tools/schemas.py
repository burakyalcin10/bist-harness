"""Tool contracts (project brief, section 22) and the finite action space (section 17).

This module is the single source of truth for tool names and parameters. The MCP
server, the harness, the fine-tuning data generator and the evaluation scripts all
read it, so a tool can never be described to the model one way and implemented another.
"""

from __future__ import annotations

from collections.abc import Iterable

ACTIONS: tuple[str, ...] = (
    "HOLD",
    "WATCH",
    "INVESTIGATE",
    "POTENTIAL_CATCH_UP_CANDIDATE",
    "TECHNICAL_REVERSAL_CANDIDATE",
    "FUNDAMENTAL_IMPROVEMENT_CANDIDATE",
    "REJECT_SIGNAL",
    "ANALYSIS_UNSAFE",
)

INDICATORS = [
    "SMA",
    "EMA",
    "KAMA",
    "RSI",
    "MACD",
    "BOLLINGER",
    "ATR",
    "SUPERTREND",
    "ICHIMOKU",
    "VOLUME",
]

REVERSAL_EVENT_TYPES = [
    "BOLLINGER_LOWER_TOUCH",
    "BOLLINGER_MIDDLE_TEST",
    "BOLLINGER_UPPER_TOUCH",
    "RSI_LOCAL_TROUGH",
    "RSI_LOCAL_PEAK",
    "SUPERTREND_FLIP",
    "KAMA_TURN",
    "ICHIMOKU_BREAKOUT",
    "SUPPORT_RESISTANCE_TOUCH",
]

WEEKDAY_PATTERNS = [
    "WEEKDAY_MEANS",
    "MON_WEAK_FRI_STRONG",
    "THREE_DOWN_TWO_UP",
    "POST_LARGE_DOWN_REVERSION",
    "END_OF_WEEK_CONTINUATION",
]

STRATEGY_VARIANTS = [
    "A_TECHNICAL",
    "B_TECH_SECTOR",
    "C_TECH_SECTOR_FUND",
    "D_FULL_STRUCTURED",
    "E_FULL_CONTEXTUAL",
]

_TICKER = {
    "type": "string",
    "description": "BIST ticker in upper case without the .IS suffix, e.g. ASELS.",
}
_START = {"type": "string", "description": "First date of the period, YYYY-MM-DD."}
_END = {"type": "string", "description": "Last date of the period, YYYY-MM-DD."}
_AS_OF = {
    "type": "string",
    "description": "Analysis date, YYYY-MM-DD. Only data public on or before it is used.",
}
_ANALYSIS_ID = {
    "type": "string",
    "description": "Identifier of the running analysis, issued by the harness.",
}


def _obj(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOL_SCHEMAS: dict[str, dict] = {
    "get_stock_history": {
        "description": "Daily adjusted OHLCV summary for one stock over a period.",
        "parameters": _obj(
            {"ticker": _TICKER, "start": _START, "end": _END}, ["ticker", "start", "end"]
        ),
    },
    "get_index_history": {
        "description": "Daily benchmark index summary (e.g. XU100) over a period.",
        "parameters": _obj(
            {
                "index": {"type": "string", "description": "Index code, e.g. XU100 or XBANK."},
                "start": _START,
                "end": _END,
            },
            ["index", "start", "end"],
        ),
    },
    "calculate_indicators": {
        "description": "Latest values and states of technical indicators for one stock.",
        "parameters": _obj(
            {
                "ticker": _TICKER,
                "start": _START,
                "end": _END,
                "indicators": {
                    "type": "array",
                    "items": {"type": "string", "enum": INDICATORS},
                    "description": "Indicators to compute; an empty list means all.",
                },
            },
            ["ticker", "start", "end", "indicators"],
        ),
    },
    "detect_reversal_events": {
        "description": (
            "Historical technical reversal events of one type for one stock, "
            "with forward-return statistics after the events."
        ),
        "parameters": _obj(
            {
                "ticker": _TICKER,
                "start": _START,
                "end": _END,
                "event_type": {
                    "type": "string",
                    "enum": REVERSAL_EVENT_TYPES,
                    "description": "Event family to detect.",
                },
                "forward_days": {
                    "type": "integer",
                    "enum": [1, 3, 5, 10],
                    "description": "Trading days after the event used for the forward return.",
                },
                "direction": {
                    "type": "string",
                    "enum": ["BULLISH", "BEARISH"],
                    "description": (
                        "Side of the event (default BULLISH). Ignored by one-sided "
                        "families such as BOLLINGER_LOWER_TOUCH."
                    ),
                },
            },
            ["ticker", "start", "end", "event_type"],
        ),
    },
    "find_support_resistance": {
        "description": "Support and resistance levels with touch counts and strength scores.",
        "parameters": _obj(
            {
                "ticker": _TICKER,
                "start": _START,
                "end": _END,
                "tolerance": {
                    "type": "number",
                    "description": "Relative distance for clustering pivots (default 0.015).",
                },
            },
            ["ticker", "start", "end"],
        ),
    },
    "rank_sector_relative_strength": {
        "description": (
            "Rank the stocks of one sector by return versus the sector median "
            "over a horizon: leaders, laggards and lag scores."
        ),
        "parameters": _obj(
            {
                "sector": {
                    "type": "string",
                    "description": "Sector name from the study universe, e.g. Banking.",
                },
                "horizon_days": {
                    "type": "integer",
                    "enum": [5, 10, 20, 60],
                    "description": "Look-back window in trading days.",
                },
                "as_of": _AS_OF,
            },
            ["sector", "horizon_days", "as_of"],
        ),
    },
    "test_weekday_pattern": {
        "description": (
            "Test a day-of-week or multi-day return pattern for one stock: occurrences, "
            "conditional returns, out-of-sample result and significance diagnostics."
        ),
        "parameters": _obj(
            {
                "ticker": _TICKER,
                "pattern": {
                    "type": "string",
                    "enum": WEEKDAY_PATTERNS,
                    "description": "Pattern to test.",
                },
                "start": _START,
                "end": _END,
            },
            ["ticker", "pattern", "start", "end"],
        ),
    },
    "get_fundamental_metrics": {
        "description": (
            "Point-in-time fundamental metrics from the latest financial statement "
            "that was public on the analysis date."
        ),
        "parameters": _obj({"ticker": _TICKER, "as_of": _AS_OF}, ["ticker", "as_of"]),
    },
    "calculate_fundamental_change": {
        "description": "Quarterly and annual changes in fundamentals up to the analysis date.",
        "parameters": _obj(
            {
                "ticker": _TICKER,
                "as_of": _AS_OF,
                "periods": {
                    "type": "integer",
                    "description": "Number of reported quarters to compare (default 4).",
                },
            },
            ["ticker", "as_of"],
        ),
    },
    "get_macro_context": {
        "description": (
            "FX, CBRT policy rate, Fed funds target and CPI over a period, "
            "aligned by publication date."
        ),
        "parameters": _obj({"start": _START, "end": _END}, ["start", "end"]),
    },
    "get_news_events": {
        "description": "Timestamped disclosure and news event metadata for a stock or a topic.",
        "parameters": _obj(
            {
                "ticker": {**_TICKER, "description": _TICKER["description"] + " Optional."},
                "topic": {
                    "type": "string",
                    "description": "Optional topic tag, e.g. earnings, FX, rates, regulation.",
                },
                "start": _START,
                "end": _END,
            },
            ["start", "end"],
        ),
    },
    "get_speech_features": {
        "description": "Topics, claims and stance extracted from one approved public video.",
        "parameters": _obj(
            {
                "source_id": {
                    "type": "string",
                    "description": "Identifier of the approved video segment.",
                }
            },
            ["source_id"],
        ),
    },
    "run_backtest": {
        "description": (
            "Historical verification of one strategy variant: performance, "
            "benchmark difference and the trade log summary."
        ),
        "parameters": _obj(
            {
                "strategy": {
                    "type": "string",
                    "enum": STRATEGY_VARIANTS,
                    "description": "Strategy variant to verify.",
                },
                "universe": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tickers to include; an empty list means the whole universe.",
                },
                "start": _START,
                "end": _END,
            },
            ["strategy", "universe", "start", "end"],
        ),
    },
    "check_data_quality": {
        "description": "Data-quality and leakage checks for the running analysis.",
        "parameters": _obj({"analysis_id": _ANALYSIS_ID}, ["analysis_id"]),
    },
    "build_evidence_bundle": {
        "description": "Observed context and the committed evidence set of the running analysis.",
        "parameters": _obj({"analysis_id": _ANALYSIS_ID}, ["analysis_id"]),
    },
}


def to_ollama_tools(names: Iterable[str] | None = None) -> list[dict]:
    """Return tool definitions in the shape Ollama's chat API expects.

    ``names`` restricts and orders the list; a name outside the spec raises ``KeyError``,
    so a harness state can never expose a tool that does not exist.
    """
    selected = list(TOOL_SCHEMAS) if names is None else list(names)
    tools = []
    for name in selected:
        if name not in TOOL_SCHEMAS:
            raise KeyError(f"unknown tool: {name}")
        spec = TOOL_SCHEMAS[name]
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec["description"],
                    "parameters": spec["parameters"],
                },
            }
        )
    return tools


_JSON_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
}


def _value_problem(name: str, value: object, spec: dict) -> str | None:
    kind = spec.get("type")
    if kind in _JSON_TYPES and not _JSON_TYPES[kind](value):
        return f"{name} must be of type {kind}"
    if "enum" in spec and value not in spec["enum"]:
        return f"{name} must be one of {spec['enum']}"
    if kind == "array" and "items" in spec:
        for item in value:  # type: ignore[union-attr]
            problem = _value_problem(f"{name} item", item, spec["items"])
            if problem:
                return problem
    return None


def validate_tool_call(name: str, arguments: object) -> str | None:
    """Check a tool call against its schema; return ``None`` or a description of the problem.

    The harness runs this before a tool is executed, so an unknown tool, a missing or
    unexpected argument, a wrong type or a value outside an enum is reported back to
    the model (and counted as an invalid tool call) instead of being silently ignored.
    """
    if name not in TOOL_SCHEMAS:
        return f"unknown tool: {name}"
    if not isinstance(arguments, dict):
        return "arguments must be a JSON object"
    params = TOOL_SCHEMAS[name]["parameters"]
    properties = params["properties"]
    unexpected = sorted(set(arguments) - set(properties))
    if unexpected:
        return f"unexpected argument(s): {', '.join(unexpected)}"
    missing = [key for key in params["required"] if key not in arguments]
    if missing:
        return f"missing argument(s): {', '.join(missing)}"
    for key, value in arguments.items():
        problem = _value_problem(key, value, properties[key])
        if problem:
            return problem
    return None
