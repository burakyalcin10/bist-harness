# Data dictionary

Every feature the system computes and every field a tool returns. A test
(`tests/test_data_dictionary.py`) fails when an indicator column or a tool output field is
missing from this file.

**"Known when"** is the earliest moment a value may be used without looking ahead. "Close
of t" means the value of trading day t is computed from data up to and including t and may
be used for decisions made after that day's close. Tools enforce this by cutting every
series at the requested `end` or `as_of` before computing anything.

Prices are Yahoo Finance daily bars with `auto_adjust=True`, read from a versioned
snapshot (`data/snapshots/<snapshot_id>/`). One documented correction is applied on read
(`data/reference/price_adjustments.csv`). Percentages and prices in tool outputs are
rounded to two decimals.

## 1. Market layer — raw columns

| Name | Definition | Unit | Source | Known when | Produced by |
| --- | --- | --- | --- | --- | --- |
| `Open`, `High`, `Low`, `Close` | Daily bar, adjusted for splits and dividends | TRY | Yahoo Finance | Close of t | `data.snapshot.load_history` |
| `Volume` | Shares traded that day; 0 where the source has no value | shares | Yahoo Finance | Close of t | `data.snapshot.load_history` |

## 2. Technical layer — indicator columns

All are produced by `tools.indicators`; the function is `add_<name>` and
`add_all_indicators` applies every one with default parameters. Formulas follow the
instructor's Scenario 3 script unless noted.

