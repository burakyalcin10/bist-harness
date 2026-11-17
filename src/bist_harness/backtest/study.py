"""Run the pre-registered studies of one research period and save the raw results.

    uv run python -m bist_harness.backtest.study test
    uv run python -m bist_harness.backtest.study discovery

Runs strategy variants A to E on the whole universe, the Scenario 1 to 3 studies
(``backtest/scenarios.py``) and, for the test period, the Scenario 4 reaction study and
the test half of Scenario 2. The rules are those of ``docs/preregistration.md``; this
module only calls the tools and writes what they return to ``runs/``. The test period
is meant to be run once.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from bist_harness.backtest import scenarios
from bist_harness.backtest.periods import PERIODS
from bist_harness.data import fundamentals, macro, peers, snapshot
from bist_harness.errors import DataUnavailableError
from bist_harness.mcp_server import server
from bist_harness.tools.disclosure import reaction_study
from bist_harness.tools.schemas import STRATEGY_VARIANTS
from bist_harness.tools.sector import lag_score_series
from bist_harness.universe import load_universe

SUMMARY_KEYS = (
    "signals",
    "trades",
    "win_rate_pct",
    "average_trade_return_pct",
    "median_trade_return_pct",
    "cumulative_return_pct",
    "cagr_pct",
    "sharpe",
    "max_drawdown_pct",
    "exposure_pct",
    "benchmark_buy_and_hold_return_pct",
    "benchmark_xu100_return_pct",
    "benchmark_sector_peers_return_pct",
    "excess_vs_buy_and_hold_pct",
    "by_regime",
    "sample_warning",
    "flags",
    "warnings",
    "result_id",
)


def backtests(start: str, end: str) -> dict[str, dict]:
    """Every strategy variant on the whole universe."""
    return {variant: server.run_backtest(variant, [], start, end) for variant in STRATEGY_VARIANTS}


def reactions(start: str, end: str) -> dict:
    """Scenario 4: reaction to every report that became usable in the period."""
    tickers = list(load_universe()["ticker"])
    closes = {}
    for ticker in tickers:
        try:
            closes[ticker] = snapshot.load_history(ticker)["Close"]
        except DataUnavailableError:
            continue
    peer_closes: dict[str, dict[str, pd.Series]] = {}
    for ticker in closes:
        group = peers.peer_group_of(ticker)
        peer_closes[ticker] = {}
        for member in group.members:
            if member == ticker:
                continue
            try:
                peer_closes[ticker][member] = snapshot.load_history(member)["Close"]
            except DataUnavailableError:
                continue
    try:
        cpi = macro.cpi_index(macro.load_macro("cpi"))
    except DataUnavailableError:
        cpi = None
    study = reaction_study(
        fundamentals.load_statements(),
        fundamentals.load_disclosure_calendar(),
        closes=closes,
        benchmark=snapshot.load_history("XU100")["Close"],
        peer_closes=peer_closes,
        cpi=cpi,
        start=start,
        end=end,
    )
    return {"summary": study["summary"], "events": study["events"].to_dict("records")}


def _universe_histories() -> dict[str, pd.DataFrame]:
    histories = {}
    for ticker in load_universe()["ticker"]:
        try:
            histories[ticker] = snapshot.load_history(ticker)
        except DataUnavailableError:
            continue
    return histories


def scenario_1(start: str, end: str) -> dict:
    """Scenario 1: laggards of strong sectors and their catch-up."""
    benchmark = snapshot.load_history("XU100")["Close"]
    closes, peer_closes, lags = {}, {}, {}
    cache: dict[str, pd.Series] = {}

    def close_of(symbol: str) -> pd.Series | None:
        if symbol not in cache:
            try:
                cache[symbol] = snapshot.load_history(symbol)["Close"]
            except DataUnavailableError:
                return None
        return cache[symbol]

    for ticker in load_universe()["ticker"]:
        group = peers.peer_group_of(ticker)
        members = {m: s for m in group.members if (s := close_of(m)) is not None}
        if ticker not in members:
            continue
        closes[ticker] = members[ticker]
        peer_closes[ticker] = {m: s for m, s in members.items() if m != ticker}
        lags[ticker] = lag_score_series(
            members, group, ticker, horizon_days=20, benchmark=benchmark
        )
    return scenarios.laggard_study(closes, peer_closes, lags, start=start, end=end)


def scenario_2(with_test: bool) -> dict:
    """Scenario 2: calendar patterns; the test half only in the one test run."""
    return scenarios.calendar_study(
        _universe_histories(),
        discovery=PERIODS["discovery"],
        test=PERIODS["test"] if with_test else None,
    )


def scenario_3(start: str, end: str) -> dict:
    """Scenario 3: what followed each technical reversal event family."""
    benchmark = snapshot.load_history("XU100")["Close"]
    return scenarios.event_study(_universe_histories(), benchmark, start=start, end=end)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] not in (["test"], ["discovery"]):
        print("usage: python -m bist_harness.backtest.study test | discovery")
        return 2
    name = args[0]
    start, end = PERIODS[name]
    result: dict = {"period": name, "start": start, "end": end, "backtests": backtests(start, end)}
    if name == "test":
        result["reactions"] = reactions(start, end)
    result["scenario_1"] = scenario_1(start, end)
    result["scenario_2"] = scenario_2(name == "test")
    result["scenario_3"] = scenario_3(start, end)
    runs = Path("runs")
    runs.mkdir(exist_ok=True)
    path = runs / f"study-{name}-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    for variant, output in result["backtests"].items():
        shown = output.get("error") or {k: output.get(k) for k in SUMMARY_KEYS if k in output}
        print(variant, json.dumps(shown, ensure_ascii=False))
    if "reactions" in result:
        print("REACTIONS", json.dumps(result["reactions"]["summary"], ensure_ascii=False))
    for key in ("primary", "secondary"):
        print("SCENARIO1", key, json.dumps(result["scenario_1"].get(key), ensure_ascii=False))
    print("SCENARIO2", json.dumps(result["scenario_2"].get("counts"), ensure_ascii=False))
    if "supported" in result["scenario_2"]:
        print("SCENARIO2 supported", json.dumps(result["scenario_2"]["supported"]))
    print("SCENARIO3 families", len(result["scenario_3"]))
    print("saved", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
