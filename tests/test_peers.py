"""Sector peer groups: every universe stock has exactly one group with enough members."""

import pytest

from bist_harness.data import peers
from bist_harness.universe import is_in_universe, load_universe


def test_every_universe_stock_belongs_to_exactly_one_group():
    groups = peers.load_peer_groups()
    owners = {}
    for group in groups.values():
        for ticker in group.universe:
            assert ticker not in owners, f"{ticker} is in two groups"
            owners[ticker] = group.name
    assert set(owners) == set(load_universe()["ticker"])


def test_reference_stocks_are_outside_the_universe_and_unique():
    seen = set()
    for group in peers.load_peer_groups().values():
        for ticker in group.reference:
            assert not is_in_universe(ticker)
            assert ticker not in seen
            seen.add(ticker)


def test_members_lists_universe_stocks_first():
    banking = peers.load_peer_groups()["Banking"]
    assert banking.universe == ("AKBNK",)
    assert banking.members == ("AKBNK", "GARAN", "ISCTR", "YKBNK", "HALKB", "VAKBN")


def test_only_telecom_is_below_the_minimum_group_size():
    small = [g.name for g in peers.load_peer_groups().values() if len(g.members) < peers.MIN_PEERS]
    assert small == ["Telecom"]


def test_peer_group_of_a_universe_stock_and_of_a_reference_stock():
    assert peers.peer_group_of("krdmd.is").name == "Steel"
    with pytest.raises(KeyError):
        peers.peer_group_of("GARAN")


@pytest.mark.parametrize(
    "name,group",
    [
        ("Banking", "Banking"),
        ("banking", "Banking"),
        ("Basic Metals / Steel", "Steel"),
        ("Retail Trade", "Retail"),
        ("Retail / Apparel", "Retail"),
        ("Telecommunications", "Telecom"),
        ("  Petrochemicals ", "Energy / Petrochemicals"),
    ],
)
def test_resolve_sector_accepts_group_names_and_universe_sector_labels(name, group):
    assert peers.resolve_sector(name).name == group


def test_resolve_sector_rejects_unknown_names():
    with pytest.raises(KeyError):
        peers.resolve_sector("Crypto")


def test_every_universe_sector_label_resolves():
    for label in set(load_universe()["sector"]):
        peers.resolve_sector(label)


def test_all_symbols_is_unique_and_holds_universe_and_reference():
    symbols = peers.all_symbols()
    assert len(symbols) == len(set(symbols))
    assert {"ASELS", "GARAN", "VESBE"} <= set(symbols)
    assert len(symbols) == 30 + sum(len(g.reference) for g in peers.load_peer_groups().values())
