"""run_backtest: the MCP tool around the engine and the strategy variants."""

import pandas as pd
import pytest

from bist_harness.backtest import engine, runner, strategies
from bist_harness.data.peers import peer_group_of
from bist_harness.mcp_server import server as srv
from bist_harness.universe import load_universe

from .synth import ohlcv

PERIOD = ("2021-01-01", "2023-12-29")


@pytest.fixture(autouse=True)
def histories(monkeypatch):
    frames: dict[str, pd.DataFrame] = {}

    def load(symbol):
        if symbol not in frames:
            frames[symbol] = ohlcv(1200, seed=sum(map(ord, symbol)))
        return frames[symbol]

    monkeypatch.setattr(srv, "load_history", load)
    return load


def _context(tickers, histories, end=PERIOD[1]):
    members = {m for t in tickers for m in peer_group_of(t).members}
    return strategies.StrategyContext(
        histories={t: histories(t).loc[:end] for t in tickers},
        peer_closes={m: histories(m)["Close"].loc[:end] for m in members},
        benchmark=histories("XU100")["Close"].loc[:end],
    )


def test_runner_trades_only_signals_inside_the_period(histories):
    context = _context(["ASELS", "THYAO"], histories)
    out = runner.run_variant("A_TECHNICAL", context, start=PERIOD[0], end=PERIOD[1])
    signals = strategies.signals("A_TECHNICAL", context)
    expected = 0
    for ticker, signal in signals.items():
        inside = signal & (signal.index >= pd.Timestamp(PERIOD[0]))
        expected += len(engine.run_trades(context.histories[ticker], inside, ticker=ticker).trades)
    assert out["trades"] == expected > 5
    assert out["strategy"] == "A_TECHNICAL" and out["rule"] == strategies.RULES["A_TECHNICAL"]
    assert out["holding_days"] == 10 and out["cost_per_side_pct"] == 0.15
    assert "open of the next trading day" in out["execution"]
    for trade in out["trade_sample"]:
        assert (
            PERIOD[0]
            <= trade["signal_date"]
            < trade["entry_date"]
            < trade["exit_date"]
            <= PERIOD[1]
        )


def test_backtest_tool_reports_performance_benchmarks_and_a_trade_sample():
    out = srv.run_backtest("A_TECHNICAL", ["asels", "THYAO.IS"], *PERIOD)
    assert out["universe"] == ["ASELS", "THYAO"] and (out["start"], out["end"]) == PERIOD
    for key in (
        "signals",
        "trades",
        "win_rate_pct",
        "average_trade_return_pct",
        "cumulative_return_pct",
        "cagr_pct",
        "sharpe",
        "max_drawdown_pct",
        "exposure_pct",
        "benchmark_buy_and_hold_return_pct",
        "excess_vs_buy_and_hold_pct",
        "benchmark_xu100_return_pct",
        "excess_vs_xu100_pct",
        "by_period",
        "by_regime",
        "sample_warning",
        "flags",
        "warnings",
        "snapshot_id",
        "adjustments_id",
    ):
        assert key in out, key
    assert "benchmark_sector_peers_return_pct" not in out
    assert 0 < len(out["trade_sample"]) <= 12
    assert len(out["result_id"]) == 12
    assert out == srv.run_backtest("A_TECHNICAL", ["ASELS", "THYAO"], *PERIOD)


def test_an_empty_universe_means_all_thirty_stocks():
    out = srv.run_backtest("A_TECHNICAL", [], "2022-01-01", "2022-12-30")
    assert out["universe"] == list(load_universe()["ticker"])
    assert out["trades"] > 30


def test_variant_b_has_no_more_signals_than_a_and_adds_the_sector_benchmark():
    a = srv.run_backtest("A_TECHNICAL", ["AKBNK", "THYAO", "BIMAS"], *PERIOD)
    b = srv.run_backtest("B_TECH_SECTOR", ["AKBNK", "THYAO", "BIMAS"], *PERIOD)
    assert 0 < b["signals"] <= a["signals"]
    assert "benchmark_sector_peers_return_pct" in b and "excess_vs_sector_peers_pct" in b


@pytest.mark.parametrize(
    "args,code",
    [
        (("A_TECHNICAL", ["GARAN"], *PERIOD), "UNKNOWN_TICKER"),
        (("A_TECHNICAL", ["ASELS", "XYZ"], *PERIOD), "UNKNOWN_TICKER"),
        (("BEST_STRATEGY", ["ASELS"], *PERIOD), "INVALID_ARGUMENT"),
        (("A_TECHNICAL", "ASELS", *PERIOD), "INVALID_ARGUMENT"),
        (("C_TECH_SECTOR_FUND", ["ASELS"], *PERIOD), "INVALID_DATE_RANGE"),
        (("A_TECHNICAL", ["ASELS"], "2023-12-29", "2021-01-01"), "INVALID_DATE_RANGE"),
        (("A_TECHNICAL", ["ASELS"], "2021-01-01", "2999-01-01"), "FUTURE_DATE"),
        (("A_TECHNICAL", ["ASELS"], "01.01.2021", "2023-12-29"), "INVALID_DATE"),
        (("A_TECHNICAL", ["ASELS"], "2018-01-01", "2019-06-28"), "DATA_UNAVAILABLE"),
    ],
)
def test_backtest_tool_bad_input(args, code):
    out = srv.run_backtest(*args)
    assert set(out) == {"error"} and out["error"]["code"] == code


