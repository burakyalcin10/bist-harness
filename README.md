# bist-harness

CSE-481 Engineering Economics course project (Akdeniz University, Dr. Alper Özcan):
an integrated BIST 100 agentic financial analytics harness.

> **Educational use only. Not investment advice.** The system does not connect to a
> broker, place orders or manage money. Its outputs are research states such as
> `WATCH` or `ANALYSIS_UNSAFE`, never buy/sell recommendations.

## Design principle

The LLM reasons and explains. Python tools calculate. The harness controls.
Backtests verify. Evidence is logged. A human makes the final decision.
The model runs locally.

## Setup

```powershell
uv sync                 # creates .venv with Python 3.12 and all dependencies
uv run pytest -q        # offline test suite
```

## Model endpoint

The harness talks to an Ollama-compatible endpoint that you control. Nothing is sent
to a cloud AI provider.

```powershell
copy .env.example .env  # then edit; .env is never committed
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `BIST_LLM_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint (this machine or a private server) |
| `BIST_LLM_MODEL` | `qwen3.5:9b-q4_K_M` | Model tag served by that endpoint |
| `BIST_DATA_DIR` | `./data` | Root of reference data and the market-data cache |

## Layout

```
src/bist_harness/   package (tools, MCP server, LLM client, evaluation)
tests/              offline tests; live tests are marked `live`
data/reference/     frozen study universe (committed)
data/cache/         market-data snapshots (not committed)
reference/          place for the instructor's example scripts (not distributed)
docs/               design, plans, decision log, AI usage log, results
```

## Study universe

30 BIST 100 stocks from the project brief (section 5), frozen in
`data/reference/universe.csv` on 2026-11-17. Market data comes from Yahoo Finance
via `yfinance` with `auto_adjust=True`, as in the instructor's example scripts.
