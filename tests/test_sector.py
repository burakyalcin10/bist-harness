"""Sector relative strength: median, lag scores, laggards, and no use of later prices."""

import numpy as np
import pandas as pd

from bist_harness.data.peers import PeerGroup, load_peer_groups
from bist_harness.tools.sector import rank_sector_relative_strength

DAYS = 120
INDEX = pd.date_range("2024-01-01", periods=DAYS, freq="B")
AS_OF = str(INDEX[-1].date())


def series(ret_pct: float, horizon: int = 20) -> pd.Series:
    """Flat at 100, then a straight line to 100 * (1 + ret) over the last ``horizon`` days."""
    values = np.full(DAYS, 100.0)
    values[-(horizon + 1) :] = np.linspace(100.0, 100.0 * (1 + ret_pct / 100), horizon + 1)
    return pd.Series(values, index=INDEX)


BANKING = load_peer_groups()["Banking"]
BANK_RETURNS = {"AKBNK": 3, "GARAN": 11, "ISCTR": 12, "YKBNK": 14, "HALKB": 16, "VAKBN": 13}


def _bank_closes() -> dict[str, pd.Series]:
    return {ticker: series(ret) for ticker, ret in BANK_RETURNS.items()}


def _rank(closes=None, group=BANKING, **kwargs):
    kwargs.setdefault("horizon_days", 20)
    kwargs.setdefault("as_of", AS_OF)
    closes = _bank_closes() if closes is None else closes
    return rank_sector_relative_strength(closes, group, **kwargs)


def test_bank_example_median_lag_score_and_laggard():
    out = _rank(benchmark=series(5))
    assert out["sector"] == "Banking" and out["horizon_days"] == 20 and out["as_of"] == AS_OF
    assert out["sector_median_return_pct"] == 12.5
    assert out["benchmark_return_pct"] == 5.0 and out["sector_strong"] is True
    rows = {row["ticker"]: row for row in out["members"]}
    assert rows["AKBNK"] == {
        "ticker": "AKBNK",
        "role": "universe",
        "return_pct": 3.0,
        "lag_score_pct": -9.5,
        "rank": 6,
    }
    assert rows["HALKB"]["rank"] == 1 and rows["HALKB"]["role"] == "reference"
    assert [row["rank"] for row in out["members"]] == [1, 2, 3, 4, 5, 6]
    assert out["laggards"] == ["AKBNK"] and out["leaders"] == []
    assert out["warnings"] == []


def test_sector_strength_is_judged_against_the_benchmark():
    assert _rank(benchmark=series(13))["sector_strong"] is False
    without = _rank()
    assert without["sector_strong"] is None and without["benchmark_return_pct"] is None


def test_reference_stocks_are_never_listed_as_leaders_or_laggards():
    retail = load_peer_groups()["Retail"]
    returns = {"BIMAS": 10, "MGROS": -4, "MAVI": 1, "SOKM": 30, "VAKKO": -20}
    out = _rank({t: series(r) for t, r in returns.items()}, retail)
    assert out["sector_median_return_pct"] == 1.0
    assert out["leaders"] == ["BIMAS"] and out["laggards"] == ["MGROS"]


def test_prices_after_the_analysis_date_do_not_change_the_result():
    as_of = str(INDEX[-11].date())
    closes = _bank_closes()
    base = _rank({t: s.iloc[:-10] for t, s in closes.items()}, as_of=as_of)
    shocked = {t: s.copy() for t, s in closes.items()}
    for s in shocked.values():
        s.iloc[-10:] *= 3
    assert _rank(shocked, as_of=as_of) == base
    assert base["effective_date"] == as_of


def test_as_of_on_a_non_trading_day_uses_the_last_close_before_it():
    saturday = str((INDEX[-1] + pd.Timedelta(days=1)).date())
    out = _rank(as_of=saturday)
    assert out["as_of"] == saturday and out["effective_date"] == AS_OF
    assert out["sector_median_return_pct"] == 12.5


def test_member_without_data_is_left_out_and_named():
    closes = _bank_closes()
    del closes["VAKBN"]
    closes["HALKB"] = closes["HALKB"].iloc[:15]  # shorter than the horizon
    out = _rank(closes)
    assert {row["ticker"] for row in out["members"]} == {"AKBNK", "GARAN", "ISCTR", "YKBNK"}
    assert out["sector_median_return_pct"] == 11.5
    assert any("VAKBN" in w for w in out["warnings"])
    assert any("HALKB" in w for w in out["warnings"])


def test_group_with_too_few_members_warns_and_does_not_judge_strength():
    closes = {t: s for t, s in _bank_closes().items() if t in ("AKBNK", "GARAN")}
    out = _rank(closes, benchmark=series(1))
    assert any(w.startswith("PEER_GROUP_TOO_SMALL") for w in out["warnings"])
    assert out["sector_strong"] is None
    assert len(out["members"]) == 2 and out["sector_median_return_pct"] == 7.0
    assert out["leaders"] == [] and out["laggards"] == []


def test_member_with_a_corporate_action_jump_in_the_window_is_left_out():
    closes = _bank_closes()
    jumped = closes["GARAN"].copy()
    jumped.iloc[-5:] *= 0.1
    closes["GARAN"] = jumped
    out = _rank(closes)
    assert "GARAN" not in {row["ticker"] for row in out["members"]}
    assert any(w.startswith("PRICE_JUMP") and "GARAN" in w for w in out["warnings"])

    early = _bank_closes()
    old_jump = early["GARAN"].copy()
    old_jump.iloc[:50] *= 10  # a jump long before the window does not matter
    early["GARAN"] = old_jump
    assert "GARAN" in {row["ticker"] for row in _rank(early)["members"]}


def test_stale_member_is_left_out():
    closes = _bank_closes()
    closes["ISCTR"] = closes["ISCTR"].iloc[:-30]
    out = _rank(closes)
    assert "ISCTR" not in {row["ticker"] for row in out["members"]}
    assert any(w.startswith("STALE_DATA") and "ISCTR" in w for w in out["warnings"])


def test_no_usable_member_gives_an_empty_ranking():
    out = _rank({}, PeerGroup("Banking", ("AKBNK",), ("GARAN",)))
    assert out["members"] == [] and out["sector_median_return_pct"] is None
    assert out["effective_date"] is None and out["sector_strong"] is None
