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
