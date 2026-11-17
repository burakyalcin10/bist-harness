# Pre-registration protocol

Written on 2026-11-17, before any backtest was run and before any event study on the
test period. The project brief (section 34, step 5) asks to "define event-based research
questions before looking at outcomes where possible". This file fixes the questions,
definitions and parameters. It is committed before the code that produces test-period
results; the commit order in the repository is the evidence.

## 1. Periods

| Period | Dates | Use |
| --- | --- | --- |
| Discovery | 2020-01-01 to 2024-12-31 | Definitions may be examined and compared here |
| Test | 2025-01-01 to 2026-11-13 | Each analysis is run once; nothing is tuned afterwards |

The test period is the one the instructor named (announcement 1). The last date is the
last stock bar in data snapshot `20261117-0722`. Fundamental analysis uses statements
from the 2024 year-end onward only (inflation-adjusted under TMS 29, announcement 1
item 4), so it lies almost entirely in the test period and has no discovery phase.

## 2. Results already seen when this was written

Honest list of every outcome number produced before this protocol existed.

| What | Period | Seen where |
| --- | --- | --- |
| ASELS lower-Bollinger reversal: 26 events, 61.54% success, mean +2.61% (5 days) | 2020–2024 (discovery) | Sprint 1 thin slice |
| **THYAO, all five calendar patterns: occurrences, conditional means, p-values** | **2020-01-01 to 2026-11-13 (includes the test period)** | Sprint 2 sanity check of the tool |
| THYAO price return 2025-01-01 to 2026-10-31 (−13.76%); ASELS price return 2024-01-01 to 2026-11-13 (+638.82%) | Test period | Thin-slice live check |
| Banking sector 20-day ranking as of 2026-11-13; Brokerage 60-day ranking as of 2024-09-30 | One date each | Sprint 2 sanity check |
| Data-quality report of the whole snapshot (no return statistics) | 2020–2026 | Sprint 2 |

Consequence: **calendar results for THYAO are not pre-registered.** They are reported,
marked as seen beforehand, and left out of any count of confirmed patterns. Nothing
else from the test period has been looked at: no backtest, no event summary for any
other stock, no fundamental reaction.

## 3. Research questions and fixed definitions

Event and pattern definitions are the ones implemented in Sprint 2 (`tools/events.py`,
`tools/calendar_patterns.py`, `tools/sector.py`); their text travels with every tool
output. They were written before any outcome on the test period was seen and are not
changed after this point.

### Scenario 1 — sector laggard / catch-up

- Question: when a sector is strong and one of its stocks lags, does the stock catch up
  afterwards?
- Laggard on day t: `sector_strong` is true (peer-group median 20-day return above the
  XU100 20-day return) **and** the stock's 20-day lag score is at or below −5 percentage
  points. Secondary definition: lag score below 0.
- Outcome: the stock's return minus the peer-group median return over the next 10
  trading days, measured from the close of day t.
- Reported: number of laggard days and of distinct episodes (a new episode starts after
  10 days without the condition), hit rate (outcome above 0), median catch-up size,
  false-positive rate (outcome at or below 0).

### Scenario 2 — weekday and multi-day patterns

- Question: do the five patterns of `tools/calendar_patterns.py` hold beyond chance and
  out of sample?
- For each of the 30 stocks, each pattern is tested on the discovery period with the
  permutation test (2,000 shuffles, seed 42) and the Bonferroni correction for five
  patterns.
- A pattern is called **supported for a stock** only if it is significant after the
  correction in the discovery period **and** its excess over the unconditional mean has
  the same sign in the test period. Anything else is reported as not supported.
- Across stocks: for each pattern, chance alone lets about 1.5 of the 30 stocks pass at
  the 5% level before the correction and about 0.3 after it. The report states how many
  stocks pass and compares that with these numbers.

### Scenario 3 — technical reversal events

- Question: what followed each of the nine event families historically?
- Primary horizon: 5 trading days. Also reported: 1, 3 and 10.
- Success: forward return above 0 for a bullish event, below 0 for a bearish one.
- Reported per family and direction: event count, bounce rate (success rate), mean and
  median forward return, reversal strength, sample-size warning, and the same on the
  test period. Regime breakdown: XU100 above or below its 200-day average on the event
  day.

### Scenario 4 — quarterly fundamentals and price reaction

