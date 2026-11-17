# Backtest, discovery period — variants A and B

Run on 2026-11-17 with `run_backtest(strategy, [], "2020-01-01", "2024-12-31")`: all 30
universe stocks, data snapshot `20261117-0722`, corrections file `52e31e96`. Rules as
fixed in `docs/preregistration.md` **before** the first run: signal at the close of day
t, entry at the open of day t+1, exit at the close of day t+10, 0.15% cost on each side,
one trade per stock at a time, equal weight across open trades, cash earns nothing.

**The test period (2025-01-01 to 2026-11-13) has not been run.** See "Status of the test
period" below.

This file was regenerated after the Sprint 3 code review, which found two defects in
the first version of the numbers: the portfolio ran on the XU100 calendar, which lacks
five real sessions, and the "buy-and-hold" benchmark was a daily-rebalanced basket. Both
are fixed; the trades themselves did not change.

| Measure | A — technical | B — technical + sector |
| --- | --- | --- |
| Result id | `afba4b11a791` | `370def4a4d79` |
| Signal days | 1,974 | 402 |
| Trades | 903 | 241 |
| Signals ignored (stock already in a trade) | 1,060 | 159 |
| Signals without a full holding window | 11 | 2 |
| Win rate | 57.25% | 56.85% |
| Mean trade return after cost | 2.05% | 2.09% |
| Median trade return after cost | 1.26% | 1.12% |
| Portfolio cumulative return | 244.98% | 225.02% |
| CAGR | 28.31% | 26.78% |
| Sharpe (risk-free rate 0) | 0.99 | 0.98 |
| Maximum drawdown | −29.35% | −29.19% |
| Days with an open trade | 77.40% | 57.35% |
| Buy-and-hold of the same 30 stocks (bought once, equal money, never rebalanced) | 1,548.88% | 1,548.88% |
| XU100 | 747.96% | 747.96% |
| Peer groups, bought once and held | — | 1,613.10% |
| Flags | `UNDERPERFORMS_BUY_AND_HOLD`, `UNDERPERFORMS_XU100` | the same and `UNDERPERFORMS_SECTOR_PEERS` |

First version, for the record: portfolio 255.63% (A) and 224.42% (B); benchmark
1,804.85% (daily rebalanced).

By market regime on the signal day (XU100 against its 200-day average):

| Regime | A: trades | A: win rate | A: mean trade | B: trades | B: win rate | B: mean trade |
| --- | --- | --- | --- | --- | --- | --- |
| Uptrend | 621 | 60.55% | 2.42% | 157 | 58.60% | 2.13% |
| Downtrend | 126 | 56.35% | 2.66% | 41 | 56.10% | 3.02% |
| Undefined (first 200 bars of 2020) | 156 | 44.87% | 0.08% | 43 | 51.16% | 1.05% |

## Reading the result

1. **Both variants lose to simply holding the stocks, by a wide margin.** The period is
   one of high inflation: the 30 stocks rose about sixteen-and-a-half-fold in nominal
   terms and XU100 about eight-and-a-half-fold. A rule that is out of the market 23% to
   43% of the days and pays 0.3% per round trip cannot keep up with that. The mean trade
   return of about 2% over ten days is close to what holding the basket earned per ten
   days in this period (about 2.3% before cost), so **the trades show no edge over being
   invested**.
2. **The sector condition does not improve the trades.** B keeps one signal in five; win
   rate and mean trade return are the same as A's within noise.
3. **The weak spot is the first 200 bars**, which include the March 2020 crash: there
   the reversal entries had a win rate below one half.
4. These numbers are nominal. Returns in Turkish lira over 2020–2024 are dominated by
   inflation.

What this means for the system: a `TECHNICAL_REVERSAL_CANDIDATE` or
`POTENTIAL_CATCH_UP_CANDIDATE` label must be accompanied by the benchmark comparison,
and the quality gate should treat `UNDERPERFORMS_BUY_AND_HOLD` as a reason to hold the
label back or to weaken it.

## Status of the test period

Not run, on purpose. The Sprint 3 review showed that the statement source used for the
fundamental layer is not point-in-time (it restates earlier periods at a later price
level). Variants C to E and Scenario 4 read that layer, and the protocol allows the test
period to be run once. It will be run for all variants together after the fundamental
layer has been rebuilt from as-published figures (first task of Sprint 4).
