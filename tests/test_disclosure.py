"""Price reaction after a disclosure: returns and abnormal returns against hand calculations."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.tools import disclosure as dc

INDEX = pd.date_range("2025-01-01", periods=40, freq="B")


def _series(changes: dict[int, float], start: float = 100.0) -> pd.Series:
    """Flat series with the given values from the given positions on."""
    values = np.full(len(INDEX), start)
    for position, level in sorted(changes.items()):
        values[position:] = level
    return pd.Series(values, index=INDEX)


STOCK = _series({10: 102.0, 11: 104.0, 15: 110.0, 30: 121.0})
XU100 = _series({11: 202.0, 15: 204.0, 30: 210.0}, start=200.0)
PEERS = {
    "P1": _series({11: 51.0, 15: 52.0, 30: 55.0}, start=50.0),  # +2%, +4%, +10%
    "P2": _series({11: 53.0, 15: 54.0, 30: 56.0}, start=50.0),  # +6%, +8%, +12%
}
EVENT = INDEX[10]


def _one(**kwargs):
    kwargs.setdefault("benchmark", XU100)
    kwargs.setdefault("peers", PEERS)
    return dc.post_disclosure_returns(STOCK, [EVENT], **kwargs).iloc[0]


def test_return_runs_from_the_close_before_the_event_day():
    row = _one()
    assert row["event_day"] == str(EVENT.date())
    assert row["base_day"] == str(INDEX[9].date())
    # base 100; one day after the event day 104; five days after 110; twenty days after 121
    assert (row["return_1d_pct"], row["return_5d_pct"], row["return_20d_pct"]) == (4.0, 10.0, 21.0)


def test_abnormal_return_subtracts_the_index_and_the_peer_average():
    row = _one()
    # XU100: 200 -> 202, 204, 210: +1%, +2%, +5%
    assert row["abnormal_vs_index_1d_pct"] == 3.0
    assert row["abnormal_vs_index_5d_pct"] == 8.0
    assert row["abnormal_vs_index_20d_pct"] == 16.0
    # peers: (2 + 6) / 2 = 4%, (4 + 8) / 2 = 6%, (10 + 12) / 2 = 11%
    assert row["abnormal_vs_peers_1d_pct"] == 0.0
    assert row["abnormal_vs_peers_5d_pct"] == 4.0
    assert row["abnormal_vs_peers_20d_pct"] == 10.0
    assert row["peers_used"] == 2


def test_a_horizon_that_is_not_complete_yet_is_missing():
    cut = STOCK.iloc[:26]  # fifteen trading days after the event day
    row = dc.post_disclosure_returns(cut, [EVENT], benchmark=XU100, peers=PEERS).iloc[0]
    assert row["return_5d_pct"] == 10.0
    assert pd.isna(row["return_20d_pct"]) and pd.isna(row["abnormal_vs_index_20d_pct"])


def test_missing_peers_or_benchmark_leave_those_columns_empty():
    row = _one(peers={})
    assert pd.isna(row["abnormal_vs_peers_5d_pct"]) and row["peers_used"] == 0
    assert row["abnormal_vs_index_5d_pct"] == 8.0
    row = _one(benchmark=None)
    assert pd.isna(row["abnormal_vs_index_5d_pct"]) and row["abnormal_vs_peers_5d_pct"] == 4.0


def test_an_event_on_a_day_without_a_bar_moves_to_the_next_bar():
    saturday = INDEX[9] + pd.Timedelta(days=1) if INDEX[9].day_of_week == 4 else None
    gap = STOCK.drop(INDEX[10])  # the stock did not trade on the event day
    row = dc.post_disclosure_returns(gap, [EVENT], benchmark=XU100, peers=PEERS).iloc[0]
    assert row["event_day"] == str(INDEX[11].date()) and row["base_day"] == str(INDEX[9].date())
    assert saturday is None or saturday not in STOCK.index


def test_an_event_before_the_first_bar_or_after_the_last_is_skipped():
    early, late = INDEX[0], INDEX[-1] + pd.Timedelta(days=30)
    table = dc.post_disclosure_returns(STOCK, [early, late, EVENT], benchmark=XU100, peers=PEERS)
    assert table["event_day"].tolist() == [str(EVENT.date())]


def test_prices_after_the_horizon_do_not_change_the_reaction():
    changed = STOCK.copy()
    changed.iloc[31:] *= 5
    pd.testing.assert_series_equal(
        dc.post_disclosure_returns(changed, [EVENT], benchmark=XU100, peers=PEERS).iloc[0], _one()
    )


def _reactions() -> pd.DataFrame:
    second = INDEX[21]
    return dc.post_disclosure_returns(STOCK, [EVENT, second], benchmark=XU100, peers=PEERS)


def test_summary_averages_over_events_and_counts_complete_horizons():
    table = _reactions()
    out = dc.summarize_reactions(table)
    assert out["events"] == 2
    one, five = out["horizons"]["1d"], out["horizons"]["5d"]
    # second event: base 110 (day 20), day 22 and day 26 still 110: 0% and 0%
    assert (one["events"], one["mean_return_pct"], one["median_return_pct"]) == (2, 2.0, 2.0)
    assert five["mean_return_pct"] == 5.0
    assert five["mean_abnormal_vs_index_pct"] == round((8.0 + 0.0) / 2, 2)
    # twenty days after the second event is beyond the data: only one event counts
    assert out["horizons"]["20d"]["events"] == 1
    assert out["sample_warning"] == "Very small sample size"


def test_summary_can_be_broken_down_by_a_group_label():
    table = _reactions()
    groups = pd.Series(["Improving", "Deteriorating"], index=table.index)
    out = dc.summarize_reactions(table, groups)
    assert out["by_group"]["Improving"]["events"] == 1
    assert out["by_group"]["Improving"]["mean_return_5d_pct"] == 10.0
    assert out["by_group"]["Deteriorating"]["mean_abnormal_vs_index_5d_pct"] == 0.0


def test_summary_of_no_events_is_empty():
    empty = dc.post_disclosure_returns(STOCK, [], benchmark=XU100, peers=PEERS)
    out = dc.summarize_reactions(empty)
    assert out["events"] == 0 and out["horizons"]["5d"]["mean_return_pct"] is None
    assert out["sample_warning"] == "Very small sample size"


@pytest.mark.parametrize("horizons", [(1, 5, 20), (3,)])
def test_columns_follow_the_requested_horizons(horizons):
    table = dc.post_disclosure_returns(
        STOCK, [EVENT], benchmark=XU100, peers=PEERS, horizons=horizons
    )
    for h in horizons:
        assert f"return_{h}d_pct" in table and f"abnormal_vs_peers_{h}d_pct" in table


def _known() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ticker": "TUPRS",
            "year": [2024, 2025],
            "quarter": [4, 1],
            "known_from": [EVENT, INDEX[21]],
        }
    )


def test_quarter_reactions_are_cut_at_the_analysis_date():
    late = dc.quarter_reactions(
        _known(), STOCK, benchmark=XU100, peers=PEERS, as_of=str(INDEX[-1].date())
    )
    assert late["period"].tolist() == ["2024Q4", "2025Q1"]
    assert late.iloc[0]["return_20d_pct"] == 21.0 and late.iloc[1]["return_5d_pct"] == 0.0
    early = dc.quarter_reactions(
        _known(), STOCK, benchmark=XU100, peers=PEERS, as_of=str(INDEX[16].date())
    )
    # on day 16 the five-day reaction of the first period is complete, the twenty-day one is not
    assert early.iloc[0]["return_5d_pct"] == 10.0 and pd.isna(early.iloc[0]["return_20d_pct"])
    # the second period only becomes usable on day 21: no reaction yet
    assert early["period"].tolist() == ["2024Q4"]


def test_reaction_study_labels_each_event_with_the_trend_known_that_day():
    from .test_fundamentals_tools import CPI, _calendar, _statements

    days = pd.date_range("2024-01-01", "2025-12-31", freq="B")
    rising = pd.Series(np.linspace(100.0, 200.0, len(days)), index=days)
    flat = pd.Series(100.0, index=days)
    study = dc.reaction_study(
        _statements(),
        _calendar(),
        closes={"TUPRS": rising},
        benchmark=flat,
        peer_closes={"TUPRS": {"P1": flat}},
        cpi=CPI,
        start="2025-01-01",
        end="2025-12-31",
    )
    table = study["events"]
    assert table["period"].tolist() == ["2024Q4", "2025Q2", "2025Q3"]
    assert table["ticker"].unique().tolist() == ["TUPRS"]
    assert table.iloc[-1]["fundamental_trend"] == "Improving"
    assert (table["return_5d_pct"] > 0).all()
    assert table["abnormal_vs_index_5d_pct"].equals(table["return_5d_pct"])
    summary = study["summary"]
    assert summary["events"] == 3 and "Improving" in summary["by_group"]
    assert summary["horizons"]["5d"]["events"] == 3
