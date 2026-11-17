"""The frozen 30-stock study universe (project brief, section 5)."""

from bist_harness.universe import is_in_universe, load_universe, normalize_ticker


def test_universe_has_thirty_unique_tickers_with_expected_columns():
    u = load_universe()
    assert list(u.columns) == ["ticker", "yahoo_symbol", "sector"]
    assert len(u) == 30
    assert u["ticker"].is_unique


def test_yahoo_symbol_is_ticker_plus_is_suffix():
    u = load_universe()
    assert (u["yahoo_symbol"] == u["ticker"] + ".IS").all()


def test_every_stock_has_a_sector():
    assert load_universe()["sector"].str.len().gt(0).all()


def test_sector_spot_checks_against_the_brief():
    sector = load_universe().set_index("ticker")["sector"]
    assert sector["ASELS"] == "Technology / Defense"
    assert sector["KRDMD"] == "Basic Metals / Steel"
    assert sector["TRALT"] == "Mining"
    assert sector["CCOLA"] == "Food & Beverage"


def test_membership_ignores_case_and_yahoo_suffix():
    assert is_in_universe("asels")
    assert is_in_universe("THYAO.IS")
    assert is_in_universe(" tuprs ")


def test_stock_outside_the_universe_is_rejected():
    assert not is_in_universe("GARAN")
    assert not is_in_universe("")


def test_normalize_ticker():
    assert normalize_ticker(" asels.is ") == "ASELS"
