"""KAP disclosure metadata: the news and event layer (project brief, section 16).

Announcement 1 (item 3): KAP disclosures are a suitable source for company events
because they carry the official publication time. Only **metadata** is stored: time,
company, category, subject line, summary line, disclosure number and link. The text of a
disclosure is not stored, and nothing here is ever used in place of a number from a
deterministic tool.

A topic tag is assigned by fixed keyword rules on the subject and summary lines. There
is no sentiment label.

Build into the active snapshot (slow on purpose: KAP drops fast clients):
    uv run python -m bist_harness.data.kap build [pause_seconds] [time_budget_seconds]
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import pandas as pd

from bist_harness.data import snapshot
from bist_harness.data.fundamentals import (
    KAP_QUERY_URL,
    GetJson,
    PostJson,
    _http_post_json,
    fetch_member_oid,
)
from bist_harness.errors import DataUnavailableError
from bist_harness.universe import load_universe, normalize_ticker

COLUMNS = [
    "ticker",
    "published_at",
    "category",
    "subject",
    "summary",
    "disclosure_index",
    "url",
    "topic",
]
DISCLOSURE_URL = "https://www.kap.org.tr/tr/Bildirim/"
BUILD_HINT = "Run `uv run python -m bist_harness.data.kap build` first."
FIRST_DAY = "2025-01-01"

# First match wins, so the more specific topics come first.
TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "regulation_legal",
        ("dava", "ceza", "soruşturma", "rekabet kurulu", "mahkeme", "tedbir", "vergi incelemesi"),
    ),
    ("management", ("esas sözleşme", "kurumsal yönetim")),
    ("credit_rating", ("kredi derecelendirme", "derecelendirme notu")),
    ("structured_products", ("varant", "yatırım kuruluşu")),
    ("share_transactions", ("pay alım satım",)),
    ("buyback", ("geri alım", "geri alın", "payların geri")),
    ("dividend", ("kar payı", "kâr payı", "kar dağıtım", "kâr dağıtım", "temettü")),
    (
        "merger_acquisition",
        ("birleşme", "devralma", "bölünme", "duran varlık edinimi", "duran varlık satışı",
         "pay devri", "satın alma", "iştirak edinimi"),
    ),
    (
        "capital_increase",
        ("sermaye artırım", "sermaye azaltım", "bedelsiz", "bedelli", "kayıtlı sermaye", "rüçhan"),
    ),
    (
        "financing",
        ("kredi", "tahvil", "bono", "borçlanma aracı", "ihraç", "finansman", "sukuk",
         "sermaye piyasası aracı", "ihrac", "kira sertifika", "kupon"),
    ),
    ("contract", ("sözleşme", "ihale", "sipariş", "iş ilişkisi", "anlaşma")),
    ("investment", ("yatırım", "kapasite", "tesis", "fabrika", "teşvik")),
    (
        "earnings",
        ("finansal rapor", "finansal tablo", "faaliyet raporu", "sorumluluk beyanı",
         "geleceğe dönük", "beklenti"),
    ),
    (
        "management",
        ("genel kurul", "yönetim kurulu", "genel müdür", "atama", "istifa", "komite",
         "bağımsız denetim", "esas sözleşme", "kurumsal yönetim"),
    ),
)  # fmt: skip
TOPICS: tuple[str, ...] = (*dict.fromkeys(name for name, _ in TOPIC_RULES), "other")


def _fold(text: str | None) -> str:
    """Lower-case Turkish text (the dotted and dotless i do not survive ``str.lower``)."""
    return (text or "").replace("İ", "i").replace("I", "ı").lower()


def tag_topic(subject: str | None, summary: str | None) -> str:
    """Topic of a disclosure from its subject and summary lines."""
    text = f"{_fold(subject)} {_fold(summary)}"
    # Words that contain a keyword but mean something else: an export is not an issue of
    # securities, an investor is not an investment.
    text = text.replace("ihracat", "dış satım").replace("yatırımcı", "")
    for topic, keywords in TOPIC_RULES:
        if any(keyword in text for keyword in keywords):
            return topic
    return "other"


def fetch_disclosures(
    ticker: str,
    member_oid: str,
    start: str,
    end: str,
    *,
    disclosure_class: str = "ODA",
    post_json: PostJson | None = None,
) -> pd.DataFrame:
    """Material-event disclosures of one company, one request per calendar year."""
    post_json = post_json or _http_post_json
    rows = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        body = {
            "fromDate": max(start, f"{year}-01-01"),
            "toDate": min(end, f"{year}-12-31"),
            "memberType": "IGS",
            "mkkMemberOidList": [member_oid],
            "disclosureClass": disclosure_class,
            "subjectList": [],
            "bdkMemberOidList": [],
            "inactiveMkkMemberOidList": [],
            "term": "",
            "year": "",
            "ruleType": "",
            "period": "",
            "bdkReview": "",
            "disclosureIndexList": [],
            "mainSector": "",
            "sector": "",
            "subSector": "",
            "market": "",
            "index": "",
            "sdkMemberOidList": [],
            "fromSrc": False,
            "srcCategory": "",
            "isLate": "",
        }
        for item in post_json(KAP_QUERY_URL, body) or []:
            published = pd.to_datetime(
                item.get("publishDate"), format="%d.%m.%Y %H:%M:%S", errors="coerce"
            )
            if pd.isna(published):
                continue
            subject = (item.get("subject") or "").strip()
            summary = (item.get("summary") or "").strip()
            index = item.get("disclosureIndex")
            rows.append(
                {
                    "ticker": normalize_ticker(ticker),
                    "published_at": published,
                    "category": item.get("disclosureCategory") or "",
                    "subject": subject,
                    "summary": summary,
                    "disclosure_index": str(index) if index is not None else "",
                    "url": f"{DISCLOSURE_URL}{index}" if index is not None else "",
                    "topic": tag_topic(subject, summary),
                }
            )
    table = pd.DataFrame(rows, columns=COLUMNS)
    return table.sort_values("published_at").reset_index(drop=True)


def build_kap(
    folder: Path,
    tickers: Sequence[str],
    *,
    start: str,
    end: str,
    get_json: GetJson | None = None,
    post_json: PostJson | None = None,
    pause: float = 12.0,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    time_budget: float | None = None,
) -> list[str]:
    """Download disclosure metadata into ``folder/kap``; return the stocks still missing.

    The file is saved after every stock and finished stocks are remembered, so a run
    that is interrupted or hits the time budget is continued by the next one.
    """
    target = folder / "kap"
    target.mkdir(parents=True, exist_ok=True)
    data_path, state_path = target / "disclosures.parquet", target / "state.json"
    stored = pd.read_parquet(data_path) if data_path.is_file() else pd.DataFrame(columns=COLUMNS)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    done: list[str] = state.get("done", [])

    def save() -> None:
        stored.to_parquet(data_path)
        state_path.write_text(
            json.dumps({"done": done, "start": start, "end": end}, indent=2), encoding="utf-8"
        )

    began = time.monotonic()
    missing: list[str] = []
    for ticker in tickers:
        name = normalize_ticker(ticker)
        if name in done:
            continue
        if time_budget is not None and time.monotonic() - began > time_budget:
            missing.append(name)
            continue
        table = None
        for attempt in range(retries):
            try:
                oid = fetch_member_oid(name, get_json=get_json)
                table = fetch_disclosures(name, oid, start, end, post_json=post_json)
                break
            except Exception:  # noqa: BLE001 - retried below
                sleep(pause * (attempt + 2))
        if table is None:
            missing.append(name)
            continue
        if len(table):
            stored = table if stored.empty else pd.concat([stored, table], ignore_index=True)
        done.append(name)
        save()
        sleep(pause)
    save()
    return missing


def load_disclosures(*, snapshot_id: str | None = None, root: Path | None = None) -> pd.DataFrame:
    """Disclosure metadata of every stock in a snapshot (the active one by default)."""
    snapshot_id = snapshot_id or snapshot.active_snapshot_id(root)
    path = snapshot._root(root) / snapshot_id / "kap" / "disclosures.parquet"
    if not path.is_file():
        raise DataUnavailableError(f"Snapshot {snapshot_id} has no KAP disclosures. {BUILD_HINT}")
    table = pd.read_parquet(path)
    table["published_at"] = pd.to_datetime(table["published_at"])
    # Tags come from the rules of the code that reads the file, not of the day it was
    # downloaded: a rule change applies without asking KAP again.
    table["topic"] = [
        tag_topic(subject, summary)
        for subject, summary in zip(table["subject"], table["summary"], strict=True)
    ]
    return table


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] != ["build"]:
        print("usage: python -m bist_harness.data.kap build [pause] [seconds]")
        return 2
    folder = snapshot._root(None) / snapshot.active_snapshot_id()
    last_bar = str(snapshot.load_history("XU100").index[-1].date())
    left = build_kap(
        folder,
        list(load_universe()["ticker"]),
        start=FIRST_DAY,
        end=last_bar,
        pause=float(args[1]) if len(args) > 1 else 12.0,
        time_budget=float(args[2]) if len(args) > 2 else None,
    )
    print("still missing:", left)
    return 1 if left else 0


if __name__ == "__main__":
    raise SystemExit(main())
