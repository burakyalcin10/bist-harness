# Data sources

Announcement 1 (item 2) allows any reliable, legally accessible source as long as the
source, the date range, the adjustments and the handling of missing data are stated.
This file is that statement. Everything below is stored inside the data snapshot, so an
analysis can be repeated without the network; tools never download.

Active snapshot: `20261117-0722`.

## 1. Prices and indices

| Item | Value |
| --- | --- |
| Source | Yahoo Finance through `yfinance`, `auto_adjust=True` |
| Range | 2020-01-02 to 2026-11-13 (stocks), 2026-11-16 (indices) |
| Symbols | 30 universe stocks, 54 reference stocks, XU100, XU030, XBANK, XUSIN |
| Fetched | 2026-11-17 |
| Corrections | `data/reference/price_adjustments.csv`: CCOLA 11-for-1 bonus issue of 2024-08-01, which the source did not apply. Applied when a series is read; its hash (`adjustments_id`) is part of every result |
| Missing data | No interpolation. Days without a bar stay absent. Zero-volume days are kept and reported by the quality check |
| Known issues | `docs/results/2026-11-18-data-quality.md`: price jumps in five reference stocks (excluded from sector medians when inside the window), SASA volume missing on 155 days |

## 2. Macro series

Built with `uv run python -m bist_harness.data.macro build` on 2026-11-18 into
`data/snapshots/20261117-0722/macro/` (with its own `manifest.json`: sources, row
counts, hashes).

| Series | Source | Rows | Range | Aligned by |
| --- | --- | --- | --- | --- |
| USD/TRY, EUR/TRY | Yahoo Finance daily close (`USDTRY=X`, `EURTRY=X`) | 1,790 | 2020-01-01 to 2026-11-17 | The day itself |
| TCMB policy rate | TCMB, "1 Hafta Repo" decision table (lending rate) | 58 | 2010-05-20 to 2026-10-23 | Decision date |
| Fed funds target range | Federal Reserve Board, "Open Market Operations" page | 60 | 2003-06-25 to 2026-09-17 | Date given on the page |
| CPI, annual and monthly change | TCMB, "Tüketici Fiyatları" table (TÜİK figures) | 262 | 2005-01 to 2026-10 | Release day: the 3rd of the following month, or the next working day if that is a weekend |

Why not EVDS: the TCMB data service needs a personal API key. The exchange rates were
therefore taken from Yahoo Finance and compared with the TCMB indicative rates
(`tcmb.gov.tr/kurlar`) on four days:

| Day | TCMB USD buying / selling | Yahoo close | TCMB EUR buying / selling | Yahoo close |
| --- | --- | --- | --- | --- |
| 2021-06-15 | 8.5474 / 8.5628 | 8.4558 | 10.3646 / 10.3833 | 10.2499 |
| 2023-09-01 | 26.6783 / 26.7264 | 26.6879 | 28.9377 / 28.9899 | 28.8849 |
| 2025-03-14 | 36.5350 / 36.6008 | 36.6796 | 39.6843 / 39.7558 | 39.8131 |
| 2026-10-15 | 49.3315 / 49.4204 | 49.4052 | 55.3113 / 55.4110 | 55.3427 |

The two agree within about 1%. They are not the same number: the TCMB rate is fixed at
15:30, the Yahoo close is the end of the trading day. The tool reports changes over a
period, for which this difference is small; the report should name Yahoo as the source.

Assumptions to keep in mind:

- **CPI release day is a rule, not a recorded timestamp.** TÜİK publishes on the 3rd of
  the month at 10:00; when the 3rd is a weekend the release moves to the next working
  day. Holidays that shift a release further are not modelled.
- **No revisions.** The tables hold the values as published on 2026-11-18. Turkish CPI
  is not revised in practice; the policy and Fed tables are decision records.
- A decision or a figure counts from its date; nothing is used before it.

## 3. Financial statements and their publication times

Built on 2026-11-18 into `data/snapshots/20261117-0722/fundamentals/`
(`statements.parquet`, `calendar.parquet`, `manifest.json`). Coverage and timing
statistics: `docs/results/2026-11-18-fundamentals-coverage.md`.

| Item | Source | Notes |
| --- | --- | --- |
| Statement items | İş Yatırım, public financial-statement service (`MaliTablo`) | Cumulative values per reporting period with an item code per line. Layout `XI_29` for industrial companies, `UFRS_K` for the bank and the insurer |
| Publication time | KAP (Kamuyu Aydınlatma Platformu), disclosure query, class "FR", subject "Finansal Rapor" | Timestamp to the second, with the fiscal year and period of the report |

The brief names Fintables for fundamentals. No Fintables access was available, and
announcement 1 (item 2) allows another reliable source; announcement 1 (item 3)
recommends KAP for disclosure times.

Rules applied:

- **A statement is used from the first trading day whose close follows its KAP
  timestamp**: before 18:00 on a trading day, that day; otherwise the next trading day.
- If a period has several financial-report disclosures, the first one counts.
- Item codes used per metric are listed in `src/bist_harness/tools/fundamentals.py`
  (`ITEMS`).
- Inflation accounting (TMS 29): non-bank statements from the 2023 year end on are
  inflation-adjusted. Year-over-year growth is reported in nominal terms and in real
  terms (the earlier amount is brought to the later period's price level with the CPI
  index); a comparison that reaches back before the 2023 year end is flagged.

## 4. Company events (KAP disclosure metadata)

Built on 2026-11-18 with `uv run python -m bist_harness.data.kap build 15 520` (two timed
runs) into `data/snapshots/20261117-0722/kap/disclosures.parquet`.

| Item | Value |
| --- | --- |
| Source | KAP disclosure query, class "ODA" (material events), one request per stock and calendar year |
| Range | 2025-01-02 to 2026-11-16 |
| Stocks | 30 (58 to 893 disclosures each; the brokerage ISMEN has 893, mostly warrant notices) |
| Rows | 4,960, no duplicates |
| Stored | Publication time, company, category, subject line, summary line, disclosure number, link. **No disclosure text** |
| Published at or after 18:00 | 2,183 of 4,960 |

Topic tags are assigned by keyword rules when the file is read (`data/kap.py`,
`TOPIC_RULES`; the first matching rule wins):

| Topic | Disclosures | Topic | Disclosures |
| --- | --- | --- | --- |
| `financing` | 1,201 | `dividend` | 182 |
| `management` | 747 | `credit_rating` | 154 |
| `other` | 745 | `capital_increase` | 148 |
| `structured_products` | 645 | `investment` | 118 |
| `contract` | 300 | `earnings` | 107 |
| `buyback` | 270 | `merger_acquisition` | 86 |
| `share_transactions` | 221 | `regulation_legal` | 36 |

Notes:

- The rules were corrected once after looking at the real download: "Esas Sözleşme
  Tadili" (articles of association) had been tagged `contract`, warrant notices
  `investment`, and "İhracı" was missed because of the Turkish ç/c change. The
  `regulation_legal` set, the only tag a strategy variant uses, did not change (36).
- About 15% of the disclosures stay `other` (mostly "Özel Durum Açıklaması (Genel)" with
  a free-form summary). The tag is a coarse label for context, not a classification to
  rely on.
- This layer is context only (announcement 1, item 3): it never supplies a number.
- There is no speech-to-text layer yet; it is planned for Sprint 7 with a fixed list of
  approved public videos.
