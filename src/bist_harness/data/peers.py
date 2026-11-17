"""Sector peer groups.

Yahoo carries history for only four BIST indices, so a sector's median return is computed
from a peer group: the universe stocks of that sector plus reference stocks from outside
the universe. Reference stocks are used for the median only; they are never analysis
targets.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from bist_harness.config import REPO_ROOT
from bist_harness.universe import load_universe, normalize_ticker

PEER_GROUPS_PATH = REPO_ROOT / "data" / "reference" / "peer_groups.csv"
MIN_PEERS = 3  # members including the target


@dataclass(frozen=True)
class PeerGroup:
    name: str
    universe: tuple[str, ...]
    reference: tuple[str, ...]

    @property
    def members(self) -> tuple[str, ...]:
        return self.universe + self.reference


def load_peer_groups(path: Path | None = None) -> dict[str, PeerGroup]:
    df = pd.read_csv(path or PEER_GROUPS_PATH, dtype=str, keep_default_na=False)
    groups: dict[str, PeerGroup] = {}
    for name, rows in df.groupby("group", sort=False):
        groups[str(name)] = PeerGroup(
            name=str(name),
            universe=tuple(rows.loc[rows["role"] == "universe", "ticker"]),
            reference=tuple(rows.loc[rows["role"] == "reference", "ticker"]),
        )
    return groups


@lru_cache(maxsize=1)
def _groups() -> dict[str, PeerGroup]:
    return load_peer_groups()


def peer_group_of(ticker: str) -> PeerGroup:
    """Group of a universe stock; ``KeyError`` for anything else."""
    name = normalize_ticker(ticker)
    for group in _groups().values():
        if name in group.universe:
            return group
    raise KeyError(name)


def resolve_sector(name: str) -> PeerGroup:
    """Find a group by its own name or by a sector label of the universe file."""
    wanted = name.strip().casefold()
    for group in _groups().values():
        if group.name.casefold() == wanted:
            return group
    universe = load_universe()
    tickers = universe.loc[universe["sector"].str.casefold() == wanted, "ticker"]
    found = {peer_group_of(t).name for t in tickers}
    if len(found) != 1:
        raise KeyError(name)
    return _groups()[found.pop()]


def all_symbols() -> list[str]:
    """Universe and reference tickers, each once, universe stocks first."""
    groups = _groups().values()
    ordered = [t for g in groups for t in g.universe] + [t for g in groups for t in g.reference]
    return list(dict.fromkeys(ordered))