- Question: were improving and deteriorating quarters followed by different price
  reactions?
- Event day: the first trading day whose close is after the KAP publication timestamp
  of the financial report (published before 18:00 on a trading day: that day; otherwise
  the next trading day).
- Reaction: return from the close before the event day to the close 1, 5 and 20 trading
  days after it; abnormal return is that minus the XU100 return and minus the
  equal-weight peer-group return over the same window.
- Grouping: `fundamental_trend` of the quarter ("Improving", "Mixed", "Deteriorating"),
  computed only from data public on the event day.
- This scenario has no discovery period. It is **descriptive**; with at most eight
  quarters per stock, no significance claim is made for a single stock.

### Strategy variants A to E (brief, section 29)

All parameters below are set a priori; none was chosen by looking at a backtest.

| Item | Value |
| --- | --- |
| Decision time | Close of day t |
| Execution | Open of day t+1 |
| Exit | Close of day t+10 (10 trading days after the signal) |
| Cost | 0.10% commission + 0.05% slippage, on entry and on exit |
| Position rule | One open trade per stock; a signal during an open trade is ignored |
| Portfolio | Equal weight across open trades; cash earns 0 |
| A — technical | `RSI_LOCAL_TROUGH` or `BOLLINGER_LOWER_TOUCH` on day t |
| B — A + sector | and 20-day lag score below 0 and `sector_strong` |
| C — B + fundamentals | and `fundamental_trend` of the latest public quarter is "Improving" |
| D — C + macro | and the TCMB policy rate was not raised in the last 60 calendar days |
| E — D + context | and no KAP disclosure tagged `regulation_legal` in the last 5 calendar days |
| Benchmarks | Equal-weight buy-and-hold of the same stocks; XU100; equal-weight peer groups |
| Sharpe | Daily returns, 252 days a year, risk-free rate 0 (stated with every result) |

Variants C to E need fundamentals and are therefore defined on the test period only.

- Every variant is reported; none is selected as "the best".
- A result with fewer than 5 trades is flagged `FEW_TRADES`; fewer than 20 carries the
  limited-sample warning.

## 4. What counts as evidence

- A historical statistic is evidence about the past. No output of this system is a
  forecast or investment advice.
- A `*_CANDIDATE` label needs the corresponding evidence in the committed evidence set
  and a backtest that ran; otherwise the label is not available to the agent.

## 5. Deviations

Any change to a definition or parameter after this file is committed is recorded in
`docs/decision-log.md` with the date and the reason, and the report shows the result
both before and after the change. A change made after seeing a test-period result is
marked as such.

## 6. Corrections made before any test-period run

Recorded on 2026-11-17 after an independent code review of Sprint 3. No test-period
backtest and no Scenario 4 study had been run when these were made; the list exists so
that the protocol and the code say the same thing.

| What | Before | Now | Why |
| --- | --- | --- | --- |
| Date of this protocol | "2026-11-17" | 2026-11-17 | The files were dated a day ahead by mistake; the system clock and the commits say 2026-11-17 |
| Buy-and-hold benchmark | Implemented as a daily-rebalanced equal-weight basket | Equal money in each stock, bought once, never rebalanced | "Buy-and-hold" must mean holding |
| Peer-group benchmark | Listed for every variant | Reported for variants B to E; variant A has no sector condition and reports none | Matches the code |
| Period of the fundamental data | "statements from the 2024 year-end onward only" | Statements are loaded from 2022Q4, because year-over-year changes and twelve-month sums need the year before; variants C to E trade from 2025-01-01, at first on 2024Q3 statements | States what the code does |
| Topic rules of the disclosure layer | Fixed before the download | Three keyword rules were corrected after reading real subject lines (articles of association, warrant notices, a Turkish spelling variant), and two more after the review (exports, investor notices). The `regulation_legal` set that variant E reads did not change (36 disclosures) | Tags other than `regulation_legal` are context only |
| Fundamental data "public on the event day" | Assumed | **Not true of the source.** It replaces a period's figures with the restated comparative of the following year's report. Real growth and valuation ratios are withheld; the fundamental trend of variants C to E and of Scenario 4 is not exactly what was computable on the day | Found by the review |

Consequence: the test period is **not** run until the fundamental layer has been rebuilt
from as-published figures. It will then be run once, for all variants and for Scenario 4
together, with the definitions of section 3 unchanged.
