"""Price-series data-quality checks: one deliberately broken series per finding code."""

import pandas as pd
import pytest

from bist_harness.quality.checks import Finding, check_price_series

from .synth import ohlcv


def _clean() -> pd.DataFrame:
    return ohlcv(120, 3)


LAST = _clean().index[-1]
AS_OF = str(LAST.date())  # last bar of the synthetic series


def _codes(findings: list[Finding]) -> dict[str, Finding]:
    return {f.code: f for f in findings}


def test_clean_series_has_no_findings():
    df = _clean()
    assert check_price_series(df, as_of=AS_OF, expected_days=df.index) == []


def test_empty_series_is_a_hard_finding_and_nothing_else_is_checked():
    findings = check_price_series(_clean().iloc[:0], as_of=AS_OF)
    assert [(f.code, f.severity) for f in findings] == [("EMPTY_SERIES", "hard")]


def _duplicated(df):
    return pd.concat([df, df.iloc[[10, 11]]]).sort_index()


def _unsorted(df):
    return pd.concat([df.iloc[60:], df.iloc[:60]])


def _non_positive(df):
    df.iloc[5, df.columns.get_loc("Close")] = 0.0
    df.iloc[6, df.columns.get_loc("Low")] = -1.0
    return df


def _inconsistent(df):
    df.iloc[7, df.columns.get_loc("High")] = df["Close"].iloc[7] * 0.9
    return df


def _jump(df):
    df.iloc[50:, :4] *= 1.6
    return df


def _zero_volume(df):
    df.iloc[[3, 4, 5], df.columns.get_loc("Volume")] = 0.0
    return df


@pytest.mark.parametrize(
    "breaker,code,severity,count",
    [
        (lambda df: df.iloc[:40], "SHORT_HISTORY", "soft", 1),
        (_duplicated, "DUPLICATE_DATES", "hard", 2),
        (_unsorted, "NON_MONOTONIC_INDEX", "hard", 1),
        (_non_positive, "NON_POSITIVE_PRICE", "hard", 2),
        (_inconsistent, "OHLC_INCONSISTENT", "hard", 1),
        (_jump, "PRICE_JUMP", "soft", 1),
        (_zero_volume, "ZERO_VOLUME", "soft", 3),
    ],
)
def test_each_defect_is_reported_with_its_code_severity_and_count(breaker, code, severity, count):
    df = breaker(_clean())
    as_of = str(df.index.max().date())
    finding = _codes(check_price_series(df, as_of=as_of))[code]
    assert (finding.severity, finding.count) == (severity, count)
    assert finding.message


def test_missing_days_are_counted_against_the_expected_calendar():
    df = _clean()
    finding = _codes(
        check_price_series(df.drop(df.index[[20, 21, 70]]), as_of=AS_OF, expected_days=df.index)
    )["MISSING_DAYS"]
    assert (finding.severity, finding.count) == ("soft", 3)


def test_missing_days_are_not_checked_without_a_calendar():
    df = _clean()
    assert check_price_series(df.drop(df.index[[20, 21]]), as_of=AS_OF) == []


def test_stale_data_when_the_last_bar_is_more_than_five_trading_days_old():
    df = _clean()
    five_later = str((LAST + pd.offsets.BDay(5)).date())
    six_later = str((LAST + pd.offsets.BDay(6)).date())
    assert check_price_series(df, as_of=five_later) == []
    finding = _codes(check_price_series(df, as_of=six_later))["STALE_DATA"]
    assert finding.severity == "soft"


def test_rows_after_the_analysis_date_are_a_hard_finding():
    df = _clean()
    finding = _codes(check_price_series(df, as_of=str(df.index[-6].date())))["FUTURE_ROWS"]
    assert (finding.severity, finding.count) == ("hard", 5)


def test_several_problems_are_reported_together():
    df = _zero_volume(_jump(_clean())).iloc[:40]
    codes = set(_codes(check_price_series(df, as_of=str(df.index[-1].date()))))
    assert codes == {"SHORT_HISTORY", "ZERO_VOLUME"}
    df = _zero_volume(_jump(_non_positive(_clean())))
    codes = set(_codes(check_price_series(df, as_of=AS_OF)))
    assert {"NON_POSITIVE_PRICE", "PRICE_JUMP", "ZERO_VOLUME"} <= codes


def test_report_lists_totals_and_only_symbols_with_findings():
    from bist_harness.quality.report import render_report

    findings = {
        "ASELS": [],
        "CCOLA": [Finding("PRICE_JUMP", "soft", "jump", 1), Finding("ZERO_VOLUME", "soft", "z", 2)],
        "SASA": [Finding("ZERO_VOLUME", "soft", "z", 155)],
    }
    text = render_report(findings, snapshot_id="s1", as_of="2026-11-13")
    assert "s1" in text and "2026-11-13" in text
    assert "| ZERO_VOLUME | soft | 2 |" in text
    assert "| PRICE_JUMP | soft | 1 |" in text
    assert "| CCOLA | PRICE_JUMP ×1, ZERO_VOLUME ×2 |" in text
    assert "| SASA | ZERO_VOLUME ×155 |" in text
    assert "| ASELS |" not in text
    assert "Symbols checked: 3" in text and "without findings: 1" in text
