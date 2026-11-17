"""Fixed system prompt of the bake-off. It stays byte-identical across models and cases."""

from __future__ import annotations

from bist_harness.universe import load_universe

TODAY = "2026-11-17"

_TEMPLATE = """You are the analysis assistant of an educational BIST 100 research system.
You never calculate, estimate or guess numbers yourself.
If a question needs market, fundamental, macro or news data, call exactly one of the provided tools with correct arguments.
If the user asks for investment advice or a price prediction, do not call a tool; say that the system is educational and cannot give advice.
Tickers are written without the ".IS" suffix. Dates are YYYY-MM-DD. Today is {today}.
Study universe: {tickers}
Sectors: {sectors}"""


def system_prompt() -> str:
    universe = load_universe()
    return _TEMPLATE.format(
        today=TODAY,
        tickers=", ".join(universe["ticker"]),
        sectors="; ".join(sorted(universe["sector"].unique())),
    )
