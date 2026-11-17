"""Data-quality report for every series of a snapshot.

Run:  uv run python -m bist_harness.quality.report [as_of] > docs/results/<file>.md
"""

from __future__ import annotations

import sys
from collections import Counter

from bist_harness.data import snapshot
from bist_harness.quality.checks import Finding, check_price_series

CALENDAR_SYMBOL = "XU100"


def snapshot_findings(as_of: str, *, adjust: bool = True) -> dict[str, list[Finding]]:
    """Check every non-empty series of the active snapshot against the XU100 calendar."""
    calendar = snapshot.load_history(CALENDAR_SYMBOL).index
    result: dict[str, list[Finding]] = {}
    for entry in snapshot.load_manifest().series:
        if entry.rows == 0:
            result[entry.symbol] = [Finding("EMPTY_SERIES", "hard", "The series has no rows.")]
            continue
        df = snapshot.load_history(entry.symbol, adjust=adjust).loc[:as_of]
        result[entry.symbol] = check_price_series(df, as_of=as_of, expected_days=calendar)
    return result


def render_report(findings: dict[str, list[Finding]], *, snapshot_id: str, as_of: str) -> str:
    totals = Counter((f.code, f.severity) for items in findings.values() for f in items)
    clean = sum(1 for items in findings.values() if not items)
    lines = [
        f"# Data-quality report — snapshot `{snapshot_id}`, as of {as_of}",
        "",
        f"Symbols checked: {len(findings)}; without findings: {clean}.",
        "",
        "| Code | Severity | Symbols affected |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {code} | {sev} | {n} |" for (code, sev), n in sorted(totals.items())]
    lines += ["", "| Symbol | Findings |", "| --- | --- |"]
    for symbol, items in findings.items():
        if items:
            lines.append(f"| {symbol} | {', '.join(f'{f.code} ×{f.count}' for f in items)} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    manifest = snapshot.load_manifest()
    as_of = args[0] if args else max(s.last_date for s in manifest.series if s.rows)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(render_report(snapshot_findings(as_of), snapshot_id=manifest.snapshot_id, as_of=as_of))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
