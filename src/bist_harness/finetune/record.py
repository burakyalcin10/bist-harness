"""The training record: one model turn of a harness run and its correct reply.

A record holds the messages and tool schemas exactly as the harness sent them to the model
in that turn, and the target reply. Training therefore sees the same format as inference.
Files are JSON Lines, one record per line, written with ``\\n`` only. Keys keep the order
in which they were built (the harness's order for messages and tool schemas, which the
chat template renders), so the same records always give the same bytes (and SHA-256).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

TURN_KINDS = ("intent", "tool_call", "explanation")


@dataclass(frozen=True)
class TrainingRecord:
    record_id: str
    question_id: str
    family: str
    language: str
    scenario: str
    turn: str  # one of TURN_KINDS
    state: str | None  # the tool state of a tool_call turn, else None
    messages: list[dict]  # what the harness sent in this turn, as sent
    tools: list[dict]  # the tool schemas offered in this turn ([] for intent and explanation)
    # {"role": "assistant", "content": str} or {"role": "assistant", "tool_calls": [...]}
    target: dict
    # turn level, by the teacher: state (tool_call), action and eligible (explanation);
    # run level, added by the build: outcome, snapshot_id, layers_id, today
    meta: dict

    def __post_init__(self) -> None:
        if self.turn not in TURN_KINDS:
            raise ValueError(f"unknown turn kind: {self.turn!r}")
        if (self.turn == "tool_call") != (self.state is not None):
            raise ValueError("a tool_call record names its state; other turns name none")


def _line(record: TrainingRecord) -> str:
    return json.dumps(dataclasses.asdict(record), ensure_ascii=False)


def write_jsonl(records: Iterable[TrainingRecord], path: Path) -> str:
    """Write the records, one per line; return the SHA-256 of the file."""
    text = "".join(_line(record) + "\n" for record in records)
    path = Path(path)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[TrainingRecord]:
    """The records of a file written by ``write_jsonl``."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [TrainingRecord(**json.loads(line)) for line in lines if line.strip()]
