"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

Episodic memory (design spec section 10, card EC-047): the earlier analyses of the same
stock and what a human decided about them.

The three memories of the harness: temporal (the Parquet layers), episodic (this module:
the SQLite ``analyses`` and ``decisions`` tables) and procedural (routes, permissions and
templates in code); ``docs/data_dictionary.md`` section 16 lists them.

A memory item is shown to the user (the answer, the review screen, the decision log) and
never reaches a model: it is ``Evidence`` with ``committed=False`` and ``tool="memory"``,
it is not in the evidence given to the gate and the explanation step, and no prompt lists
it. Nothing from the future is recalled: only episodes whose ``as_of`` is strictly before
the new analysis's, that were stored before it, and a human decision only if it was made
strictly before the new analysis was created.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from bist_harness.harness.evidence import Evidence

NOT_ANALYSES = ("REFUSED_ADVICE", "OUT_OF_SCOPE", "MODEL_UNAVAILABLE")
HEADERS = {"tr": "Önceki analizler:", "en": "Earlier analyses:"}
_SENTENCES = {
    "tr": "{as_of}: {scenario}, etiket {action}; insan kararı: {decision}.",
    "en": "{as_of}: {scenario}, label {action}; human decision: {decision}.",
}
_NO_DECISION = {"tr": "yok", "en": "none yet"}
MEMORY_TOOL = "memory"


@dataclass(frozen=True)
class Episode:
    analysis_id: str
    as_of: str
    scenario: str
    action: str | None
    outcome: str
    human_result: str | None
    reason: str | None
    reviewed_at: str | None


def _scenario(intent_json: str | None) -> str:
    try:
        return str((json.loads(intent_json or "{}") or {}).get("scenario") or "unknown")
    except ValueError:
        return "unknown"


def recall(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    as_of: str,
    limit: int = 3,
    known_at: str | None = None,
    asking: str | None = None,
) -> list[Episode]:
    """The latest earlier analyses of ``ticker``, newest ``as_of`` first.

    Only episodes with ``as_of`` strictly before ``as_of``. ``known_at`` (the new
    analysis's ``created_at``) also drops episodes created after it and any human
    decision made at or after it; ``asking`` (its id) drops every row stored after it.
    """
    query = (
        "SELECT a.analysis_id, COALESCE(a.as_of, a.period_end), a.intent_json, a.action, "
        "a.outcome FROM analyses a WHERE a.ticker = ? AND a.outcome IS NOT NULL "
        f"AND a.outcome NOT IN ({', '.join('?' * len(NOT_ANALYSES))}) "
        "AND COALESCE(a.as_of, a.period_end) < ?"
    )
    args: list = [ticker, *NOT_ANALYSES, as_of]
    if known_at is not None:
        query += " AND a.created_at <= ?"
        args.append(known_at)
    if asking is not None:
        query += " AND a.rowid < (SELECT rowid FROM analyses WHERE analysis_id = ?)"
        args.append(asking)
    query += " ORDER BY COALESCE(a.as_of, a.period_end) DESC, a.rowid DESC LIMIT ?"
    args.append(limit)
    episodes = []
    for analysis_id, day, intent_json, action, outcome in conn.execute(query, args).fetchall():
        decision = "SELECT human_result, reason, reviewed_at FROM decisions WHERE analysis_id = ?"
        decision_args: list = [analysis_id]
        if known_at is not None:
            decision += " AND reviewed_at < ?"
            decision_args.append(known_at)
        row = conn.execute(decision + " ORDER BY id DESC LIMIT 1", decision_args).fetchone()
        human, reason, reviewed_at = row if row else (None, None, None)
        episodes.append(
            Episode(
                analysis_id,
                day,
                _scenario(intent_json),
                action,
                outcome,
                human,
                reason,
                reviewed_at,
            )
        )
    return episodes


def recall_for(conn: sqlite3.Connection, analysis, *, limit: int = 3) -> list[Episode]:
    """The episodes ``analysis`` saw (or would see): recalled as of its own time."""
    intent = analysis.intent or {}
    day = intent.get("as_of") or intent.get("end")
    if not intent.get("ticker") or not day:
        return []
    return recall(
        conn,
        ticker=intent["ticker"],
        as_of=day,
        limit=limit,
        known_at=analysis.created_at,
        asking=analysis.analysis_id,
    )


def memory_items(episodes: Sequence[Episode], *, language: str) -> list[Evidence]:
    """One uncommitted ``memory`` item per episode, labelled M1..Mn."""
    language = language if language in HEADERS else "en"
    items = []
    for number, episode in enumerate(episodes, start=1):
        sentence = _SENTENCES[language].format(
            as_of=episode.as_of,
            scenario=episode.scenario,
            action=episode.action or episode.outcome,
            decision=episode.human_result or _NO_DECISION[language],
        )
        items.append(
            Evidence(
                label=f"M{number}",
                tool=MEMORY_TOOL,
                result_id=episode.analysis_id,
                field="episode",
                value=dataclasses.asdict(episode),
                sentence=sentence,
                committed=False,
            )
        )
    return items


def episodes_of(analysis) -> list[dict]:
    """The episodes stored in the trail of ``analysis`` (set when its memory was on)."""
    for record in analysis.trail:
        if record.state == "BUILD_EVIDENCE" and "memory" in record.detail:
            return list(record.detail["memory"])
    return []


def items_of(analysis, *, language: str) -> list[Evidence]:
    return memory_items([Episode(**e) for e in episodes_of(analysis)], language=language)


def answer_section(items: Sequence[Evidence], *, language: str) -> str:
    """The short section appended to a shown answer; empty without items."""
    if not items:
        return ""
    language = language if language in HEADERS else "en"
    return "\n".join([HEADERS[language], *(f"{e.label}: {e.sentence}" for e in items)])


def strip_section(text: str) -> str:
    """``text`` without a memory section at its end (what the model's own text is)."""
    for header in HEADERS.values():
        cut = text.rfind(f"\n\n{header}\n")
        if cut != -1:
            text = text[:cut]
    return text
