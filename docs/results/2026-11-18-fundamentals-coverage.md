# Fundamental data coverage — snapshot `20261117-0722`

Built on 2026-11-18 with `uv run python -m bist_harness.data.fundamentals build` and
`… fundamentals times` into `data/snapshots/20261117-0722/fundamentals/`.

| Item | Value |
| --- | --- |
| Stocks | 30 (the whole universe) |
| Reporting periods | 2022Q4 to 2026Q3: 16 per stock (MAVI 15: its fiscal year ends in January, so its latest period is 2026Q2) |
| Statement rows | 75,213 item values (cumulative, TRY) |
| Periods with a KAP publication time | 479 of 479 |
| Periods with a later correction on KAP | 55 (the first publication is used; the count is stored) |
| Latest period public by 2026-11-13 | 2026Q3 for 29 stocks, 2026Q2 for MAVI |

## When statements become public

| Measure | Value |
| --- | --- |
| Published before 18:00 | 57 periods (12%) |
| Published at or after 18:00 | 422 periods (88%) |
| Usable on the publication day itself | 51 |
| Usable only from the next trading day (or later) | 428 |
| Days from period end to first usable day | median 41, shortest 16, longest 135 |
| The same, by quarter | Q1 39, Q2 42, Q3 37, Q4 (annual, audited) 64 |

**Why this matters.** Almost nine reports in ten are released after the session. A
backtest that aligns a statement with its period end would use it about six weeks
before anyone could; one that uses the publication *date* would still trade on it at a
close that came before the release. The tools use neither: a period counts from the
first close after its publication timestamp.

## How the download went

The statement service answered every request. KAP dropped the connection after about
sixteen stocks asked in quick succession; the remaining fourteen were fetched with a
25-second pause and up to three attempts each, saved after every stock. A rebuild should
start with the slow setting (`fundamentals times 25`).

## Limits

- The statement values are those the source holds today. If a company restated a
  period later, the restated figures are stored; the original ones are not available
  from this source. The number of corrections per period is recorded so that affected
  periods can be listed.
- Banks and the insurer use different statement layouts; only total assets, equity,
  paid-in capital, the revenue line (net interest income, gross premiums) and net
  profit are mapped for them.
- THYAO reports in US dollars as its functional currency and does not apply inflation
  accounting; its TRY figures are translations.
