# Is the statement source point-in-time? A measurement (K-048)

Measured on 2026-11-17 for Sprint 4, Task 0. Question: can the fundamental layer be
rebuilt from as-published figures, and by which route?

- **Route (a):** read the figures from the KAP financial-report disclosure itself.
- **Route (b):** take the source value (İş Yatırım `MaliTablo`, snapshot `20261117-0722`) and
  divide it by a CPI ratio to undo the later restatement.

## Method

For 7 stocks and 2 periods (2024Q3, 2024Q4), plus TUPRS 2022Q4, 2023Q3 and 2025Q4, the
first financial-report disclosure of the period was downloaded from KAP (21 requests,
20 s apart). Each KAP page carries the statements as XBRL-tagged HTML: every row names its
taxonomy concept (`ifrs-full_Revenue`, `ifrs-full_Equity`, …), every value cell holds the
raw number, the column headers give the period ("Cari Dönem 01.01.2024 - 31.12.2024"), and
the page states the presentation unit (TL, thousand TL or million TL) and whether the
report is consolidated. The current-period column was compared with the source value of
the same item; the ratio was compared with CPI ratios from the snapshot's CPI index
(chained from monthly changes rounded to two decimals, so ratios agree to about 0.01%).

## Results

Ratio = source value / KAP as-published value.

| Stocks | Period | Flows (revenue, profit, operating cash flow) | Balance sheet (assets, equity) |
| --- | --- | --- | --- |
| TUPRS, ASELS, BIMAS | 2024Q3 | 1.33294 = CPI Sep 2025 / Sep 2024 | 1.00000 (as published) |
| TUPRS, ASELS, BIMAS | 2024Q4 | 1.30892 = CPI Dec 2025 / Dec 2024 | 1.30892 |
| MAVI (fiscal year ends in January) | 2024Q3 / 2024Q4 | 1.32867 / 1.30653: October and January ratios | 1.00000 / 1.30653 |
| THYAO (functional currency USD, no TMS 29) | 2024Q3 | 1.00000 | 1.00000 |
| THYAO | 2024Q4 | **1.30892** | **1.30892** |
| AKBNK (bank), TURSG (insurer) | 2024Q3, 2024Q4 | 1.00000 | 1.00000 (bank: TL + FX columns summed) |
| TUPRS | 2025Q4 | 1.24317 = CPI Sep 2026 / Dec 2025 | 1.24317 |
| TUPRS | 2023Q3 | revenue 1.78, net profit **0.67**, cash flow 1.78 | 1.00000 |
| TUPRS | 2022Q4 | 1.49 to 1.90 by item | 2.06 (assets), 2.67 (equity) |

What the source does, as far as these 23 stock-periods show:

1. **Interim periods (Q1–Q3), industrial layout:** income and cash-flow figures are the
   comparative column of the *following year's* report of the same quarter, i.e. restated
   to a price level twelve months later. Balance-sheet figures are as published.
2. **Year-end periods, industrial layout:** every figure is the as-published figure
   multiplied by a CPI ratio, computed by the source itself (the values are not whole
   thousands). The ratio runs to December of the next year, or, for the latest year end,
   to the end of the latest quarter (September 2026). It is applied even to THYAO, which
   does not apply inflation accounting, so the source's THYAO year ends are wrong.
3. **Banks and insurers** (layout `UFRS_K`): as published. They do not apply inflation
   accounting (BDDK and SEDDK decisions) and the source does not rescale them.
4. **2022Q4 and 2023 periods:** the following report is the first one under TMS 29, which
   restates each item from its own transaction dates. No single ratio undoes it; the
   ratios range from 0.67 to 2.67.

## What each route can recover

| | Route (a): KAP report | Route (b): CPI back-conversion |
| --- | --- | --- |
| 2024Q1 onward, TMS 29 companies | Exact | Possible, with a rule per layout, period type and download date (items 1–2 above); about 0.01% off because of the CPI index |
| Companies without TMS 29 (THYAO) | Exact | Only if the rule knows the company's accounting policy |
| 2022Q4, 2023Q1–Q3 | Exact | **Not possible** |
| Banks, insurer | Exact (needs the total column; three templates) | Already as published |
| Year-over-year change | Current and comparative column of the **same** report: both on one price level, so under TMS 29 the change is real growth | Needs two figures on one price level: rebuilt from (b)'s outputs plus a CPI step |
| Later downloads | Same figures forever | Ratios change with the download date (item 2) |

## Cost of route (a)

- One page per report: 479 periods in the snapshot, plus the second (solo or consolidated)
  report where a company files both (banks, insurer, some holdings): about 520 pages of
  about 5 MB (bank and insurer pages about 2.5 MB). At 20 s per request that is about
  three hours, resumable.
- A parser for three templates (industrial, bank with TL/FX/total columns, insurer); the
  unit (TL, thousand TL, million TL) and the consolidation flag are read from the page.
- The metric definitions move from the source's item codes to XBRL concept names.

## Side findings

- "55 periods with a later correction" in the coverage report are partly not corrections:
  AKBNK and TURSG file a consolidated and a solo report seconds apart, and the second one
  was counted as a correction. TURSG files the solo report first.
- MAVI's periods end in April, July, October and January; the layer maps them to calendar
  quarters, so its period-end dates and CPI ratios are one month off.
- KAP reports state the unit: THYAO reports in million TL, TURSG in TL, the others in
  thousand TL.

## After the rebuild (same day)

All 534 report pages were downloaded (`failed: []`) and the layer was built with
`uv run python -m bist_harness.data.fundamentals build-kap`: 30 stocks, 479 periods (MAVI
15, the rest 16), every period with a usable-from day and with revenue, net profit, total
assets, equity and paid-in capital; every stock with comparative columns. The consolidated
report was used everywhere except TRALT, which files a consolidated report for one of its
16 periods. The figures read in the measurement above come out of the layer unchanged
(TUPRS 2024Q4 revenue 810,385,588 and comparative 991,202,993 thousand TL; AKBNK 2024Q3
total assets 2,404,289,929 thousand TL, TL plus FX; THYAO in million TL; TURSG in TL; MAVI
2024Q4 from 2024-02-01 to 2025-01-31). Periods with a later correction fell from 55 to 7:
most of the 55 were the consolidated and solo reports a company files minutes apart.
Snapshot sealed afterwards: `layers_id` `21b3a428`.