def test_stock_missing_from_the_snapshot_is_skipped_with_a_warning(histories, monkeypatch):
    from bist_harness.errors import DataUnavailableError

    def load(symbol):
        if symbol == "THYAO":
            raise DataUnavailableError("Snapshot s has no data for THYAO.")
        return histories(symbol)

    monkeypatch.setattr(srv, "load_history", load)
    out = srv.run_backtest("A_TECHNICAL", ["ASELS", "THYAO"], *PERIOD)
    assert out["trades"] > 0 and any("THYAO" in w for w in out["warnings"])


@pytest.mark.parametrize("variant", ["A_TECHNICAL", "B_TECH_SECTOR"])
def test_backtest_does_not_change_when_rows_after_the_end_are_removed(
    variant, histories, monkeypatch
):
    full = srv.run_backtest(variant, ["AKBNK", "THYAO"], *PERIOD)
    monkeypatch.setattr(srv, "load_history", lambda symbol: histories(symbol).loc[: PERIOD[1]])
    cut = srv.run_backtest(variant, ["AKBNK", "THYAO"], *PERIOD)
    assert cut == full


def test_no_number_in_the_output_is_nan(histories):
    import json

    out = srv.run_backtest("B_TECH_SECTOR", ["TCELL", "ASELS"], "2021-01-01", "2021-06-30")
    json.dumps(out, allow_nan=False)


LATE = ("2024-06-01", "2026-06-30")


@pytest.fixture
def layers(monkeypatch):
    """Histories that reach 2026 and the fundamental, macro and news layers."""
    from .test_feature_table import _disclosures
    from .test_fundamentals_tools import _calendar, _statements
    from .test_macro import _series

    frames: dict[str, pd.DataFrame] = {}

    def load(symbol):
        if symbol not in frames:
            frames[symbol] = ohlcv(1750, seed=sum(map(ord, symbol)))
        return frames[symbol]

    macro = _series()
    monkeypatch.setattr(srv, "load_history", load)
    monkeypatch.setattr(srv, "load_statements", lambda: _statements())
    monkeypatch.setattr(srv, "load_disclosure_calendar", lambda: _calendar())
    monkeypatch.setattr(srv, "load_macro", lambda name: macro[name])
    monkeypatch.setattr(srv, "load_disclosures", lambda: _disclosures())
    return load


@pytest.mark.parametrize(
    "variant", ["C_TECH_SECTOR_FUND", "D_FULL_STRUCTURED", "E_FULL_CONTEXTUAL"]
)
def test_variants_with_fundamentals_run_from_2025_on_and_say_so(variant, layers):
    out = srv.run_backtest(variant, ["TUPRS"], *LATE)
    assert "error" not in out
    assert out["effective_start"] == "2025-01-01"
    assert any(w.startswith("NOT_AVAILABLE_BEFORE_2025") for w in out["warnings"])
    assert all(t["signal_date"] >= "2025-01-01" for t in out["trade_sample"])
    assert out["strategy"] == variant and "benchmark_sector_peers_return_pct" in out


def test_each_later_variant_has_no_more_signals(layers):
    counts = [
        srv.run_backtest(v, ["TUPRS"], "2025-01-01", "2026-06-30")["signals"]
        for v in ("B_TECH_SECTOR", "C_TECH_SECTOR_FUND", "D_FULL_STRUCTURED", "E_FULL_CONTEXTUAL")
    ]
    assert counts == sorted(counts, reverse=True) and counts[0] > 0


def test_variants_a_and_b_keep_the_requested_start(layers):
    out = srv.run_backtest("A_TECHNICAL", ["TUPRS"], *LATE)
    assert out["effective_start"] == LATE[0]
    assert not any(w.startswith("NOT_AVAILABLE") for w in out["warnings"])


@pytest.mark.parametrize(
    "variant,hook",
    [
        ("C_TECH_SECTOR_FUND", "load_statements"),
        ("D_FULL_STRUCTURED", "load_macro"),
        ("E_FULL_CONTEXTUAL", "load_disclosures"),
    ],
)
def test_a_variant_whose_layer_was_not_built_is_an_error(variant, hook, layers, monkeypatch):
    from bist_harness.errors import DataUnavailableError

    def missing(*args):
        raise DataUnavailableError(f"{hook}: layer not built. Run the build command first.")

    monkeypatch.setattr(srv, hook, missing)
    out = srv.run_backtest(variant, ["TUPRS"], "2025-01-01", "2026-06-30")
    assert out["error"]["code"] == "DATA_UNAVAILABLE"


def test_variant_c_does_not_change_when_rows_after_the_end_are_removed(layers, monkeypatch):
    full = srv.run_backtest("C_TECH_SECTOR_FUND", ["TUPRS"], "2025-01-01", "2026-03-31")
    monkeypatch.setattr(srv, "load_history", lambda symbol: layers(symbol).loc[:"2026-03-31"])
    assert srv.run_backtest("C_TECH_SECTOR_FUND", ["TUPRS"], "2025-01-01", "2026-03-31") == full
