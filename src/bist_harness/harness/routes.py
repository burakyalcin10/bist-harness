"""The 17 harness states, their allowed tools and the route each scenario takes."""

from __future__ import annotations

# Design spec section 6, in order.
STATES: tuple[str, ...] = (
    "START",
    "SELECT_UNIVERSE",
    "LOAD_MARKET_DATA",
    "CHECK_DATA_QUALITY",
    "CALCULATE_TECHNICALS",
    "RUN_SECTOR_RELATIVE_ANALYSIS",
    "RUN_PATTERN_AND_REVERSAL_ANALYSIS",
    "LOAD_FUNDAMENTALS",
    "LOAD_MACRO_CONTEXT",
    "LOAD_NEWS_AND_SPEECH_CONTEXT",
    "BUILD_EVIDENCE",
    "PREVIEW_STRATEGIES",
    "RUN_BACKTEST",
    "RISK_GATE",
    "GENERATE_EXPLANATION",
    "HUMAN_REVIEW",
    "LOG_AND_CLOSE",
)

ALLOWED_TOOLS: dict[str, tuple[str, ...]] = {
    "START": (),
    "SELECT_UNIVERSE": (),
    "LOAD_MARKET_DATA": ("get_stock_history", "get_index_history"),
    "CHECK_DATA_QUALITY": ("check_data_quality",),
    "CALCULATE_TECHNICALS": ("calculate_indicators", "find_support_resistance"),
    "RUN_SECTOR_RELATIVE_ANALYSIS": ("rank_sector_relative_strength",),
    "RUN_PATTERN_AND_REVERSAL_ANALYSIS": ("detect_reversal_events", "test_weekday_pattern"),
    "LOAD_FUNDAMENTALS": ("get_fundamental_metrics", "calculate_fundamental_change"),
    "LOAD_MACRO_CONTEXT": ("get_macro_context",),
    "LOAD_NEWS_AND_SPEECH_CONTEXT": ("get_news_events", "get_speech_features"),
    "BUILD_EVIDENCE": ("build_evidence_bundle",),
    "PREVIEW_STRATEGIES": (),
    "RUN_BACKTEST": ("run_backtest",),
    "RISK_GATE": ("check_data_quality",),
    "GENERATE_EXPLANATION": (),
    "HUMAN_REVIEW": (),
    "LOG_AND_CLOSE": (),
}

MANDATORY = ("CHECK_DATA_QUALITY", "RISK_GATE", "LOG_AND_CLOSE")

# Scenarios that can end in a *_CANDIDATE label: PREVIEW_STRATEGIES and RUN_BACKTEST are
# never skipped for them.
CANDIDATE_SCENARIOS = (
    "SECTOR_LAGGARD",
    "CALENDAR_PATTERN",
    "TECHNICAL_REVERSAL",
    "FUNDAMENTAL_REACTION",
    "BACKTEST",
)
# Guarded early exits: no analysis starts, so only START and LOG_AND_CLOSE run.
GUARDED_ROUTE = ("START", "LOG_AND_CLOSE")

_HEAD = ("START", "SELECT_UNIVERSE", "LOAD_MARKET_DATA", "CHECK_DATA_QUALITY")
_CANDIDATE_TAIL = (
    "BUILD_EVIDENCE",
    "PREVIEW_STRATEGIES",
    "RUN_BACKTEST",
    "RISK_GATE",
    "GENERATE_EXPLANATION",
    "HUMAN_REVIEW",
    "LOG_AND_CLOSE",
)
_CONTEXT_TAIL = (
    "BUILD_EVIDENCE",
    "RISK_GATE",
    "GENERATE_EXPLANATION",
    "HUMAN_REVIEW",
    "LOG_AND_CLOSE",
)


def _route(*middle: str, tail: tuple[str, ...]) -> tuple[str, ...]:
    return (*_HEAD, *middle, *tail)


ROUTES: dict[str, tuple[str, ...]] = {
    "SECTOR_LAGGARD": _route(
        "CALCULATE_TECHNICALS", "RUN_SECTOR_RELATIVE_ANALYSIS", tail=_CANDIDATE_TAIL
    ),
    "CALENDAR_PATTERN": _route("RUN_PATTERN_AND_REVERSAL_ANALYSIS", tail=_CANDIDATE_TAIL),
    "TECHNICAL_REVERSAL": _route(
        "CALCULATE_TECHNICALS", "RUN_PATTERN_AND_REVERSAL_ANALYSIS", tail=_CANDIDATE_TAIL
    ),
    "FUNDAMENTAL_REACTION": _route(
        "CALCULATE_TECHNICALS", "LOAD_FUNDAMENTALS", tail=_CANDIDATE_TAIL
    ),
    "BACKTEST": _route(
        "CALCULATE_TECHNICALS", "RUN_PATTERN_AND_REVERSAL_ANALYSIS", tail=_CANDIDATE_TAIL
    ),
    "PRICE_SUMMARY": _route("CALCULATE_TECHNICALS", tail=_CONTEXT_TAIL),
    "MACRO_CONTEXT": _route("LOAD_MACRO_CONTEXT", tail=_CONTEXT_TAIL),
    "NEWS_CONTEXT": _route("LOAD_NEWS_AND_SPEECH_CONTEXT", tail=_CONTEXT_TAIL),
    "ADVICE_REQUEST": GUARDED_ROUTE,
    "PREDICTION_REQUEST": GUARDED_ROUTE,
    "OUT_OF_SCOPE": GUARDED_ROUTE,
}
