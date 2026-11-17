# Test period, the one pre-registered run

Run once on 2026-11-17 (decision K-049), after the fundamental layer was rebuilt from
as-published KAP reports (K-055). Definitions are those of `docs/preregistration.md`
section 3, with the corrections of sections 6 and 6.1 recorded before this run. Nothing
was tuned or re-run afterwards.

| Item | Value |
| --- | --- |
| Command | `uv run python -m bist_harness.backtest.study test` |
| Code | commit `beb5650` (detached checkout; the last Task 0 commit) |
| Data | snapshot `20261117-0722`, `layers_id` `21b3a428`, `snapshot verify` clean before the run |
| Period | 2025-01-01 to 2026-11-13 |
| Raw output | `runs/study-test-20261117-211858.json` (git-ignored; result ids below) |

## Strategy variants A to E

| Variant | Trades | Win rate % | Mean trade % | Cumulative % | CAGR % | Sharpe | Max DD % | Exposure % | Flags |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A technical | 485 | 49.28 | 0.56 | −30.51 | −17.80 | −0.56 | −47.33 | 94.87 | below buy-and-hold, below XU100 |
| B + sector | 108 | 46.30 | 0.61 | 8.46 | 4.47 | 0.30 | −35.02 | 71.58 | below buy-and-hold, XU100, peers |
| C + fundamentals | 34 | 44.12 | 1.00 | 15.17 | 7.90 | 0.45 | −28.48 | 36.54 | below buy-and-hold, XU100 |
| D + macro | 34 | 44.12 | 1.00 | 15.17 | 7.90 | 0.45 | −28.48 | 36.54 | below buy-and-hold, XU100 |
| E + context | 33 | 42.42 | 0.27 | −0.12 | −0.06 | 0.11 | −28.61 | 34.83 | below buy-and-hold, XU100, peers |

Benchmarks over the same days: equal-money buy-and-hold of the universe 35.33%, XU100
20.47%, equal-weight peer groups 12.40% (B to E). Sharpe uses a zero risk-free rate.
Result ids: A `36d29c98bdba`, B `3bd8e2822aa8`, C `24a8fe550f83`, D `6728349fc598`,
E `83809bbfc03b`.

- No variant beat holding the same stocks. Each added filter cut the trade count
  (485 → 108 → 34 → 33) and the drawdown; C's fundamental filter lifted the result
  from 8.46% to 15.17%, still below the index.
- D equals C: no C signal fell within 60 days of a policy-rate increase.
- E removed one trade (a `regulation_legal` disclosure) and lost 15 points: one trade.
  With 33–34 trades the C–E differences are not stable evidence.
- **Known defect in the output text:** C, D and E carry the warning
  `FUNDAMENTALS_NOT_POINT_IN_TIME` ("the statement source restates earlier periods…").
  The Sprint 3 code attaches it unconditionally; this run used the rebuilt as-published
  layer, so the warning text is outdated. The numbers are not affected. The warning is
  removed in Sprint 4 code after this run.

## Scenario 1 — sector laggards

| Period | Definition | Laggard days | Episodes | Hit rate % | Median catch-up (pp) | False positives % |
| --- | --- | --- | --- | --- | --- | --- |
| Discovery 2020–2024 | lag ≤ −5 pp | 4,089 | 461 | 51.28 | 0.21 | 48.72 |
| Test | lag ≤ −5 pp | 1,137 | 141 | 54.97 | 0.78 | 45.03 |
| Discovery | lag < 0 | 7,463 | 628 | 50.61 | 0.08 | 49.39 |
| Test | lag < 0 | 2,147 | 216 | 55.19 | 0.78 | 44.81 |

Outcome: the stock's next-10-day return minus its peers' median (stock excluded). A
laggard in a strong sector caught up a little more often than not in the test period,
but close to a coin flip in five years of discovery data; the median catch-up is under
one percentage point.

## Scenario 2 — weekday and multi-day patterns

Stocks passing at 5% in the discovery period, per pattern (30 stocks; chance alone:
about 1.5 before and 0.3 after the Bonferroni correction):

| Pattern | Before correction | After correction |
| --- | --- | --- |
| WEEKDAY_MEANS | 6 | 1 |
| MON_WEAK_FRI_STRONG | 2 | 0 |
| THREE_DOWN_TWO_UP | 6 | 0 |
| POST_LARGE_DOWN_REVERSION | 2 | 2 |
| END_OF_WEEK_CONTINUATION | 2 | 0 |

Three stock-pattern pairs were significant after the correction; two kept the same sign
in the test period and are **supported** under the protocol's rule:

