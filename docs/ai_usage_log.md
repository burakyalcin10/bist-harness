# AI usage log

Course policy (Week 1 slides, p. 31, "AI Use Policy"):

> AI tools may support idea generation, coding assistance and understanding.
> Students remain responsible for the analysis, interpretation and final work.
> Prompts and materially used AI outputs should be documented in the appendix.
> Financial outputs must be verified against the underlying data and code.

This log is the source of the report appendix. One row per materially used AI contribution.
"Verified by Claude" lists the checks the tool itself ran; **"Verified by Burak" is filled
in by the student** after reading the code or output, and a row is not report-ready until
it is.

The delivered system itself calls no cloud AI service: the model is an open-source LLM
served by Ollama on hardware the student owns.

| Date | Tool / model | Prompt (verbatim or summary) | Output used in the project | Verified by Claude | Verified by Burak | Card |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-11-17 | Claude Code (Claude Fable 5.2) | "dizini incele, economy dersi için proje ödevim var … notionda bir page açıp yapılacakları belirlemek, ardından kanban board oluşturup detaylı bir şekilde başlayalım." | Project plan: Notion hub page, 64 task cards with acceptance criteria, risk list. | Card counts and section references checked against the brief (15 tools, 17 states, 13 deliverables, 8 actions). | _pending_ | — |
| 2026-11-17 | Claude Code (Claude Fable 5.2) | "llm kısmında weight space programming düşünebilir miyiz" | Assessment of weight-space programming as a side experiment, with sources (Takehi et al. blog post, two independent write-ups). | Claims taken from the fetched sources, not from memory. | _pending_ | EC-057 |
| 2026-11-17 | Claude Code (Claude Fable 5.2) | "projeyi sprintlere böl … bu gece ilk sprinti bitireceğiz planını hazırla" | 8-sprint schedule; Sprint 1 implementation plan (`docs/superpowers/plans/2026-11-17-sprint-1-temel-ve-ince-hat.md`). | Dependency order of cards checked against sprint order. | _pending_ | S1 |
| 2026-11-17 | Claude Code (Claude Fable 5.2) | "sprint 1'i gece vardiyası olarak düşün, ben yokum bu gece sen devam et, kendi aldığın kararları ayrı bir noktada not al" | Repository scaffold, settings module, tests (Task 1). Decisions recorded in `docs/decision-log.md`. | `uv run pytest -q` output recorded per task in the sprint ledger. | _pending_ | EC-003 |
| 2026-11-17 | Claude Code (Claude Fable 5.2) | Same night-shift instruction (Sprint 1 plan, Task 3). | System design document (`docs/superpowers/specs/2026-11-17-bist-harness-design.md`) and the 15 tool schemas (`tools/schemas.py`). Three design decisions were taken by the tool on the student's behalf (decision log K-005 to K-007). | Tool names checked against section 22 of the brief by test; action labels against section 17. | _pending — the design decisions need the student's own review_ | EC-004 |
| 2026-11-17 | Claude Code (Claude Fable 5.2) | Same instruction (Task 4). | Frozen 30-stock universe (`data/reference/universe.csv`) and loader. | 7 tests; all 30 Yahoo symbols returned data. | _pending_ | EC-010 |
| 2026-11-17 | Claude Code (Claude Fable 5.2) | Same instruction (Task 5). | Ollama client, bake-off questions (30 cases written by the tool), scoring and runner; laptop measurements of four open-source models. | Client and scoring covered by tests; results copied from the runner output into `docs/results/2026-11-17-model-bakeoff.md`. | _pending — the base-model choice is the student's_ | EC-005 |
| 2026-11-17 | Claude Code (Claude Fable 5.2) | Same instruction (Task 6). | Market-data cache, Bollinger reversal summary, numeric-hallucination check (including the `numbers_match` rule, decision K-008), MCP server with two tools, end-to-end runner. | Reversal summary equals the instructor's Scenario 3 functions on three synthetic series and two horizons; 113 tests pass; three live questions run on two models. | _pending — `numbers_match` was meant to be written by the student_ | EC-009 |
| 2026-11-17 | Claude Code (Claude Fable 5.2) | Same instruction ("sprint 1'i bitirirsen sprint 2 planını yap"). | Sprint 2 implementation plan, including proposed peer groups and event definitions. | Reference tickers and index symbols checked against Yahoo Finance on 2026-11-17. | _pending_ | S2 |
| 2026-11-17 | Claude Code (Claude Fable 5.2), fresh-context reviewer | Whole-branch code review of Sprint 1. | Review findings and the fixes made from them (see the sprint ledger and git history). | Each fix has a test that failed first. | _pending_ | S1 |

Open-source models run locally during development on 2026-11-17 (not cloud services):
`qwen3.5:4b`, `qwen3.5:2b`, `qwen3.5:0.8b`, `llama3.2:3b` through Ollama 0.40.16 on the
laptop, for the bake-off and the thin-slice check.
