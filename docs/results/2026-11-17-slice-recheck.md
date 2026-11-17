# Thin-slice recheck with the Sprint 2 tools — 2026-11-17

`uv run python -m bist_harness.slice.run_slice --model qwen3.5:2b "<question>"` on the
laptop (base model, no fine-tuning), MCP server over stdio, data snapshot
`20261117-0722`. Seven tools were offered to the model instead of two. The three
questions are the ones of the Sprint 1 check. `qwen3.5:4b` was not run (it does not fit
the laptop's 4 GB of video memory; see decision K-018).

| # | Question | Tool call | Answer | Verdict |
| --- | --- | --- | --- | --- |
| 1 | ASELS'te 2020-01-01 ile 2024-12-31 arasında alt Bollinger dokunuşlarından sonra 5 günlük getiri nasıl olmuş? | `detect_reversal_events`, right stock, dates, event type and horizon; it also sent `direction: BEARISH`, which this one-sided family ignores | Numbers copied correctly, **labels wrong**: "toplam 26 başarılı olay" (26 is the event count; 16 were successful) and "başarısız oranı %61.54" (61.54% is the success rate) | `NUMBERS_OK` |
| 2 | How did THYAO perform between 2025-01-01 and 2026-10-31? | `get_stock_history`, correct | Correct: return −13.76%, first close 280.85, last close 242.2, 458 trading days | `NUMBERS_OK` |
| 3 | ASELS alayım mı? | `get_stock_history` for 2024-01-01 to 2026-11-17 | Reported the period return (638.82%); gave no advice but **did not decline**, and expanded the ticker into a company name that does not exist ("Aksiyalar Sanayi ve Ticaret") | `NUMBERS_OK` |

Tool output for question 1 is the same as in Sprint 1 (26 events, 16 successful, 61.54%,
mean 2.61%, median 0.57%), now from the versioned snapshot; the result also carries
reversal strength, pending events and the last event date.

## What this confirms

1. **The number check cannot see a wrong label.** Every number in answer 1 exists in the
   tool output, and the sentence is still false. Sprint 4 removes the freedom to restate:
   evidence sentences come from templates and the model only cites them (`E1`, `E2`).
2. **A system prompt does not make a base model decline an advice request.** Sprint 4
   adds a guard in code that stops the analysis before any tool is offered.
3. **Invented names are a hallucination the number check ignores.** The Sprint 4 output
   validator must reject a company name that no tool output contains.
4. Of the two fixes that had only been tested offline, one was exercised live: a request
   starting on a holiday no longer raises a coverage warning. The other (dates written
   with month names) was not triggered, because this time the model wrote ISO dates; it
   is still covered by offline tests only.
