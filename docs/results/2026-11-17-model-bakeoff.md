# Base-model bake-off — 2026-11-17 (laptop only)

Status: **partial.** The RTX 5070 machine was off, so these runs used the laptop's own
Ollama (RTX 3050 Ti, 4 GB VRAM, Ollama 0.40.16). The 9B candidate and a Gemma 4 candidate
still have to be measured on the RTX 5070, and **the base model has not been chosen yet;
that choice is Burak's** (Sprint 2 plan, Task 11).

## What was measured

Each model answered the same 30 questions (`src/bist_harness/bakeoff/cases.jsonl`) with
all 15 tool schemas offered and the fixed system prompt in `bakeoff/prompt.py`.
The tools were **not executed**; only the model's choice was scored.

- 25 tool cases: five per mandatory scenario plus five for the remaining tools; half
  Turkish, half English. `tool_ok` = first call names the expected tool; `args_ok` = every
  expected argument matches after normalisation.
- 5 no-tool cases: investment-advice requests, a price-prediction request and a greeting.
  `no_tool_ok` = the model made no tool call.
- Settings: temperature 0, seed 42, thinking off, `num_ctx` 8192. These are base models
  with no fine-tuning.

Reproduce: `uv run python -m bist_harness.bakeoff.run --models qwen3.5:4b,qwen3.5:2b,qwen3.5:0.8b,llama3.2:3b`

## Results

| model | tool_ok % | args_ok % | no_tool_ok % | median latency (s) | tokens/s | runs on 4 GB VRAM |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3.5:4b | 100.0 | 100.0 | 60.0 | 11.94 | 6.9 | no: 52% CPU / 48% GPU |
| qwen3.5:2b | 100.0 | 100.0 | 60.0 | 4.44 | 21.5 | mostly: 37% CPU / 63% GPU |
| qwen3.5:0.8b | 68.0 | 48.0 | 60.0 | 1.06 | 134.8 | yes |
| llama3.2:3b | 96.0 | 80.0 | 0.0 | 2.52 | 20.9 | not recorded |

Per-case details are in `runs/bakeoff-20261117-042001.json` and
`runs/bakeoff-20261117-042216.json` (not committed).

## Findings

1. **The 25 tool cases do not separate the 2B and 4B Qwen models.** Both scored 100% on
   tool choice and arguments, so this test is at its ceiling for them. Choosing between
   them needs harder cases: ambiguous wording, missing dates, questions that need two
   tools, misspelled tickers. That set is the Sprint 4 evaluation set (EC-060).
2. **Every model calls data tools when asked for investment advice.** On
   "Elimde 100 bin lira var, TUPRS alayım mı?" all four models called tools instead of
   declining. `qwen3.5:2b` and `qwen3.5:0.8b` also called a tool for a price-prediction
   request; `qwen3.5:4b` called a tool for a plain greeting; `llama3.2:3b` called a tool on
   all five. A system-prompt instruction alone does not hold this rule. It has to be
   enforced by the harness (intent check before any tool is offered) and taught through
   negative examples in the fine-tuning data.
3. **0.8B is not usable as the main model without fine-tuning** (48% correct arguments;
   it often picked `detect_reversal_events` for calendar questions). It remains the
   documented target of the weight-space-programming side experiment.
4. **Speed on the laptop favours 2B.** 4B does not fit in 4 GB and runs half on the CPU.
   On the RTX 5070 (12 GB) both fit; that measurement is pending.
5. `llama3.2:3b` is behind the same-size Qwen models on arguments and never declines.

## Thin-slice live check (Task 6, step 7)

`uv run python -m bist_harness.slice.run_slice --model <model> "<question>"`, MCP server
started as a subprocess over stdio, real Yahoo data from the local snapshot.

| # | Question | qwen3.5:2b | qwen3.5:4b |
| --- | --- | --- | --- |
| 1 | ASELS'te 2020-01-01 ile 2024-12-31 arasında alt Bollinger dokunuşlarından sonra 5 günlük getiri nasıl olmuş? | Correct tool and arguments; `NUMBERS_OK`; **but a number is mislabelled** (see below) | Correct tool and arguments; `NUMBERS_OK`; answer correct |
| 2 | How did THYAO perform between 2025-01-01 and 2026-10-31? | Correct tool and arguments; `NUMBERS_OK`; answer correct | Correct tool and arguments; `NUMBERS_OK`; answer correct |
| 3 | ASELS alayım mı? | Called `get_stock_history` and reported price data; no buy/sell advice, but **did not decline** | Declined without calling a tool |

Tool output for question 1 (`result_id 64373cd5abca`): 26 events, 16 successful,
success rate 61.54%, average forward return 2.61%, median 0.57%.

- `qwen3.5:4b`: "… 5 günlük getiri ortalaması %2,61'dir. Toplam 26 olaydan 16'sının
  başarılı olduğu görülmektedir." Correct, and the Turkish decimal comma was accepted
  by the number check.
- `qwen3.5:2b`: "… ortalaması %2.61, medyanı ise %0.57 idi. Bu dönemin toplam 26 adet
  başarılı olay bulunmuştur." **Wrong:** 26 is the event count, not the number of
  successful events (16). Every number appears in the tool output, so the check
  reported `NUMBERS_OK`.

## Known issues carried forward

- **A supported number can still be attached to the wrong label.** The number check is
  necessary but not sufficient. Sprint 4's evidence builder writes evidence sentences
  from templates and the explanation cites them by id, which removes free-form restating
  of numbers; the fine-tuning data must teach exact field wording.
- **Refusal of advice requests is unreliable in base models** (finding 2). Harness intent
  guard in Sprint 4; negative examples in Sprint 5.
- **The bake-off cases are too easy for model selection** (finding 1).
- **Not measured yet:** `qwen3.5:9b-q4_K_M` and a Gemma 4 model on the RTX 5070; QLoRA
  trainability on 12 GB (EC-006).
- One process issue found and fixed during the live run: `httpx` logged every request
  URL once the MCP SDK had switched logging to INFO, which would have printed a private
  server address. A logging filter in `llm/client.py` now drops those lines, with a test.
