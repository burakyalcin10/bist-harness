"""Pre-registered Scenario 1-3 studies (docs/preregistration.md, section 3)."""

import numpy as np
import pandas as pd

from bist_harness.backtest import scenarios as sc


def _closes(values, start="2024-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_laggard_episodes_and_catch_up_outcome():
    flat = [100.0] * 60
    stock = _closes(flat)
    lag = pd.DataFrame({"lag_score": 0.0, "sector_strong": True}, index=stock.index)
    lag.iloc[[25, 26, 45], lag.columns.get_loc("lag_score")] = [-0.08, -0.06, -0.07]
    lag.iloc[[30], lag.columns.get_loc("lag_score")] = -0.02  # secondary definition only
    rising = stock.copy()
    rising.iloc[26:] = 110.0  # the stock catches up after day 25
    peers = {"P1": _closes(flat), "P2": _closes(flat)}
    out = sc.laggard_study(
        {"AAA": rising}, {"AAA": peers}, {"AAA": lag}, start="2024-01-01", end="2024-03-22"
    )
    primary = out["primary"]
    assert primary["laggard_days"] == 3
    assert primary["episodes"] == 2  # day 45 is more than 10 days after day 26
    assert primary["hit_rate_pct"] == round(100 / 3, 2)  # only day 25 is followed by a gain
    assert out["secondary"]["laggard_days"] == 4
    assert out["definition"]["outcome_days"] == 10


def test_laggard_outcomes_must_end_inside_the_period():
    stock = _closes([100.0] * 30)
    lag = pd.DataFrame({"lag_score": -0.1, "sector_strong": True}, index=stock.index)
    out = sc.laggard_study(
        {"AAA": stock},
        {"AAA": {"P1": stock, "P2": stock}},
        {"AAA": lag},
        start="2024-01-01",
        end=str(stock.index[-1].date()),
    )
    assert out["primary"]["laggard_days"] == 30 - 10


def test_a_pattern_is_supported_only_if_significant_and_its_sign_holds():
    significant = {"p_value": 0.001, "p_value_bonferroni": 0.005, "edge_pct": 0.4}
    weak = {"p_value": 0.2, "p_value_bonferroni": 1.0, "edge_pct": 0.4}
    assert sc.pattern_supported(significant, {"edge_pct": 0.1}) is True
    assert sc.pattern_supported(significant, {"edge_pct": -0.1}) is False
    assert sc.pattern_supported(significant, {"edge_pct": None}) is False
    assert sc.pattern_supported(weak, {"edge_pct": 0.1}) is False


def test_pattern_counts_are_compared_with_chance():
    rows = [
        {
            "ticker": f"S{i}",
            "pattern": "P",
            "discovery": {"p_value": p, "p_value_bonferroni": min(1, p * 5)},
        }
        for i, p in enumerate([0.001, 0.03, 0.5, 0.9])
    ]
    summary = sc.pattern_counts(rows, stocks=4)
    assert summary["P"]["significant_before_correction"] == 2
    assert summary["P"]["significant_after_correction"] == 1
    assert summary["P"]["expected_by_chance_before"] == 0.2
    assert summary["P"]["expected_by_chance_after"] == 0.04


def _stub_study(monkeypatch, tmp_path, calls):
    from bist_harness.backtest import study

    monkeypatch.setattr(study, "backtests", lambda s, e: {"A": {"trades": 0}})
    monkeypatch.setattr(study, "reactions", lambda s, e: {"summary": {}, "events": []})
    monkeypatch.setattr(study, "scenario_1", lambda s, e: {"primary": {}, "secondary": {}})
    monkeypatch.setattr(
        study, "scenario_2", lambda with_test: calls.append(with_test) or {"counts": {}}
    )
    monkeypatch.setattr(study, "scenario_3", lambda s, e: {})
    monkeypatch.chdir(tmp_path)
    return study


def test_the_test_run_holds_every_preregistered_question(monkeypatch, tmp_path):
    import json

    calls = []
    study = _stub_study(monkeypatch, tmp_path, calls)
    assert study.main(["test"]) == 0
    saved = json.loads(next((tmp_path / "runs").glob("study-test-*.json")).read_text("utf-8"))
    assert {"backtests", "reactions", "scenario_1", "scenario_2", "scenario_3"} <= set(saved)
    assert calls == [True]


def test_a_discovery_run_never_computes_the_test_half_of_scenario_2(monkeypatch, tmp_path):
    calls = []
    study = _stub_study(monkeypatch, tmp_path, calls)
    assert study.main(["discovery"]) == 0
    assert calls == [False]


def test_event_family_summary_with_regimes():
    records = pd.DataFrame(
        {
            "ticker": ["A", "A", "B", "B"],
            "event": ["RSI_LOCAL_TROUGH"] * 4,
            "direction": ["BULLISH"] * 4,
            "date": ["2024-01-02", "2024-02-01", "2024-03-01", "2024-04-01"],
            "forward_1d_return_pct": [1.0, -1.0, 2.0, np.nan],
            "forward_3d_return_pct": [1.0, -1.0, 2.0, np.nan],
            "forward_5d_return_pct": [2.0, -1.0, 3.0, np.nan],
            "forward_10d_return_pct": [2.0, -1.0, 3.0, np.nan],
            "reversal_strength_pct": [1.0, 2.0, 3.0, 4.0],
        }
    )
    above = {"2024-01-02": True, "2024-02-01": False, "2024-03-01": True, "2024-04-01": True}
    out = sc.summarize_family(records, regime=above)
    assert out["events"] == 4 and out["evaluated_5d"] == 3
    assert out["bounce_rate_5d_pct"] == round(200 / 3, 2)
    assert out["mean_5d_return_pct"] == round(4 / 3, 2)
    assert out["by_regime"]["XU100_ABOVE_200D"]["events"] == 3
    assert out["by_regime"]["XU100_BELOW_200D"]["bounce_rate_5d_pct"] == 0.0
    assert out["sample_warning"] == "Very small sample size"
