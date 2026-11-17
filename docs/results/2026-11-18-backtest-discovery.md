# Backtest, discovery period — variants A and B

Run on 2026-11-18 with `run_backtest(strategy, [], "2020-01-01", "2024-12-31")`: all 30
universe stocks, data snapshot `20261117-0722`, corrections file `52e31e96`. Rules as
fixed in `docs/preregistration.md` **before** this run: signal at the close of day t,
entry at the open of day t+1, exit at the close of day t+10, 0.15% cost on each side,
one trade per stock at a time, equal weight across open trades, cash earns nothing.

**The test period (2025-01-01 to 2026-11-13) has not been run.** It is run once, at the
end of Sprint 3, for all variants together.

| Measure | A — technical | B — technical + sector |
| --- | --- | --- |
| Result id | `9470339f5549` | `c4ee510b5b4c` |
| Signal days | 1,974 | 402 |
| Trades | 903 | 241 |
| Signals ignored (stock already in a trade) | 1,060 | 159 |
| Signals without a full holding window | 11 | 2 |
| Win rate | 57.25% | 56.85% |
| Mean trade return after cost | 2.05% | 2.09% |
| Median trade return after cost | 1.26% | 1.12% |
| Portfolio cumulative return | 255.63% | 224.42% |
| CAGR | 29.20% | 26.82% |
| Sharpe (risk-free rate 0) | 1.02 | 0.98 |
| Maximum drawdown | −29.35% | −29.19% |
| Days with an open trade | 77.48% | 57.45% |
| Buy-and-hold of the same 30 stocks | 1,804.85% | 1,804.85% |
| XU100 | 747.96% | 747.96% |
| Peer groups, equal weight | — | 1,829.08% |
| Flags | `UNDERPERFORMS_BUY_AND_HOLD`, `UNDERPERFORMS_XU100` | the same and `UNDERPERFORMS_SECTOR_PEERS` |

By market regime on the signal day (XU100 against its 200-day average):

| Regime | A: trades | A: win rate | A: mean trade | B: trades | B: win rate | B: mean trade |
| --- | --- | --- | --- | --- | --- | --- |
| Uptrend | 621 | 60.55% | 2.42% | 157 | 58.60% | 2.13% |
| Downtrend | 126 | 56.35% | 2.66% | 41 | 56.10% | 3.02% |
| Undefined (first 200 bars of 2020) | 156 | 44.87% | 0.08% | 43 | 51.16% | 1.05% |

## Reading the result

1. **Both variants lose to simply holding the stocks, by a wide margin.** The period is
   one of high inflation: the 30 stocks rose about nineteen-fold in nominal terms and
   XU100 about eight-and-a-half-fold. A rule that is out of the market 23% to 43% of the
   days and pays 0.3% per round trip cannot keep up with that. A mean trade return of
   about 2% over ten days is roughly what a randomly chosen ten-day holding earned in
   this market, so **the trades show no edge over being invested**.
2. **The sector condition does not improve the trades.** B keeps one signal in five; win
   rate and mean trade return are the same as A's within noise.
3. **The weak spot is the first 200 bars**, which include the March 2020 crash: there
   the reversal entries had a win rate below one half.
4. These numbers are nominal. Returns in Turkish lira over 2020–2024 are dominated by
   inflation; a comparison across periods needs real returns, which Sprint 3's macro
   layer (CPI) makes possible.

What this means for the system: a `TECHNICAL_REVERSAL_CANDIDATE` or
`POTENTIAL_CATCH_UP_CANDIDATE` label must be accompanied by the benchmark comparison,
and the quality gate should treat `UNDERPERFORMS_BUY_AND_HOLD` as a reason to hold the
label back or to weaken it. This is the kind of result the harness is meant to surface
instead of hiding.