| Name | Definition and calculation | Unit | Known when |
| --- | --- | --- | --- |
| `SMA_20`, `SMA_50` | Simple mean of the last 20 / 50 closes | TRY | Close of t |
| `EMA_20` | Exponential mean of closes, span 20, `adjust=False` | TRY | Close of t |
| `MACD` | EMA(12) minus EMA(26) of the close | TRY | Close of t |
| `MACD_Signal` | EMA(9) of `MACD` | TRY | Close of t |
| `MACD_Hist` | `MACD` minus `MACD_Signal` | TRY | Close of t |
| `BB_Middle` | 20-day mean of the close | TRY | Close of t |
| `BB_Upper`, `BB_Lower` | `BB_Middle` plus / minus 2 sample standard deviations of the last 20 closes | TRY | Close of t |
| `RSI` | Wilder RSI, period 14: 100 − 100 / (1 + average gain / average loss), averages smoothed with alpha 1/14 | 0–100 | Close of t |
| `KAMA` | Kaufman adaptive moving average, efficiency ratio over 10 days, fast 2, slow 30 | TRY | Close of t |
| `KAMA_Slope` | `KAMA` today minus `KAMA` yesterday | TRY per day | Close of t |
| `ATR` | 10-day simple mean of the true range | TRY | Close of t |
| `Supertrend` | Trailing band: (High+Low)/2 ± 3 × `ATR`, ratcheted; the lower band while bullish, the upper band while bearish. Starts on the first day with an `ATR` (the script's version never starts) | TRY | Close of t |
| `Supertrend_Direction` | 1 bullish, −1 bearish, 0 not defined yet | — | Close of t |
| `Supertrend_Bullish_Flip` | Direction was −1 yesterday and is 1 today | bool | Close of t |
| `Tenkan` | (9-day high + 9-day low) / 2 | TRY | Close of t |
| `Kijun` | (26-day high + 26-day low) / 2 | TRY | Close of t |
| `Senkou_A` | (`Tenkan` + `Kijun`) / 2, shifted 26 days forward: the value on day t was computed on day t−26 | TRY | Close of t−26 |
| `Senkou_B` | (52-day high + 52-day low) / 2, shifted 26 days forward | TRY | Close of t−26 |
| `Cloud_Top`, `Cloud_Bottom` | Larger / smaller of `Senkou_A` and `Senkou_B` on day t | TRY | Close of t−26 |
| `Ichimoku_Bullish_Breakout` | Close was at or below `Cloud_Top` yesterday and is above it today | bool | Close of t |
| `Volume_MA` | 20-day mean of `Volume` | shares | Close of t |
| `Volume_Rise` | `Volume` above `Volume_MA` | bool | Close of t |

## 3. Fields common to tool outputs

| Name | Definition |
| --- | --- |
| `ticker` | Universe stock the result is about (upper case, no `.IS`) |
| `index` | Benchmark index code (`get_index_history`): XU100, XU030, XBANK or XUSIN |
| `start`, `end` | Requested period, both inclusive |
| `as_of` | Analysis date; nothing after it is used. In `calculate_indicators` it is the date of the last bar used |
| `snapshot_id` | Identifier of the market-data snapshot the tool read |
| `adjustments_id` | Short hash of `data/reference/price_adjustments.csv`, the corrections applied when a series is read; a change to that file changes every `result_id` |
| `data_source` | Where the prices come from |
| `data_first_date`, `data_last_date` | First and last bar the snapshot holds for the symbol |
| `coverage_warning` | Text when the requested period reaches more than 7 days beyond the data; otherwise null |
| `result_id` | First 12 hex digits of SHA-256 over tool name, arguments and output; identical input and data give an identical id |
| `definition`, `method` | Plain-language definition of what was measured; travels with the numbers |
| `sample_warning` | "Very small sample size" below 5 occurrences, "Limited sample size" below 20, otherwise null (instructor thresholds) |
| `warnings` | List of data problems that changed the result (members left out and why) |
| `error`, `code`, `message` | A failed call returns only `error` with a `code` (`UNKNOWN_TICKER`, `UNKNOWN_INDEX`, `UNKNOWN_SECTOR`, `INVALID_DATE`, `INVALID_DATE_RANGE`, `FUTURE_DATE`, `INVALID_ARGUMENT`, `DATA_UNAVAILABLE`) and a `message` |

## 4. `get_stock_history`, `get_index_history`

| Name | Definition | Unit |
| --- | --- | --- |
| `rows` | Trading days in the period | days |
| `first_date`, `last_date` | First and last trading day in the period | date |
| `first_close`, `last_close` | Close on those days | TRY / index points |
| `period_return_pct` | `last_close` / `first_close` − 1 | % |

## 5. `calculate_indicators` — values of the last day and state labels

Produced by `tools.indicators.indicator_state`. A value that cannot be computed yet is null: RSI needs 15 bars, EMA 20, MACD 35, the
Ichimoku cloud 78 (both spans), SMA its window.

| Name | Definition |
| --- | --- |
| `indicators` | Indicator groups returned |
| `close` | Close of the `as_of` day |
| `sma_20`, `sma_50`, `ema_20` | Columns `SMA_20`, `SMA_50`, `EMA_20` |
| `close_vs_sma_20` | "Above" or "Below" |
| `macd`, `macd_signal`, `macd_hist` | Columns `MACD`, `MACD_Signal`, `MACD_Hist` |
| `macd_state` | "Bullish" when `macd` is above `macd_signal`, else "Bearish" |
| `bb_upper`, `bb_middle`, `bb_lower` | Bollinger columns |
| `bollinger_position` | "Above Upper", "Upper Half", "Lower Half" or "Below Lower" |
| `rsi` | Column `RSI` |
| `rsi_state` | "Local Low": yesterday's RSI below both neighbours and below 40. "Local High": above both and above 60. Otherwise "Neutral" |
| `kama`, `kama_slope` | Columns `KAMA`, `KAMA_Slope` |
| `kama_slope_state` | "Flattening" when the absolute slope is below 0.05% of the close, else "Rising" or "Falling" |
| `atr` | Column `ATR` |
| `atr_pct` | `atr` as a percentage of the close |
| `supertrend` | Column `Supertrend` |
| `supertrend_state` | "Bullish" or "Bearish" |
| `tenkan`, `kijun`, `cloud_top`, `cloud_bottom` | Ichimoku columns |
| `ichimoku_state` | "Above Cloud", "In Cloud" or "Below Cloud": the close against the cloud of the same day |
| `volume_ratio` | `Volume` / `Volume_MA` |
| `volume_regime` | "High" above 1.5, "Low" below 0.5, otherwise "Normal" |

## 6. `find_support_resistance`

Produced by `tools.support_resistance`. A pivot is the extreme of an 11-day centred
window, so it is **known 5 trading days after it happens**; only known pivots are used.

| Name | Definition |
| --- | --- |
| `tolerance` | Relative distance within which pivots form one level (default 0.015) |
| `last_close` | Close of the last day of the period |
| `levels_found` | Number of levels found in the period |
| `levels` | The 6 strongest of them, strongest first |
| `level` | Mean price of the pivots in the level |
| `kind` | "support" below `last_close`, "resistance" above |
| `touches` | Pivots in the level |
| `recent_touches` | Pivots in the last 60 trading days |
| `high_volume_reactions` | Pivots on a day with volume above 1.5 × its 20-day mean |
| `last_touch_date` | Date of the latest pivot in the level |
| `strength` | `touches` + 1.5 × `recent_touches` + 1.2 × `high_volume_reactions` + one point per 5% of average move away from the level in the 5 days after each touch (at most 3 points) |
| `nearest_support`, `nearest_resistance` | Closest level below / above `last_close` among **all** levels found (it may be a weak one that is not in `levels`), or null |

## 7. `detect_reversal_events`

Produced by `tools.events`. An event is decided at the close of day t. The forward
return runs from that close to the close `forward_days` trading days later.

| Name | Definition | Unit |
| --- | --- | --- |
| `event_type` | One of nine families (see `definition` in the output) | — |
| `direction` | "BULLISH" or "BEARISH"; the side the event really has | — |
| `forward_days` | Horizon of the forward return: 1, 3, 5 or 10 | days |
| `event_count` | Events in the period that have a full forward window | count |
| `pending_events` | Events in the period too recent to have a full forward window; not in the statistics | count |
| `last_event_date` | Date of the latest event in the period, pending ones included | date |
| `successful_events` | Events whose forward return is above 0 (bullish) or below 0 (bearish) | count |
| `success_rate_pct` | `successful_events` / `event_count` | % |
| `average_forward_return_pct`, `median_forward_return_pct` | Mean and median forward return | % |
| `average_reversal_strength_pct`, `median_reversal_strength_pct` | Best move in the event's direction within the forward window: highest high (bullish) or lowest low (bearish) against the event close | % |
| `continuation_count` | `BOLLINGER_MIDDLE_TEST` only: events after which the earlier trend continued | count |
| `rejection_count` | `BOLLINGER_MIDDLE_TEST`: events after which it did not. `ICHIMOKU_BREAKOUT`: breakouts followed by a close back at or inside the cloud within the forward window | count |

Per-event records (`tools.events.event_records`, stored in the `events` table) add
`rsi_state`, `supertrend_state`, `kama_slope`, `ichimoku_state` and `volume_regime` as
known at the event close, and `forward_1d_return_pct` … `forward_10d_return_pct`.

## 8. Sector layer — `rank_sector_relative_strength`

Produced by `tools.sector`. Peer groups are in `data/reference/peer_groups.csv`.

| Name | Definition | Unit |
| --- | --- | --- |
| `sector` | Peer group name | — |
| `horizon_days` | Look-back window: 5, 10, 20 or 60 | trading days |
| `effective_date` | Last trading day on or before `as_of` that the returns end on | date |
| `benchmark` | Index used for comparison (XU100) | — |
| `members` | Up to 12 rows, best return first | — |
| `role` | "universe" (study stock) or "reference" (used for the median only) | — |
| `return_pct` | Close on `effective_date` against the close `horizon_days` trading days earlier | % |
| `sector_median_return_pct` | Median `return_pct` of the members with usable data | % |
| `lag_score_pct` | `return_pct` minus `sector_median_return_pct`; negative means lagging. Null when fewer than 3 members have data | % points |
| `rank` | 1 is the best return in the group | — |
| `benchmark_return_pct` | Same return for the benchmark | % |
| `sector_strong` | True when the sector median is above the benchmark return; null when it cannot be judged | bool |
| `leaders`, `laggards` | Universe stocks with a positive / negative lag score; empty when the group has fewer than 3 members with data | — |

## 9. Calendar layer — `test_weekday_pattern`

Produced by `tools.calendar_patterns`. A condition reads only days before the outcome it
is measured against.

| Name | Definition | Unit |
| --- | --- | --- |
| `pattern` | One of five patterns (see `definition` in the output) | — |
| `occurrences` | Times the condition occurred; for `WEEKDAY_MEANS` the number of daily returns | count |
| `conditional_mean_return_pct`, `conditional_median_return_pct` | Outcome when the condition occurred | % |
| `positive_rate_pct` | Share of those outcomes above 0; per weekday in `weekdays` | % |
| `unconditional_mean_return_pct` | Mean outcome over all units, condition or not | % |
| `transaction_cost_pct` | Cost charged once per occurrence (0.10) | % |
| `mean_after_cost_pct` | Conditional mean minus the cost; for `WEEKDAY_MEANS` the best weekday's mean minus the cost | % |
| `train`, `test` | The same summary on the first 70% and the last 30% of the period | — |
| `p_value` | Permutation test, 2,000 shuffles, seed 42, two-sided around the shuffles' own mean. Condition patterns use a studentized (Welch) statistic, so that volatile days selected by the condition do not look significant by themselves; null with fewer than 3 occurrences | 0–1 |
| `patterns_in_family` | Patterns tested together (5) | count |
| `p_value_bonferroni` | `p_value` × `patterns_in_family`, capped at 1 | 0–1 |
| `interpretation_flags` | `NOT_SIGNIFICANT` (Bonferroni p at or above 0.05 or no p-value), `UNSTABLE_OUT_OF_SAMPLE` (the edge changes sign between train and test, or one part has no occurrence; the edge is the conditional mean minus the unconditional one, or the signed mean for the direction pattern), `NEGATIVE_AFTER_COST` | — |
| `complete_weeks`, `incomplete_weeks_skipped` | Weeks with all five trading days, and weeks left out because a day is missing | count |
| `instructor_full_pattern_count` | `THREE_DOWN_TWO_UP` only: weeks that also had a positive Thursday and Friday, as counted by the instructor's script | count |
| `weekdays` | `WEEKDAY_MEANS` only: one row per `weekday` with `observations`, `average_return_pct`, `median_return_pct`, `positive_rate_pct` | — |
| `best_day`, `worst_day`, `spread_pct` | `WEEKDAY_MEANS` only: weekdays with the highest and lowest mean return and the gap between them | — / % |

## 10. Backtest layer — `run_backtest`

Produced by `backtest/engine.py`, `backtest/strategies.py` and `backtest/runner.py`. The
rules are fixed in `docs/preregistration.md`. A signal is decided at the close of day t
and filled at the **open of day t+1**; nothing is filled at the price of the bar that
produced the signal.

| Name | Definition | Unit |
| --- | --- | --- |
| `strategy` | Variant: `A_TECHNICAL` … `E_FULL_CONTEXTUAL` | — |
| `universe` | Stocks the variant was run on | — |
| `rule`, `execution` | Entry rule of the variant and the timing rules, in words | — |
| `holding_days` | Trading days from the signal to the exit close (10) | days |
| `cost_per_side_pct` | Commission plus slippage, charged on entry and on exit (0.15) | % |
| `signals` | Signal days in the period, over all stocks | count |
| `trades` | Signals that became a trade | count |
| `skipped_overlapping` | Signals ignored because the stock already had an open trade | count |
| `skipped_incomplete` | Signals without a full holding window in the data | count |
| `win_rate_pct` | Share of trades with a return above 0 after cost | % |
| `average_trade_return_pct`, `median_trade_return_pct` | Return per trade after cost | % |
| `cumulative_return_pct` | Compound return of the portfolio over the period (equal weight across open trades, 0 while none is open) | % |
| `cagr_pct` | `cumulative_return_pct` annualised with 252 trading days | % a year |
| `sharpe` | Mean daily portfolio return over its standard deviation, times √252; risk-free rate 0; null without variation | ratio |
| `max_drawdown_pct` | Deepest fall of the portfolio value below its earlier peak (0 or negative) | % |
| `exposure_pct` | Share of days with at least one open trade | % |
| `benchmark_buy_and_hold_return_pct` | Compound return of holding the same stocks with equal weight, rebalanced daily | % |
| `benchmark_xu100_return_pct` | Compound return of XU100 over the period | % |
| `benchmark_sector_peers_return_pct` | Variants B to E: compound return of the stocks' peer groups, equal weight | % |
| `excess_vs_buy_and_hold_pct`, `excess_vs_xu100_pct`, `excess_vs_sector_peers_pct` | `cumulative_return_pct` minus that benchmark | % points |
| `by_period` | Trades, win rate and mean trade return for signals in the `discovery` and in the `test` period | — |
| `by_regime` | The same for signals on days when XU100 closed above (`Uptrend`) or below (`Downtrend`) its 200-day average; `Undefined` before 200 closes exist | — |
| `flags` | `FEW_TRADES` (fewer than 5), `NEGATIVE_AFTER_COST` (mean trade return at or below 0), `UNDERPERFORMS_<BENCHMARK>` | — |
| `trade_sample` | The 12 latest trades: `signal_date`, `entry_date`, `exit_date`, `entry_price`, `exit_price`, `return_pct` | — |

## 11. Macro layer — `get_macro_context`

Produced by `data/macro.py` and `tools/macro.py`. Sources and publication rules are in
`docs/data_sources.md`. A value counts from the day it became public.

| Name | Definition | Unit | Known when |
| --- | --- | --- | --- |
| `usdtry_start`, `usdtry_end`, `eurtry_start`, `eurtry_end` | Exchange rate on the first and last day of the period with data | TRY | Close of that day |
| `usdtry_change_pct`, `eurtry_change_pct` | End against start | % | Close of the last day |
| `policy_rate_start`, `policy_rate_end` | TCMB one-week repo rate in effect on the first and last day | % a year | Decision date |
| `policy_rate_change_pp` | End minus start | % points | Decision date |
| `policy_rate_changes` | Decisions that changed the rate inside the period | count | Decision date |
| `last_policy_decision_date` | Date of the decision in effect at the end | date | — |
| `fed_target_lower_start`, `fed_target_upper_start`, `fed_target_lower_end`, `fed_target_upper_end` | Federal funds target range in effect on the first and last day | % a year | Decision date |
| `fed_changes` | Changes of the target range inside the period | count | Decision date |
| `cpi_period` | Month of the latest CPI figure **published** by the end of the period | YYYY-MM | — |
| `cpi_annual_pct`, `cpi_monthly_pct` | That month's consumer-price change against a year and a month earlier | % | Release day |
| `cpi_published` | Release day of that figure: the 3rd of the next month or the next working day | date | — |

## 12. Fundamental layer — `get_fundamental_metrics`, `calculate_fundamental_change`

Produced by `data/fundamentals.py` and `tools/fundamentals.py`. Statement values are
cumulative within the fiscal year. Amounts are in million TRY. **Known when:** a
reporting period is used from its `known_from` day, the first trading day whose close
follows the KAP publication (before 18:00 on a trading day: that day; otherwise the next
trading day). A ratio whose base is missing, zero or negative is null.

| Name | Definition | Unit |
| --- | --- | --- |
| `period`, `period_end` | Latest reporting period public on `as_of` (for example `2025Q3`) and its last day | — |
| `published_at` | KAP timestamp of the first financial-report disclosure of that period | timestamp |
| `known_from` | First trading day on which the period may be used | date |
| `financial_group` | `industrial`, `bank` or `insurance`: which statement layout applies | — |
| `revenue_meaning` | What `revenue_mn` is for that group: net sales, net interest income or gross written premiums | — |
| `revenue_mn`, `net_profit_mn`, `operating_cash_flow_mn` | Cumulative value of the period | mn TRY |
| `ebitda_mn` | Operating profit plus depreciation and amortisation, cumulative | mn TRY |
| `total_assets_mn`, `equity_mn` | Balance at the period end | mn TRY |
| `net_debt_mn` | Short-term plus long-term financial debt minus cash and short-term financial investments | mn TRY |
| `revenue_yoy_pct`, `ebitda_yoy_pct`, `net_profit_yoy_pct` | Cumulative value against the same period a year earlier, nominal; null when the earlier value is not positive | % |
| `revenue_real_yoy_pct`, `ebitda_real_yoy_pct`, `net_profit_real_yoy_pct` | The same after bringing the earlier value to the later period's price level with the CPI index | % |
| `ebitda_margin_pct`, `net_margin_pct` | EBITDA and net profit over revenue, cumulative | % |
| `roe_pct` | Last-twelve-months net profit of the parent over the parent's equity at the period end | % |
| `roa_pct` | Last-twelve-months net profit over total assets at the period end | % |
| `net_debt_to_ebitda` | `net_debt_mn` over last-twelve-months EBITDA | ratio |
| `debt_to_equity` | Financial debt over equity | ratio |
| `current_ratio` | Current assets over short-term liabilities | ratio |
| `quick_ratio` | Current assets minus inventories, over short-term liabilities | ratio |
| `cash_conversion` | Operating cash flow over net profit, cumulative | ratio |
| `market_cap_mn` | Close on `as_of` times the share count of the period (paid-in capital, 1 TRY nominal) | mn TRY |
| `pe` | `market_cap_mn` over last-twelve-months net profit of the parent | ratio |
| `pb` | `market_cap_mn` over the parent's equity | ratio |
| `ev_ebitda` | `market_cap_mn` plus `net_debt_mn`, over last-twelve-months EBITDA | ratio |
| `valuation_note` | Why the valuation ratios are null: `SHARE_COUNT_CHANGED_AFTER_THE_PERIOD` (prices in the snapshot assume the later share count) or `NO_PRICE_OR_SHARE_COUNT` | — |
| `not_applicable` | Fields that do not exist for a bank or an insurer (EBITDA, net debt, liquidity ratios, cash flow) | — |
| `periods` | `calculate_fundamental_change`: number of quarters requested (1 to 8) | count |
| `compared_with` | Period a year before `period`, used for the changes below | — |
| `quarters` | One row per public quarter, latest first | — |
| `revenue_q_mn`, `ebitda_q_mn`, `net_profit_q_mn` | The quarter's own value: cumulative minus the previous cumulative | mn TRY |
| `ebitda_margin_q_pct`, `net_margin_q_pct` | Margins of the quarter alone | % |
| `revenue_qoq_pct` | Quarter's revenue against the previous quarter | % |
| `revenue_q_yoy_pct`, `net_profit_q_yoy_pct` | Quarter's value against the same quarter a year earlier, nominal | % |
| `ebitda_margin_change_pp`, `net_margin_change_pp`, `roe_change_pp` | Latest period minus a year earlier | % points |
| `net_debt_to_ebitda_change`, `current_ratio_change` | Latest period minus a year earlier | ratio |
| `improvement_flags` | Checks that are positive against a year earlier: `REVENUE_UP`, `PROFIT_UP` (real growth when CPI is available), `MARGIN_UP`, `RETURN_ON_EQUITY_UP`, and for industrial companies `LEVERAGE_DOWN`, `CASH_FLOW_UP` | — |
| `fundamental_trend` | `Improving` when at least two thirds of the applicable checks are positive, `Deteriorating` when at most one third, otherwise `Mixed`; null with fewer than three applicable checks | — |

Limits: values are those the source holds today (a later restatement of a period is not
tracked); under inflation accounting each period is stated at its own price level, so a
quarter's own value (a difference of two cumulative values) is approximate; statements
before the 2023 year end are not inflation-adjusted (`COMPARATIVE_BEFORE_TMS29`).

## 13. Layers not built yet

| Layer (brief, section 10) | Planned content | Sprint |
| --- | --- | --- |
| News and events | Timestamped disclosure and news metadata | 3 |
| Speech | Topics, claims and stance from approved public videos | 7 |
