"""Timestamped company events from KAP disclosure metadata (project brief, section 16).

The output is **context**: it tells what was disclosed and when. It carries no number
that could stand in for market or financial data, and no sentiment label.
"""

from __future__ import annotations

import pandas as pd

from bist_harness.data.kap import TOPICS
from bist_harness.universe import normalize_ticker

__all__ = ["TOPICS", "news_events"]
MAX_EVENTS = 12


def news_events(
    disclosures: pd.DataFrame,
    *,
    start: str,
    end: str,
    ticker: str | None = None,
    topic: str | None = None,
    limit: int = MAX_EVENTS,
) -> dict:
    """Disclosures published from ``start`` to the end of ``end``, newest first.

    ``total`` and ``by_topic`` count every match; ``events`` lists at most ``limit``.
    """
    if topic is not None and topic not in TOPICS:
        raise ValueError(f"topic must be one of {list(TOPICS)}")
    first = pd.Timestamp(start)
    last = pd.Timestamp(end) + pd.Timedelta(days=1)
    rows = disclosures[
        (disclosures["published_at"] >= first) & (disclosures["published_at"] < last)
    ]
    if ticker is not None:
        rows = rows[rows["ticker"] == normalize_ticker(ticker)]
    if topic is not None:
        rows = rows[rows["topic"] == topic]
    rows = rows.sort_values("published_at", ascending=False)
    counts = rows["topic"].value_counts()
    events = [
        {
            "published_at": pd.Timestamp(row.published_at).isoformat(timespec="seconds"),
            "ticker": row.ticker,
            "topic": row.topic,
            "subject": row.subject if not row.summary else f"{row.subject}: {row.summary}",
            "url": row.url,
        }
        for row in rows.head(limit).itertuples(index=False)
    ]
    return {
        "start": start,
        "end": end,
        "ticker": None if ticker is None else normalize_ticker(ticker),
        "topic": topic,
        "total": int(len(rows)),
        "by_topic": {name: int(counts[name]) for name in sorted(counts.index)},
        "events": events,
        "context_only": True,
        "warnings": [],
    }
