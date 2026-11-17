"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

The unseen evaluation question set (card EC-060, design spec section 12).

``questions.jsonl`` holds 120 questions, one JSON object per line::

    {"id", "category", "lang", "question", "source", "trap", "expected"}

* ``category``: one of the four mandatory scenarios (20 each, half Turkish), ``TRAP``
  (20: advice, prediction, out-of-universe stock, future date, reversed range, misspelled
  ticker, off-topic) or ``AMBIGUOUS`` (20: vague or two-tool questions).
* ``source``: ``fresh`` (written for this set) or ``review`` (a phrasing an earlier review
  found slipping past the keyword guards; kept word for word on purpose).
* ``trap``: the kind of trap, ``null`` outside ``TRAP``.
* ``expected``: ``scenarios`` (acceptable intent scenarios), ``outcomes`` (acceptable
  outcome classes, see ``OUTCOMES``), ``ticker``, ``sector`` (a peer-group name),
  ``start``, ``end``, ``as_of`` (``null`` when the question gives none), ``reason`` (the
  ``check_intent`` code a guarded question should end with) and ``tools`` (tools a
  two-tool question needs).

The set is frozen: its SHA-256 (line endings normalised to LF) is written in this module
(``FROZEN_SHA256``, also in the decision log) and in ``questions.sha256``;
``verify_frozen`` refuses a set that no longer has that hash, even when the hash file
was edited along with it. Fine-tuning data
(Sprint 5) must not share a question with it: ``overlaps`` finds near copies.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from difflib import SequenceMatcher
from pathlib import Path

from bist_harness.harness.intent import fold_text

QUESTIONS_PATH = Path(__file__).with_name("questions.jsonl")
HASH_PATH = Path(__file__).with_name("questions.sha256")
CATEGORIES = (
    "SECTOR_LAGGARD",
    "CALENDAR_PATTERN",
    "TECHNICAL_REVERSAL",
    "FUNDAMENTAL_REACTION",
    "TRAP",
    "AMBIGUOUS",
)
# Outcome classes: ANALYSIS is any action label other than ANALYSIS_UNSAFE.
OUTCOMES = ("ANALYSIS", "REFUSED_ADVICE", "OUT_OF_SCOPE", "ANALYSIS_UNSAFE")
# The SHA-256 of the frozen set. A frozen set is not edited; this constant never changes.
FROZEN_SHA256 = "e6141ea876724b786d84d78e7960f7865146a9f13074687cefe64aaa1fb3bcae"
OVERLAP_THRESHOLD = 0.8  # SequenceMatcher ratio of the folded texts


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    """The questions in file order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def file_sha256(path: Path = QUESTIONS_PATH) -> str:
    """SHA-256 of the file with CRLF read as LF, so a Windows checkout hashes the same."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def recorded_sha256() -> str:
    """The hash recorded when the set was frozen (first word of ``questions.sha256``)."""
    return HASH_PATH.read_text(encoding="utf-8").split()[0]


def verify_frozen(path: Path = QUESTIONS_PATH) -> None:
    """Raise ``ValueError`` when the set or its hash file no longer has the frozen hash."""
    found = file_sha256(path)
    if found != FROZEN_SHA256 or recorded_sha256() != FROZEN_SHA256:
        raise ValueError(
            f"the question set changed (sha256 {found}, frozen {FROZEN_SHA256}); "
            "a frozen set is not edited"
        )


def overlaps(
    texts: Iterable[str],
    *,
    threshold: float = OVERLAP_THRESHOLD,
    questions: list[dict] | None = None,
) -> list[tuple[str, str, float]]:
    """``(text, question id, ratio)`` for every text that copies or closely paraphrases a
    question of the set: the similarity ratio of the folded texts (lower case, no
    diacritics, no punctuation) reaches ``threshold``."""
    pool = [(q["id"], fold_text(q["question"]).strip()) for q in questions or load_questions()]
    found: list[tuple[str, str, float]] = []
    for text in texts:
        folded = fold_text(text).strip()
        if not folded:
            continue
        for qid, question in pool:
            ratio = SequenceMatcher(None, folded, question).ratio()
            if ratio >= threshold:
                found.append((text, qid, round(ratio, 3)))
    return found
