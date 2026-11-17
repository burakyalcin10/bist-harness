"""Regression tests for the findings of the Sprint 2 code review (2026-11-17)."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.data import snapshot as snap
from bist_harness.data.peers import load_peer_groups
from bist_harness.mcp_server import server as srv
from bist_harness.tools import calendar_patterns as cal
from bist_harness.tools import events as ev
from bist_harness.tools.indicators import add_all_indicators, indicator_state
from bist_harness.tools.sector import rank_sector_relative_strength

from .synth import ohlcv
from .test_calendar_patterns import prices, random_returns, weekday_of_returns
from .test_support_resistance import zigzag


@pytest.fixture
def histories(monkeypatch):
    """Real-looking bars (High != Low, varying volume), a different walk per symbol."""
    frames: dict[str, pd.DataFrame] = {}

    def load(symbol):
        if symbol not in frames:
            frames[symbol] = ohlcv(1200, seed=sum(map(ord, symbol)))
        return frames[symbol]

    monkeypatch.setattr(srv, "load_history", load)
    return load


# --- C1: nearest support and resistance -------------------------------------------------


def _many_levels() -> pd.DataFrame:
    points = [(0, 100), (10, 150), (20, 60), (30, 150), (40, 60), (50, 140), (60, 70), (70, 130)]
    points += [(80, 80), (90, 120), (100, 90), (110, 105), (120, 98), (126, 101)]
    return zigzag(points)


def test_nearest_levels_come_from_all_levels_not_only_from_the_strongest(monkeypatch):
    frame = _many_levels()
    monkeypatch.setattr(srv, "load_history", lambda symbol: frame)
    out = srv.find_support_resistance("ASELS", "2024-01-01", str(frame.index[-1].date()))
    assert out["last_close"] == 101.0
    assert out["levels_found"] == 10 and len(out["levels"]) == 6
    assert out["nearest_support"] == 97.8
    assert out["nearest_resistance"] == 105.2
    listed = {lv["level"] for lv in out["levels"]}
    assert 97.8 not in listed  # the nearest level is a weak one and is still reported


def test_one_strong_move_cannot_outweigh_several_touches():
    from bist_harness.tools.support_resistance import find_support_resistance

    levels = find_support_resistance(_many_levels(), max_levels=None)
    by_level = {lv["level"]: lv for lv in levels}
    assert by_level[150.2]["touches"] == 2 and by_level[140.2]["touches"] == 1
    # the two-touch level moved away by about 30% each time; the term is capped at 3 points
    assert by_level[150.2]["strength"] == 2 * 1.0 + 0 * 1.5 + 3.0


def test_support_resistance_tool_says_when_the_window_is_too_short(histories):
    out = srv.find_support_resistance("ASELS", "2024-03-01", "2024-03-25")
    assert out["levels"] == [] and out["levels_found"] == 0
    assert any(w.startswith("TOO_FEW_BARS") for w in out["warnings"])
    assert srv.find_support_resistance("ASELS", "2021-01-01", "2022-12-30")["warnings"] == []


# --- C2, I1, I2: calendar statistics ------------------------------------------------------


def _garch(days: int, seed: int) -> np.ndarray:
    """Zero-mean returns with volatility clustering and no dependence in the mean."""
    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal(days)
    returns, variance = np.empty(days), 4e-6 / (1 - 0.2 - 0.75)
    for i in range(days):
        returns[i] = np.sqrt(variance) * shocks[i]
        variance = 4e-6 + 0.2 * returns[i] ** 2 + 0.75 * variance
    return returns


def test_large_drop_test_keeps_its_size_under_volatility_clustering():
    """No effect in the mean: about 5% of series may pass at the 5% level, not 15%."""
    passed = 0
    for seed in range(60):
        out = cal.evaluate_pattern(prices(_garch(1000, seed)), "POST_LARGE_DOWN_REVERSION")
        passed += out["p_value"] is not None and out["p_value"] < 0.05
    assert passed <= 6


def test_two_sided_p_value_is_centred_on_the_permutation_mean():
    simulated = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    # distance from the centre 3: the values 1 and 5 are at least as far as the observed 5
    assert cal.two_sided_p_value(5.0, simulated) == round((1 + 2) / (5 + 1), 4)
    assert cal.two_sided_p_value(3.0, simulated) == 1.0
    assert cal.two_sided_p_value(9.0, simulated) == round(1 / 6, 4)


@pytest.mark.parametrize(
    "train,test,signed,expected",
    [
        # direction pattern: the edge is the signed mean itself
        ((0.20, 0.30), (0.20, -0.30), True, False),
        ((0.20, 0.30), (-0.20, 0.30), True, True),
        # condition pattern: the edge is the excess over the unconditional mean
        ((0.50, 0.10), (0.40, 0.20), False, False),
        ((0.50, 0.10), (0.10, 0.20), False, True),
        ((0.50, 0.10), (None, 0.20), False, True),
    ],
)
def test_unstable_flag_compares_the_right_edge(train, test, signed, expected):
    def part(pair):
        return {"conditional_mean_return_pct": pair[0], "unconditional_mean_return_pct": pair[1]}

    assert cal.is_unstable(part(train), part(test), signed=signed) is expected


def test_an_effect_that_reverses_in_the_second_part_is_flagged_unstable():
    days = 1500
    returns = random_returns(days, seed=4)
    weekday = weekday_of_returns(days)
    for i in np.flatnonzero(weekday == 0):
        if i + 4 < days and returns[i] < 0:
            returns[i + 4] += 0.015 if i < 0.7 * days else -0.015
    out = cal.evaluate_pattern(prices(returns), "MON_WEAK_FRI_STRONG")
    assert "UNSTABLE_OUT_OF_SAMPLE" in out["interpretation_flags"]
    stable = returns.copy()
    for i in np.flatnonzero(weekday == 0):
        if i + 4 < days and returns[i] < 0 and i >= 0.7 * days:
            stable[i + 4] += 0.03
    out = cal.evaluate_pattern(prices(stable), "MON_WEAK_FRI_STRONG")
    assert "UNSTABLE_OUT_OF_SAMPLE" not in out["interpretation_flags"]


@pytest.mark.parametrize("pattern", cal.PATTERNS)
def test_a_period_without_any_return_reports_nothing_instead_of_raising(pattern, histories):
    empty = cal.evaluate_pattern(prices(random_returns(days=50)).iloc[:1], pattern)
    assert empty["occurrences"] == 0 and empty["p_value"] is None
    out = srv.test_weekday_pattern("ASELS", pattern, "2019-12-01", "2020-01-02")
    assert out["occurrences"] == 0 and "error" not in out


def test_since_does_not_restart_the_volatility_warm_up():
    df = prices(random_returns(days=900, seed=6))
    since = df.index[400]
    full = cal._day_units(cal.prepare(df))
    expected = int((full.loc[full.index >= since, "weight"] == 1).sum())
    out = cal.evaluate_pattern(df, "POST_LARGE_DOWN_REVERSION", since=str(since.date()))
    assert out["occurrences"] == expected > 0


# --- I4, I5: sector ---------------------------------------------------------------------


def _closes(returns: dict[str, float], days: int = 120) -> dict[str, pd.Series]:
    index = pd.date_range("2024-01-01", periods=days, freq="B")
    out = {}
    for ticker, ret in returns.items():
        values = np.full(days, 100.0)
        values[-21:] = np.linspace(100.0, 100.0 * (1 + ret / 100), 21)
        out[ticker] = pd.Series(values, index=index)
    return out


def test_sector_ranking_warns_when_the_data_ends_before_the_analysis_date():
    banking = load_peer_groups()["Banking"]
    closes = _closes({"AKBNK": 3, "GARAN": 11, "ISCTR": 12, "YKBNK": 14})
    last = str(next(iter(closes.values())).index[-1].date())
    fresh = rank_sector_relative_strength(closes, banking, horizon_days=20, as_of=last)
    assert not any(w.startswith("DATA_ENDS_BEFORE_AS_OF") for w in fresh["warnings"])
    late = rank_sector_relative_strength(closes, banking, horizon_days=20, as_of="2026-11-13")
    assert late["effective_date"] == last
    assert any(w.startswith("DATA_ENDS_BEFORE_AS_OF") for w in late["warnings"])


def test_an_undersized_group_names_no_leader_or_laggard():
    telecom = load_peer_groups()["Telecom"]
    closes = _closes({"TCELL": 12, "TTKOM": 2})
    out = rank_sector_relative_strength(
        closes, telecom, horizon_days=20, as_of="2024-06-14", benchmark=closes["TCELL"]
    )
    assert any(w.startswith("PEER_GROUP_TOO_SMALL") for w in out["warnings"])
    assert out["leaders"] == [] and out["laggards"] == [] and out["sector_strong"] is None
    assert [row["lag_score_pct"] for row in out["members"]] == [None, None]
    assert [row["return_pct"] for row in out["members"]] == [12.0, 2.0]


# --- I6: price adjustments ----------------------------------------------------------------


def _adjustments(tmp_path, rows: str):
    path = tmp_path / "adjustments.csv"
    path.write_text("ticker,effective_date,factor,reason\n" + rows, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "rows,problem",
    [
        ("CCOLA,2024-08-01,11,a\nCCOLA,2024-08-01,11,b\n", "duplicate"),
        ("ccola,2024-08-01,11,a\n", "ticker"),
        ("CCOLA,01.08.2024,11,a\n", "date"),
        ("CCOLA,,11,a\n", "date"),
        ("CCOLA,2024-08-01,0,a\n", "factor"),
        ("CCOLA,2024-08-01,-2,a\n", "factor"),
        ("CCOLA,2024-08-01,eleven,a\n", "factor"),
    ],
)
def test_a_broken_adjustments_file_is_refused(tmp_path, rows, problem):
    with pytest.raises(ValueError, match=problem):
        snap.load_adjustments(_adjustments(tmp_path, rows))


def test_adjustments_id_changes_with_the_file_content(tmp_path):
    one = snap.adjustments_id(_adjustments(tmp_path, "CCOLA,2024-08-01,11,a\n"))
    other = snap.adjustments_id(_adjustments(tmp_path, "CCOLA,2024-08-01,12,a\n"))
    assert len(one) == 8 and one != other
    assert snap.adjustments_id() == snap.adjustments_id()


def test_every_tool_output_names_the_adjustments_and_the_result_id_depends_on_them(
    histories, monkeypatch
):
    first = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    assert first["adjustments_id"] == snap.adjustments_id()
    sector = srv.rank_sector_relative_strength("Banking", 20, "2022-06-30")
    assert sector["adjustments_id"] == first["adjustments_id"]
    monkeypatch.setattr(srv, "current_adjustments_id", lambda: "deadbeef")
    second = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    assert second["adjustments_id"] == "deadbeef" and second["result_id"] != first["result_id"]


def test_a_broken_adjustments_file_becomes_an_error_object(monkeypatch):
    def broken(symbol):
        raise ValueError("price_adjustments.csv: factor must be a positive number")

    monkeypatch.setattr(srv, "load_history", broken)
    out = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    assert out["error"]["code"] == "DATA_UNAVAILABLE" and "factor" in out["error"]["message"]


def test_snapshot_verification_detects_a_changed_file(tmp_path):
    frames = {"ASELS.IS": ohlcv(50, 1), "THYAO.IS": ohlcv(50, 2)}
    snap.build_snapshot(
        ["ASELS", "THYAO"], snapshot_id="s1", root=tmp_path, downloader=lambda s, a, b: frames[s]
    )
    assert snap.verify_snapshot(root=tmp_path) == []
    changed = pd.read_parquet(tmp_path / "s1" / "THYAO.parquet")
    changed.iloc[3, 3] += 0.01
    changed.to_parquet(tmp_path / "s1" / "THYAO.parquet")
    (tmp_path / "s1" / "ASELS.parquet").unlink()
    assert snap.verify_snapshot(root=tmp_path) == ["ASELS: file missing", "THYAO: content changed"]


# --- I7: indicator warm-up ----------------------------------------------------------------


def test_indicators_report_nothing_before_their_warm_up_is_complete():
    bars = ohlcv(200, 3)

    def state(rows):
        return indicator_state(add_all_indicators(bars.iloc[:rows]), [])

    two, eight, fourteen, fifteen = state(2), state(8), state(14), state(15)
    assert two["rsi"] is None and two["rsi_state"] is None
    assert two["macd"] is None and two["macd_state"] is None and two["ema_20"] is None
    assert eight["rsi"] is None and fourteen["rsi"] is None and fifteen["rsi"] is not None
    assert state(19)["ema_20"] is None and state(20)["ema_20"] is not None
    assert state(34)["macd"] is None and state(35)["macd_state"] is not None
    sixty = state(60)
    assert sixty["ichimoku_state"] is None and sixty["cloud_top"] is None
    assert state(78)["ichimoku_state"] is not None


def test_market_state_follows_the_same_warm_up():
    frame = add_all_indicators(ohlcv(200, 3))
    early = ev.market_state(frame, frame.index[8])
    assert early["rsi_state"] is None and early["ichimoku_state"] is None
    assert ev.market_state(frame, frame.index[60])["ichimoku_state"] is None
    assert ev.market_state(frame, frame.index[100])["ichimoku_state"] is not None


def test_events_inside_the_warm_up_of_their_indicator_are_not_counted():
    bars = ohlcv(600, 2)
    frame = add_all_indicators(bars)
    for event_type, direction, minimum in [
        ("ICHIMOKU_BREAKOUT", "BULLISH", 78),
        ("ICHIMOKU_BREAKOUT", "BEARISH", 78),
        ("RSI_LOCAL_TROUGH", "BULLISH", 16),
        ("RSI_LOCAL_PEAK", "BEARISH", 16),
    ]:
        mask = ev.event_mask(frame, event_type, direction)
        evaluated = mask & (bars["Close"].shift(-5) / bars["Close"] - 1).notna()
        out = ev.detect_events(bars, event_type, direction)
        assert out["event_count"] == int(evaluated.iloc[minimum:].sum())


# --- I9: server-level look-ahead and input checks -----------------------------------------

PERIOD = ("2021-01-01", "2022-06-30")
CALLS = [
    ("get_stock_history", ("ASELS", *PERIOD)),
    ("get_index_history", ("XU100", *PERIOD)),
    ("calculate_indicators", ("ASELS", *PERIOD, [])),
    ("find_support_resistance", ("ASELS", *PERIOD)),
    ("detect_reversal_events", ("ASELS", *PERIOD, "SUPPORT_RESISTANCE_TOUCH", 5, "BEARISH")),
    ("detect_reversal_events", ("ASELS", *PERIOD, "ICHIMOKU_BREAKOUT", 10, "BULLISH")),
    ("detect_reversal_events", ("ASELS", *PERIOD, "SUPERTREND_FLIP", 5, "BULLISH")),
    ("rank_sector_relative_strength", ("Banking", 20, PERIOD[1])),
    ("test_weekday_pattern", ("ASELS", "POST_LARGE_DOWN_REVERSION", *PERIOD)),
    ("test_weekday_pattern", ("ASELS", "THREE_DOWN_TWO_UP", *PERIOD)),
]


@pytest.mark.parametrize("tool,args", CALLS)
def test_no_tool_output_changes_when_rows_after_the_requested_end_are_removed(
    tool, args, histories, monkeypatch
):
    def analysis(output):
        skip = {"data_last_date", "coverage_warning", "result_id"}
        return {k: v for k, v in output.items() if k not in skip}

    full = getattr(srv, tool)(*args)
    assert "error" not in full
    monkeypatch.setattr(srv, "load_history", lambda symbol: histories(symbol).loc[: PERIOD[1]])
    assert analysis(getattr(srv, tool)(*args)) == analysis(full)


@pytest.mark.parametrize("bad", ["20210101", "2021-W01-1", "2021-1-1", "01.01.2021", ""])
def test_dates_must_be_written_exactly_as_yyyy_mm_dd(bad, histories):
    out = srv.get_stock_history("ASELS", bad, "2021-12-31")
    assert out["error"]["code"] == "INVALID_DATE"
    out = srv.rank_sector_relative_strength("Banking", 20, bad)
    assert out["error"]["code"] == "INVALID_DATE"