| Stock | Pattern | Discovery (n, p Bonferroni, excess %) | Test (n, excess %) | Supported |
| --- | --- | --- | --- | --- |
| AKBNK | POST_LARGE_DOWN_REVERSION | 32, 0.0325, −2.04 | 11, −2.51 | yes |
| EKGYO | WEEKDAY_MEANS (Monday) | 1,250, 0.0325, +0.50 | 468, +0.33 | yes |
| GUBRF | POST_LARGE_DOWN_REVERSION | 29, 0.015, −3.79 | 14, +1.02 | no (sign changed) |

For AKBNK the "reversion" is the opposite: after a large drop the next days were weaker
than average. The test samples are small (11 and 14 events) and not significant on their
own; the protocol asks only for the same sign. Three passes after correction against
about 1.5 expected by chance across the five patterns is weak evidence. THYAO is marked
"not pre-registered" and is not among them.

## Scenario 3 — technical reversal events (5-day horizon)

| Family | Discovery events | Discovery success % | Test events | Test success % | Test mean % | Above 200-day avg. (n, %) | Below (n, %) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bollinger lower touch, bullish | 712 | 53.60 | 349 | 60.17 | 1.32 | 205, 58.05 | 144, 63.19 |
| Bollinger middle test, bullish | 1,839 | 55.09 | 689 | 48.98 | 0.28 | 533, 48.03 | 156, 52.26 |
| Bollinger middle test, bearish | 1,683 | 44.77 | 843 | 50.49 | 0.54 | 576, 50.69 | 267, 50.00 |
| Bollinger upper touch, bearish | 1,487 | 42.22 | 450 | 51.12 | −0.41 | 404, 50.25 | 46, 59.52 |
| RSI local trough, bullish | 1,753 | 54.09 | 927 | 59.23 | 1.18 | 544, 58.09 | 383, 60.92 |
| RSI local peak, bearish | 3,979 | 41.75 | 1,109 | 51.63 | −0.16 | 962, 50.83 | 147, 57.04 |
| Supertrend flip, bullish | 503 | 58.00 | 218 | 52.86 | 0.62 | 177, 50.85 | 41, 63.64 |
| Supertrend flip, bearish | 517 | 43.02 | 219 | 42.47 | 0.97 | 137, 47.45 | 82, 34.15 |
| KAMA turn, bullish | 2,426 | 53.95 | 1,032 | 51.18 | 0.86 | 747, 51.81 | 285, 49.45 |
| KAMA turn, bearish | 2,428 | 47.33 | 1,022 | 49.90 | 0.23 | 720, 50.42 | 302, 48.65 |
| Ichimoku breakout, bullish | 860 | 55.67 | 397 | 47.72 | 0.30 | 306, 49.02 | 91, 43.18 |
| Ichimoku breakout, bearish | 709 | 44.11 | 421 | 49.05 | 0.45 | 275, 49.09 | 146, 48.97 |
| Support/resistance touch, bullish | 2,907 | 55.26 | 1,597 | 49.53 | 0.22 | 1,059, 49.86 | 538, 48.85 |
| Support/resistance touch, bearish | 3,957 | 42.40 | 1,588 | 48.35 | 0.39 | 1,200, 47.83 | 388, 50.00 |

Success: a 5-day return above 0 for a bullish event, below 0 for a bearish one. Two
families held up out of sample — the lower Bollinger touch and the RSI trough, both
near 60% in the test period. Most others drifted to about 50%. Bearish families score
below 50% in the rising discovery market (prices mostly went up), so their success rate
measures the trend as much as the signal.

## Scenario 4 — price reaction to quarterly reports (descriptive)

239 reports became usable in the test period (5-day horizon complete for 228, 20-day for
210). Abnormal return = stock return minus the XU100 and minus the equal-weight peers,
from the close before the usable-from day.

| Fundamental trend | Reports | 5-day vs peers (pp) | 20-day vs index (pp) | 20-day vs peers (pp) |
| --- | --- | --- | --- | --- |
| Improving | 86 | +1.07 | +2.04 | +2.43 |
| Mixed | 55 | −1.38 | −0.46 | −2.29 |
| Deteriorating | 98 | −0.20 | −0.75 | −0.93 |

Improving quarters were followed by better relative returns than deteriorating ones,
in the direction one would expect. With at most eight reports per stock this is a
description, not a significance claim (protocol, Scenario 4).

## What this run does and does not show

- It is the single out-of-sample evaluation the protocol allowed; repeating it with other
  parameters would no longer be out of sample.
- Fundamentals entered the test-period strategies only after the layer was rebuilt from
  the figures published at the time (K-055); the old restated source would have used
  later price levels.
- No result here is a forecast or investment advice.
