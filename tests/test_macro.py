"""Macro layer: parsing the official pages, publication dates and the context summary."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.data import macro
from bist_harness.errors import DataUnavailableError
from bist_harness.tools.macro import macro_context

POLICY_HTML = """
<html><body><table>
<tr><td>Tarih</td><td>Borç Alma</td><td>Borç Verme</td></tr>
<tr><td>20.05.2010</td><td>-</td><td>7.00</td></tr>
<tr><td>21.03.2024</td><td>-</td><td>50.00</td></tr>
<tr><td>26.12.2024</td><td>-</td><td>47.50</td></tr>
<tr><td>23.01.2025</td><td>-</td><td>45.00</td></tr>
<tr><td>06.03.2025</td><td>-</td><td>42.50</td></tr>
</table></body></html>
"""

CPI_HTML = """
<html><body><table>
<thead><tr><th>Ay-Yıl</th><th>TÜFE (Yıllık % Değişim)</th><th>TÜFE (Aylık % Değişim)</th></tr></thead>
<tbody>
<tr><td>10-2026</td><td>29.77</td><td>2.58</td></tr>
<tr><td>09-2026</td><td>29.73</td><td>1.84</td></tr>
<tr><td>08-2026</td><td>31.51</td><td>1.84</td></tr>
</tbody></table></body></html>
"""

FED_HTML = """
<html><body>
<h4 class="borderdash">FOMC's target federal funds rate or range, change and level</h4>
<p><a href="#2025">2025</a> | <a href="#2024">2024</a></p>
<h4 id="2025">2025</h4>
<table><thead><tr><th>Date</th><th>Increase</th><th>Decrease</th><th>Level (%)</th></tr></thead>
<tbody>
<tr><td>October 29</td><td>0</td><td>25</td><td>3.75-4.00</td></tr>
<tr><td>September 17</td><td>0</td><td>25</td><td>4.00-4.25</td></tr>
</tbody></table>
<h4 id="2024">2024</h4>
<table><thead><tr><th>Date</th><th>Increase</th><th>Decrease</th><th>Level (%)</th></tr></thead>
<tbody>
<tr><td>December 18</td><td>0</td><td>25</td><td>4.25-4.50</td></tr>
<tr><td>September 18 (unscheduled)</td><td>0</td><td>50</td><td>4.75–5.00</td></tr>
</tbody></table>
<h4 id="2007">2007</h4>
<table><thead><tr><th>Date</th><th>Increase</th><th>Decrease</th><th>Level (%)</th></tr></thead>
<tbody><tr><td>December 11</td><td>0</td><td>25</td><td>4.25</td></tr></tbody></table>
</body></html>
"""


def test_policy_rate_table_is_read_as_dated_decisions():
    table = macro.parse_policy_rate(POLICY_HTML)
    assert list(table.columns) == ["effective_date", "rate"]
    assert table["effective_date"].is_monotonic_increasing
    assert table.iloc[0].tolist() == [pd.Timestamp("2010-05-20"), 7.0]
    assert table.iloc[-1].tolist() == [pd.Timestamp("2025-03-06"), 42.5]
    assert len(table) == 5


def test_cpi_table_gets_month_ends_and_publication_dates():
    table = macro.parse_cpi(CPI_HTML)
    assert list(table.columns) == ["period", "annual_pct", "monthly_pct", "published"]
    assert table["period"].tolist() == [
        pd.Timestamp("2026-08-31"),
        pd.Timestamp("2026-09-30"),
        pd.Timestamp("2026-10-31"),
    ]
    assert table.iloc[-1][["annual_pct", "monthly_pct"]].tolist() == [29.77, 2.58]
    assert table.iloc[-1]["published"] == pd.Timestamp("2026-11-03")


def test_fed_target_table_takes_the_year_from_the_heading_above_it():
    table = macro.parse_fed_target(FED_HTML)
    assert list(table.columns) == ["effective_date", "lower", "upper"]
    assert table["effective_date"].tolist() == [
        pd.Timestamp("2007-12-11"),
        pd.Timestamp("2024-09-18"),
        pd.Timestamp("2024-12-18"),
        pd.Timestamp("2025-09-17"),
        pd.Timestamp("2025-10-29"),
    ]
    assert table.iloc[0][["lower", "upper"]].tolist() == [4.25, 4.25]  # a single target
    assert table.iloc[1][["lower", "upper"]].tolist() == [4.75, 5.0]  # en dash in the range
    assert table.iloc[-1][["lower", "upper"]].tolist() == [3.75, 4.0]


@pytest.mark.parametrize(
    "period,published",
    [
        ("2026-10", "2026-11-03"),  # a Tuesday
        ("2026-09", "2026-10-05"),  # the 3rd is a Saturday
        ("2026-04", "2026-05-04"),  # the 3rd is a Sunday
        ("2025-12", "2026-01-05"),  # across the year end; the 3rd is a Saturday
    ],
)
def test_cpi_is_published_on_the_third_of_the_next_month_or_the_next_working_day(period, published):
    assert macro.cpi_publication_date(pd.Period(period, "M")) == pd.Timestamp(published)
    assert macro.cpi_publication_date(pd.Period(period, "M").end_time) == pd.Timestamp(published)


def test_cpi_index_chains_the_monthly_changes():
    index = macro.cpi_index(macro.parse_cpi(CPI_HTML))
    assert index.index.tolist() == [
        pd.Timestamp("2026-08-31"),
        pd.Timestamp("2026-09-30"),
        pd.Timestamp("2026-10-31"),
    ]
    assert index.iloc[0] == 100.0
    assert index.iloc[1] == pytest.approx(100.0 * 1.0184)
    assert index.iloc[2] == pytest.approx(100.0 * 1.0184 * 1.0258)


def _series() -> dict[str, pd.DataFrame]:
    days = pd.date_range("2024-01-01", "2026-11-13", freq="B")
    fx = pd.DataFrame(
        {
            "USDTRY": np.linspace(30.0, 50.0, len(days)),
            "EURTRY": np.linspace(33.0, 55.0, len(days)),
        },
        index=days,
    )
    return {
        "fx": fx,
        "policy_rate": macro.parse_policy_rate(POLICY_HTML),
        "fed_target": macro.parse_fed_target(FED_HTML),
        "cpi": macro.parse_cpi(CPI_HTML),
    }


def test_context_reports_fx_change_and_the_rates_in_effect():
    out = macro_context(_series(), start="2025-01-01", end="2025-06-30")
    fx = _series()["fx"].loc["2025-01-01":"2025-06-30"]
    assert out["usdtry_start"] == round(float(fx["USDTRY"].iloc[0]), 4)
    assert out["usdtry_end"] == round(float(fx["USDTRY"].iloc[-1]), 4)
    assert out["usdtry_change_pct"] == round(
        float(fx["USDTRY"].iloc[-1] / fx["USDTRY"].iloc[0] - 1) * 100, 2
    )
    assert out["eurtry_change_pct"] > 0
    # in effect on 2025-01-01: the decision of 2024-12-26; two decisions inside the period
    assert (out["policy_rate_start"], out["policy_rate_end"]) == (47.5, 42.5)
    assert out["policy_rate_changes"] == 2 and out["policy_rate_change_pp"] == -5.0
    assert out["last_policy_decision_date"] == "2025-03-06"
    assert (out["fed_target_lower_start"], out["fed_target_upper_start"]) == (4.25, 4.5)
    assert (out["fed_target_lower_end"], out["fed_target_upper_end"]) == (4.25, 4.5)
    assert out["fed_changes"] == 0
    # the sample CPI table starts in 2026, so nothing was published by mid-2025
    assert [w.split(":")[0] for w in out["warnings"]] == ["NO_CPI_DATA"]


def test_context_uses_only_cpi_published_by_the_end_date():
    before = macro_context(_series(), start="2026-09-01", end="2026-11-02")
    assert (before["cpi_period"], before["cpi_annual_pct"]) == ("2026-09", 29.73)
    assert before["cpi_published"] == "2026-10-05"
    on_the_day = macro_context(_series(), start="2026-09-01", end="2026-11-03")
    assert (
        on_the_day["cpi_period"],
        on_the_day["cpi_annual_pct"],
        on_the_day["cpi_monthly_pct"],
    ) == (
        "2026-10",
        29.77,
        2.58,
    )
    early = macro_context(_series(), start="2026-01-01", end="2026-06-30")
    assert early["cpi_period"] is None and early["cpi_annual_pct"] is None


def test_context_does_not_change_when_later_rows_are_removed():
    full = macro_context(_series(), start="2025-01-01", end="2025-06-30")
    cut = {
        "fx": _series()["fx"].loc[:"2025-06-30"],
        "policy_rate": _series()["policy_rate"].query("effective_date <= '2025-06-30'"),
        "fed_target": _series()["fed_target"].query("effective_date <= '2025-06-30'"),
        "cpi": _series()["cpi"].query("published <= '2025-06-30'"),
    }
    assert macro_context(cut, start="2025-01-01", end="2025-06-30") == full


def test_missing_series_give_warnings_and_none_values_not_errors():
    series = _series()
    del series["fx"], series["cpi"]
    out = macro_context(series, start="2025-01-01", end="2025-06-30")
    assert out["usdtry_start"] is None and out["usdtry_change_pct"] is None
    assert out["cpi_annual_pct"] is None and out["policy_rate_end"] == 42.5
    assert sorted(w.split(":")[0] for w in out["warnings"]) == ["NO_CPI_DATA", "NO_FX_DATA"]
    empty = macro_context({}, start="2025-01-01", end="2025-06-30")
    assert len(empty["warnings"]) == 4 and empty["policy_rate_start"] is None


def _fetch(url: str) -> str:
    pages = {
        macro.SOURCES["policy_rate"]: POLICY_HTML,
        macro.SOURCES["cpi"]: CPI_HTML,
        macro.SOURCES["fed_target"]: FED_HTML,
    }
    return pages[url]


def _fx_download(symbol, start, end):
    days = pd.date_range("2024-01-01", periods=30, freq="B")
    level = 30.0 if symbol == "USDTRY=X" else 33.0
    return pd.DataFrame({"Close": level + np.arange(30.0)}, index=days)


def test_build_writes_the_four_series_and_they_load_back(tmp_path):
    counts = macro.build_macro(tmp_path / "s1", fetch=_fetch, fx_downloader=_fx_download)
    assert counts == {"fx": 30, "policy_rate": 5, "fed_target": 5, "cpi": 3}
    assert sorted(p.name for p in (tmp_path / "s1" / "macro").iterdir()) == [
        "cpi.parquet",
        "fed_target.parquet",
        "fx.parquet",
        "manifest.json",
        "policy_rate.parquet",
    ]
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")
    fx = macro.load_macro("fx", root=tmp_path)
    assert list(fx.columns) == ["USDTRY", "EURTRY"] and len(fx) == 30
    pd.testing.assert_frame_equal(
        macro.load_macro("cpi", root=tmp_path), macro.parse_cpi(CPI_HTML), check_dtype=False
    )


def test_a_source_that_fails_is_reported_and_the_others_are_still_written(tmp_path):
    def flaky(url):
        if url == macro.SOURCES["fed_target"]:
            raise RuntimeError("timeout")
        return _fetch(url)

    counts = macro.build_macro(tmp_path / "s1", fetch=flaky, fx_downloader=_fx_download)
    assert counts["fed_target"] == 0 and counts["cpi"] == 3
    assert not (tmp_path / "s1" / "macro" / "fed_target.parquet").exists()


def test_loading_a_series_that_was_not_built_names_the_build_command(tmp_path):
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")
    with pytest.raises(DataUnavailableError, match="macro build"):
        macro.load_macro("cpi", root=tmp_path)
    with pytest.raises(ValueError):
        macro.load_macro("gold", root=tmp_path)


@pytest.fixture
def macro_series(monkeypatch):
    from bist_harness.mcp_server import server as srv

    series = _series()

    def load(name):
        if name not in series:
            raise DataUnavailableError(f"Snapshot s has no macro series {name}.")
        return series[name]

    monkeypatch.setattr(srv, "load_macro", load)
    return series


def test_macro_tool_returns_the_context_with_versions(macro_series):
    from bist_harness.mcp_server import server as srv

    out = srv.get_macro_context("2026-09-01", "2026-11-03")
    expected = macro_context(macro_series, start="2026-09-01", end="2026-11-03")
    for key, value in expected.items():
        assert out[key] == value
    assert out["cpi_period"] == "2026-10" and out["snapshot_id"] and len(out["result_id"]) == 12
    assert "TCMB" in out["data_source"] and "Federal Reserve" in out["data_source"]


def test_macro_tool_keeps_going_when_one_series_is_missing(macro_series):
    from bist_harness.mcp_server import server as srv

    del macro_series["fed_target"]
    out = srv.get_macro_context("2025-01-01", "2025-06-30")
    assert out["policy_rate_end"] == 42.5 and out["fed_target_upper_end"] is None
    assert any(w.startswith("NO_FED_TARGET_DATA") for w in out["warnings"])


def test_macro_tool_without_any_series_names_the_build_command(monkeypatch):
    from bist_harness.mcp_server import server as srv

    def load(name):
        raise DataUnavailableError("Snapshot s has no macro series. Run `... macro build` first.")

    monkeypatch.setattr(srv, "load_macro", load)
    out = srv.get_macro_context("2025-01-01", "2025-06-30")
    assert out["error"]["code"] == "DATA_UNAVAILABLE" and "macro build" in out["error"]["message"]


@pytest.mark.parametrize(
    "start,end,code",
    [
        ("2025-06-30", "2025-01-01", "INVALID_DATE_RANGE"),
        ("2025-01-01", "2999-01-01", "FUTURE_DATE"),
        ("01.01.2025", "2025-06-30", "INVALID_DATE"),
    ],
)
def test_macro_tool_bad_period(start, end, code, macro_series):
    from bist_harness.mcp_server import server as srv

    assert srv.get_macro_context(start, end)["error"]["code"] == code
