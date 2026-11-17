"""Strategy variants A to E (project brief, section 29): entry rules only.

A variant turns the data known at the close of each day into a yes/no entry signal per
stock. Execution, holding period and costs belong to the engine. The rules are fixed in
``docs/preregistration.md``; each later variant adds one condition to the one before, so
its signals are a subset.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from bist_harness.data.peers import peer_group_of
from bist_harness.tools.events import counted_mask
from bist_harness.tools.indicators import add_all_indicators
from bist_harness.tools.schemas import STRATEGY_VARIANTS
from bist_harness.tools.sector import lag_score_series

VARIANTS: tuple[str, ...] = tuple(STRATEGY_VARIANTS)
ENTRY_EVENTS = ("RSI_LOCAL_TROUGH", "BOLLINGER_LOWER_TOUCH")
LAG_HORIZON_DAYS = 20

RULES = {
    "A_TECHNICAL": (
        "Enter after a bullish reversal event: an RSI local trough or a lower-Bollinger "
        "reversal at the close of day t."
    ),
    "B_TECH_SECTOR": (
        "Rule A, and on day t the stock's 20-day return is below its peer-group median "
        "while that median is above the XU100 20-day return."
    ),
    "C_TECH_SECTOR_FUND": (
        "Rule B, and the latest quarter public on day t shows an improving fundamental trend."
    ),
    "D_FULL_STRUCTURED": (
        "Rule C, and the TCMB policy rate was not raised in the 60 calendar days before day t."
    ),
    "E_FULL_CONTEXTUAL": (
        "Rule D, and no KAP disclosure tagged regulation or legal in the 5 calendar days "
        "before day t."
    ),
}


@dataclass(frozen=True)
class StrategyContext:
    """Everything a variant may read. Every series is already cut at the end date."""

    histories: dict[str, pd.DataFrame]  # stocks to trade: daily OHLCV
    peer_closes: dict[str, pd.Series]  # closes of every peer-group member
    benchmark: pd.Series  # XU100 close
    features: pd.DataFrame | None = None  # point-in-time feature table (variants C to E)


def technical_signal(df: pd.DataFrame) -> pd.Series:
    """Rule A: any of the entry events on that day."""
    frame = add_all_indicators(df)
    signal = pd.Series(False, index=frame.index)
    for event_type in ENTRY_EVENTS:
        signal |= counted_mask(frame, event_type, "BULLISH")
    return signal


def sector_condition(ticker: str, context: StrategyContext) -> pd.Series:
    """Rule B's addition: a lagging stock in a sector that beats the index."""
    lag = lag_score_series(
        context.peer_closes,
        peer_group_of(ticker),
        ticker,
        horizon_days=LAG_HORIZON_DAYS,
        benchmark=context.benchmark,
    )
    index = context.histories[ticker].index
    lagging = (lag["lag_score"] < 0).reindex(index, fill_value=False)
    strong = lag["sector_strong"].reindex(index, fill_value=False).astype(bool)
    return lagging & strong


def signals(variant: str, context: StrategyContext) -> dict[str, pd.Series]:
    """Entry signal per stock for one variant."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown strategy variant: {variant}")
    if variant not in ("A_TECHNICAL", "B_TECH_SECTOR"):
        raise NotImplementedError(f"{variant} needs the fundamental, macro and news layers")
    result: dict[str, pd.Series] = {}
    for ticker, history in context.histories.items():
        signal = technical_signal(history)
        if variant == "B_TECH_SECTOR":
            signal &= sector_condition(ticker, context)
        result[ticker] = signal
    return result
