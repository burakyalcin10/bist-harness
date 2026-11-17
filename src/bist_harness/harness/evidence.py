"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

The evidence builder: tool outputs become numbered, templated sentences E1..En.

Rules (design spec section 7):

* One template per (tool, field), in Turkish and English. A sentence states what the field
  means and contains only the number(s) of the fields the template names. The numbers are
  copied from the tool output and formatted; the model never writes one, it only cites the
  label (E3).
* A field without a value gives no sentence; an error output or a call that was not
  allowed gives no evidence.
* Warnings (``sample_warning``, ``coverage_warning``, ``warnings``, flags) are not evidence;
  they travel in a separate warnings list.
* The committed evidence set is chosen by a minimum-evidence rule per scenario. When the
  minimum is not met the missing kinds are reported (``missing_requirements``); nothing is
  invented, and the gate (Task 6) turns the gap into INVESTIGATE.

Number formatting: values are written at two decimals (the precision of the tools and the
comparison of rule K-008); a p-value below one keeps its four. A Turkish decimal comma is read back
correctly by ``eval.number_check`` as long as there are not exactly three decimals after
it, which would look like an English thousands group; two or four decimals never do,
except four decimals after a leading 1 to 9 ("1.0000"), so a p-value of one is written "1.00".
"""

# ruff: noqa: E501  (the sentence templates are one line each)

from __future__ import annotations

import dataclasses
import re
import string
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

LANGUAGES = ("tr", "en")
DISCLAIMER = {
    "tr": "Yalnızca geçmiş veriye dayalı kanıt; gelecekteki getiri için garanti yoktur.",
    "en": "Historical evidence only; no guarantee of future return.",
}


@dataclass(frozen=True)
class Evidence:
    label: str
    tool: str
    result_id: str
    field: str  # "rsi", or a row path such as "members[AKBNK].lag_score_pct"
    value: object
    sentence: str
    committed: bool


# --- templates ---------------------------------------------------------------------------
# Key: (tool, field). A field with a dot ("members.lag_score_pct") is read from a row of a
# list or dict inside the output; see ROWS. Placeholders name fields of the output (or of
# that row); ``{p_value:p}`` writes four decimals.
def _t(tr: str, en: str) -> dict[str, str]:
    return {"tr": tr, "en": en}


TEMPLATES: dict[tuple[str, str], dict[str, str]] = {
    # --- prices ---
    ("get_stock_history", "period_return_pct"): _t(
        "{ticker} kapanış fiyatı {first_date} ile {last_date} arasında %{period_return_pct} değişti.",
        "The closing price of {ticker} changed {period_return_pct}% between {first_date} and {last_date}.",
    ),
    ("get_stock_history", "last_close"): _t(
        "{ticker} için dönem sonu kapanışı {last_close} ({last_date}).",
        "The last close of {ticker} in the period was {last_close} ({last_date}).",
    ),
    ("get_index_history", "period_return_pct"): _t(
        "{index} endeksi {first_date} ile {last_date} arasında %{period_return_pct} değişti.",
        "The {index} index changed {period_return_pct}% between {first_date} and {last_date}.",
    ),
    # --- technical state ---
    ("calculate_indicators", "rsi"): _t(
        "{ticker} için {as_of} tarihinde RSI değeri {rsi}.",
        "The RSI of {ticker} on {as_of} was {rsi}.",
    ),
    ("calculate_indicators", "rsi_state"): _t(
        "{ticker} için {as_of} tarihinde RSI durumu: {rsi_state}.",
        "The RSI state of {ticker} on {as_of}: {rsi_state}.",
    ),
    ("calculate_indicators", "macd"): _t(
        "{ticker} için {as_of} tarihinde MACD değeri {macd}, sinyal çizgisi {macd_signal}.",
        "The MACD of {ticker} on {as_of} was {macd} against a signal line of {macd_signal}.",
    ),
    ("calculate_indicators", "macd_state"): _t(
        "{ticker} için {as_of} tarihinde MACD durumu: {macd_state}.",
        "The MACD state of {ticker} on {as_of}: {macd_state}.",
    ),
    ("calculate_indicators", "close_vs_sma_20"): _t(
        "{ticker} kapanışı {as_of} tarihinde kısa dönemli hareketli ortalamanın {close_vs_sma_20}.",
        "The close of {ticker} on {as_of} was {close_vs_sma_20} its short-term moving average.",
    ),
    ("calculate_indicators", "sma_20"): _t(
        "{ticker} için {as_of} tarihinde kısa dönemli hareketli ortalama {sma_20}.",
        "The short-term moving average of {ticker} on {as_of} was {sma_20}.",
    ),
    ("calculate_indicators", "sma_50"): _t(
        "{ticker} için {as_of} tarihinde orta dönemli hareketli ortalama {sma_50}.",
        "The medium-term moving average of {ticker} on {as_of} was {sma_50}.",
    ),
    ("find_support_resistance", "nearest_support"): _t(
        "{ticker} için en yakın destek seviyesi {nearest_support} (son kapanış {last_close}).",
        "The nearest support level of {ticker} was {nearest_support} (last close {last_close}).",
    ),
    ("find_support_resistance", "nearest_resistance"): _t(
        "{ticker} için en yakın direnç seviyesi {nearest_resistance} (son kapanış {last_close}).",
        "The nearest resistance level of {ticker} was {nearest_resistance} (last close {last_close}).",
    ),
    # --- sector ---
    ("rank_sector_relative_strength", "sector_median_return_pct"): _t(
        "{sector} sektörünün {as_of} tarihine kadarki {horizon_days} işlem günlük medyan getirisi %{sector_median_return_pct}.",
        "The median return of the {sector} sector over {horizon_days} trading days to {as_of} was {sector_median_return_pct}%.",
    ),
    ("rank_sector_relative_strength", "benchmark_return_pct"): _t(
        "{benchmark} endeksinin aynı {horizon_days} işlem gününde getirisi %{benchmark_return_pct}.",
        "The {benchmark} index return over the same {horizon_days} trading days was {benchmark_return_pct}%.",
    ),
    ("rank_sector_relative_strength", "sector_strong"): _t(
        "{sector} sektörünün medyan getirisi {benchmark} endeksinin getirisinden yüksek mi: {sector_strong}.",
        "Whether the {sector} sector median return was above the {benchmark} index return: {sector_strong}.",
    ),
    ("rank_sector_relative_strength", "members.return_pct"): _t(
        "{ticker} hissesinin {horizon_days} işlem günlük getirisi %{return_pct}.",
        "The return of {ticker} over {horizon_days} trading days was {return_pct}%.",
    ),
    ("rank_sector_relative_strength", "members.lag_score_pct"): _t(
        "{ticker} için {sector} sektörüne göre {horizon_days} işlem günlük gecikme skoru {lag_score_pct} puan (getiri eksi sektör medyanı; negatif geride kalmayı gösterir).",
        "The lag score of {ticker} against the {sector} sector over {horizon_days} trading days was {lag_score_pct} points (return minus sector median; negative means lagging).",
    ),
    # --- technical reversal and calendar pattern ---
    ("detect_reversal_events", "successful_events"): _t(
        "{ticker} için {event_count} {event_type} olayının {successful_events} tanesi başarılıydı.",
        "{successful_events} of the {event_count} {event_type} events for {ticker} were successful.",
    ),
    ("detect_reversal_events", "success_rate_pct"): _t(
        "Teknik dönüş olaylarında başarı oranı %{success_rate_pct} ({event_type}, {ticker}).",
        "Success rate of the technical reversal events was {success_rate_pct}% ({event_type}, {ticker}).",
    ),
    ("detect_reversal_events", "average_forward_return_pct"): _t(
        "{event_type} olaylarından sonraki {forward_days} işlem günlük ortalama getiri %{average_forward_return_pct} ({ticker}).",
        "The average return {forward_days} trading days after {event_type} events was {average_forward_return_pct}% ({ticker}).",
    ),
    ("detect_reversal_events", "median_forward_return_pct"): _t(
        "{event_type} olaylarından sonraki {forward_days} işlem günlük medyan getiri %{median_forward_return_pct} ({ticker}).",
        "The median return {forward_days} trading days after {event_type} events was {median_forward_return_pct}% ({ticker}).",
    ),
    ("detect_reversal_events", "last_event_date"): _t(
        "{ticker} için son {event_type} olayı {last_event_date} tarihinde.",
        "The last {event_type} event for {ticker} was on {last_event_date}.",
    ),
    ("test_weekday_pattern", "best_day"): _t(
        "{ticker} için ortalama getirisi en yüksek haftanın günü {best_day}.",
        "The weekday with the highest average return for {ticker} was {best_day}.",
    ),
    ("test_weekday_pattern", "spread_pct"): _t(
        "{ticker} için en iyi ve en kötü haftanın günü arasındaki ortalama getiri farkı %{spread_pct}.",
        "The gap in average return between the best and the worst weekday for {ticker} was {spread_pct}%.",
    ),
    ("test_weekday_pattern", "mean_after_cost_pct"): _t(
        "{ticker} için en iyi günün işlem maliyeti sonrası ortalama getirisi %{mean_after_cost_pct}.",
        "The average return of the best weekday for {ticker} after transaction cost was {mean_after_cost_pct}%.",
    ),
    ("test_weekday_pattern", "p_value"): _t(
        "Haftanın günü farkının tesadüf olma olasılığı (p değeri) {p_value:p}.",
        "The probability that the weekday gap is chance (p-value) was {p_value:p}.",
    ),
    ("test_weekday_pattern", "p_value_bonferroni"): _t(
        "Birden fazla deneme için düzeltilmiş p değeri {p_value_bonferroni:p}.",
        "The p-value corrected for several tested patterns was {p_value_bonferroni:p}.",
    ),
    # --- fundamentals ---
    ("get_fundamental_metrics", "revenue_yoy_pct"): _t(
        "{ticker} için {period} döneminde hasılatın yıllık değişimi %{revenue_yoy_pct}.",
        "The year-over-year change in revenue of {ticker} in {period} was {revenue_yoy_pct}%.",
    ),
    ("get_fundamental_metrics", "revenue_real_yoy_pct"): _t(
        "{ticker} için {period} döneminde hasılatın enflasyondan arındırılmış yıllık değişimi %{revenue_real_yoy_pct}.",
        "The inflation-adjusted year-over-year change in revenue of {ticker} in {period} was {revenue_real_yoy_pct}%.",
    ),
    ("get_fundamental_metrics", "net_profit_yoy_pct"): _t(
        "{ticker} için {period} döneminde net kârın yıllık değişimi %{net_profit_yoy_pct}.",
        "The year-over-year change in net profit of {ticker} in {period} was {net_profit_yoy_pct}%.",
    ),
    ("get_fundamental_metrics", "net_profit_real_yoy_pct"): _t(
        "{ticker} için {period} döneminde net kârın enflasyondan arındırılmış yıllık değişimi %{net_profit_real_yoy_pct}.",
        "The inflation-adjusted year-over-year change in net profit of {ticker} in {period} was {net_profit_real_yoy_pct}%.",
    ),
    ("get_fundamental_metrics", "ebitda_margin_pct"): _t(
        "{ticker} için {period} döneminde FAVÖK marjı %{ebitda_margin_pct}.",
        "The EBITDA margin of {ticker} in {period} was {ebitda_margin_pct}%.",
    ),
    ("get_fundamental_metrics", "net_margin_pct"): _t(
        "{ticker} için {period} döneminde net kâr marjı %{net_margin_pct}.",
        "The net profit margin of {ticker} in {period} was {net_margin_pct}%.",
    ),
    ("get_fundamental_metrics", "roe_pct"): _t(
        "{ticker} için {period} döneminde özkaynak kârlılığı %{roe_pct}.",
        "The return on equity of {ticker} in {period} was {roe_pct}%.",
    ),
    ("get_fundamental_metrics", "net_debt_to_ebitda"): _t(
        "{ticker} için {period} döneminde net borcun FAVÖK'e oranı {net_debt_to_ebitda}.",
        "The ratio of net debt to EBITDA of {ticker} in {period} was {net_debt_to_ebitda}.",
    ),
    ("get_fundamental_metrics", "current_ratio"): _t(
        "{ticker} için {period} döneminde cari oran {current_ratio}.",
        "The current ratio of {ticker} in {period} was {current_ratio}.",
    ),
    ("get_fundamental_metrics", "pe"): _t(
        "{ticker} için {period} verisiyle fiyat/kazanç oranı {pe}.",
        "The price-to-earnings ratio of {ticker} on {period} data was {pe}.",
    ),
    ("get_fundamental_metrics", "pb"): _t(
        "{ticker} için {period} verisiyle piyasa değeri/defter değeri oranı {pb}.",
        "The price-to-book ratio of {ticker} on {period} data was {pb}.",
    ),
    ("calculate_fundamental_change", "fundamental_trend"): _t(
        "{ticker} için {period} dönemi temel görünümü {compared_with} dönemine göre: {fundamental_trend}.",
        "The fundamental trend of {ticker} in {period} against {compared_with}: {fundamental_trend}.",
    ),
    ("calculate_fundamental_change", "net_profit_real_yoy_pct"): _t(
        "{ticker} için {period} döneminde net kârın enflasyondan arındırılmış yıllık değişimi %{net_profit_real_yoy_pct}.",
        "The inflation-adjusted year-over-year change in net profit of {ticker} in {period} was {net_profit_real_yoy_pct}%.",
    ),
    ("calculate_fundamental_change", "net_margin_change_pp"): _t(
        "{ticker} için net kâr marjı {compared_with} dönemine göre {net_margin_change_pp} puan değişti.",
        "The net profit margin of {ticker} changed {net_margin_change_pp} points against {compared_with}.",
    ),
    ("calculate_fundamental_change", "ebitda_margin_change_pp"): _t(
        "{ticker} için FAVÖK marjı {compared_with} dönemine göre {ebitda_margin_change_pp} puan değişti.",
        "The EBITDA margin of {ticker} changed {ebitda_margin_change_pp} points against {compared_with}.",
    ),
    ("calculate_fundamental_change", "quarters.reaction_5d_pct"): _t(
        "{ticker} hissesinin {period} finansallarının açıklanmasından sonraki beş işlem günlük getirisi %{reaction_5d_pct}.",
        "The return of {ticker} over the five trading days after the {period} financials were published was {reaction_5d_pct}%.",
    ),
    ("calculate_fundamental_change", "quarters.abnormal_vs_index_5d_pct"): _t(
        "{ticker} hissesinin {period} finansallarının açıklanmasından sonraki beş işlem gününde endeksten farkı {abnormal_vs_index_5d_pct} puan.",
        "The return of {ticker} against the index over the five trading days after the {period} financials were published was {abnormal_vs_index_5d_pct} points.",
    ),
    # --- macro and news ---
    ("get_macro_context", "policy_rate_end"): _t(
        "Dönem sonunda politika faizi %{policy_rate_end} ({end}).",
        "The policy rate at the end of the period was {policy_rate_end}% ({end}).",
    ),
    ("get_macro_context", "policy_rate_change_pp"): _t(
        "Politika faizi dönem içinde {policy_rate_change_pp} puan değişti.",
        "The policy rate changed {policy_rate_change_pp} points over the period.",
    ),
    ("get_macro_context", "cpi_annual_pct"): _t(
        "{cpi_period} dönemi yıllık enflasyon %{cpi_annual_pct}.",
        "Annual inflation for {cpi_period} was {cpi_annual_pct}%.",
    ),
    ("get_macro_context", "usdtry_change_pct"): _t(
        "Dolar/TL kuru dönem içinde %{usdtry_change_pct} değişti.",
        "The USD/TRY rate changed {usdtry_change_pct}% over the period.",
    ),
    ("get_macro_context", "eurtry_change_pct"): _t(
        "Euro/TL kuru dönem içinde %{eurtry_change_pct} değişti.",
        "The EUR/TRY rate changed {eurtry_change_pct}% over the period.",
    ),
    ("get_news_events", "total"): _t(
        "{start} ile {end} arasında {total} KAP bildirimi bulundu (yalnızca bağlam).",
        "{total} KAP disclosures were found between {start} and {end} (context only).",
    ),
    # --- backtest ---
    ("run_backtest", "trades"): _t(
        "{strategy} stratejisi {start} ile {end} arasında {trades} işlem yaptı.",
        "The {strategy} strategy made {trades} trades between {start} and {end}.",
    ),
    ("run_backtest", "win_rate_pct"): _t(
        "{strategy} stratejisinde kazanan işlem oranı %{win_rate_pct}.",
        "The share of winning trades of the {strategy} strategy was {win_rate_pct}%.",
    ),
    ("run_backtest", "average_trade_return_pct"): _t(
        "{strategy} stratejisinde işlem başına ortalama getiri %{average_trade_return_pct}.",
        "The average return per trade of the {strategy} strategy was {average_trade_return_pct}%.",
    ),
    ("run_backtest", "cumulative_return_pct"): _t(
        "{strategy} stratejisinin dönem boyunca kümülatif getirisi %{cumulative_return_pct}.",
        "The cumulative return of the {strategy} strategy over the period was {cumulative_return_pct}%.",
    ),
    ("run_backtest", "max_drawdown_pct"): _t(
        "{strategy} stratejisinin en büyük değer kaybı (maksimum düşüş) %{max_drawdown_pct}.",
        "The maximum drawdown of the {strategy} strategy was {max_drawdown_pct}%.",
    ),
    ("run_backtest", "excess_vs_buy_and_hold_pct"): _t(
        "{strategy} stratejisi al-ve-tut getirisinin {excess_vs_buy_and_hold_pct} puan üzerinde (negatifse altında).",
        "The {strategy} strategy return minus the buy-and-hold return was {excess_vs_buy_and_hold_pct} points (negative means below).",
    ),
    ("run_backtest", "excess_vs_xu100_pct"): _t(
        "{strategy} stratejisi getirisi eksi endeks getirisi {excess_vs_xu100_pct} puan (negatifse endeksin altında).",
        "The {strategy} strategy return minus the index return was {excess_vs_xu100_pct} points (negative means below the index).",
    ),
    ("run_backtest", "by_period.win_rate_pct"): _t(
        "{strategy} stratejisinin test döneminde {trades} işlemin kazanan oranı %{win_rate_pct}.",
        "In the test period the share of winning trades of the {strategy} strategy over {trades} trades was {win_rate_pct}%.",
    ),
    ("run_backtest", "by_period.average_trade_return_pct"): _t(
        "{strategy} stratejisinin test döneminde işlem başına ortalama getirisi %{average_trade_return_pct}.",
        "In the test period the average return per trade of the {strategy} strategy was {average_trade_return_pct}%.",
    ),
}

# Row fields: (tool, "container.field") -> how the rows are found. ``select`` returns the
# (key, row) pairs that give sentences; the field path is ``container[key].field``.
_TR_WORDS = {
    "Above": "üstünde",
    "Below": "altında",
    "Neutral": "nötr",
    "Local Low": "yerel dipte",
    "Local High": "yerel tepede",
    "Bullish": "yükseliş yönlü",
    "Bearish": "düşüş yönlü",
    "Improving": "iyileşiyor",
    "Deteriorating": "kötüleşiyor",
    "Mixed": "karışık",
    "Mon": "Pazartesi",
    "Tue": "Salı",
    "Wed": "Çarşamba",
    "Thu": "Perşembe",
    "Fri": "Cuma",
}
_EN_WORDS = {
    "Above": "above",
    "Below": "below",
    "Neutral": "neutral",
    "Local Low": "at a local low",
    "Local High": "at a local high",
    "Bullish": "bullish (MACD above its signal)",
    "Bearish": "bearish (MACD below its signal)",
    "Improving": "improving",
    "Deteriorating": "deteriorating",
    "Mixed": "mixed",
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
}
WORDS = {"tr": _TR_WORDS, "en": _EN_WORDS}
_YES_NO = {"tr": ("evet", "hayır"), "en": ("yes", "no")}


def _rank_rows(output: dict) -> list[tuple[str, dict]]:
    """Only the stock(s) of the analysis (role ``universe``), not the reference peers."""
    return [(m["ticker"], m) for m in output.get("members") or [] if m.get("role") == "universe"]


def _latest_quarter(output: dict) -> list[tuple[str, dict]]:
    quarters = output.get("quarters") or []
    return [(quarters[0]["period"], quarters[0])] if quarters else []


def _test_period(output: dict) -> list[tuple[str, dict]]:
    row = (output.get("by_period") or {}).get("test")
    return [("test", row)] if isinstance(row, dict) else []


ROWS = {
    ("rank_sector_relative_strength", "members"): _rank_rows,
    ("calculate_fundamental_change", "quarters"): _latest_quarter,
    ("run_backtest", "by_period"): _test_period,
}


class _Formatter(string.Formatter):
    """Writes numbers and words for one language; the spec ``p`` writes four decimals."""

    def __init__(self, language: str):
        self.language = language

    def format_field(self, value: Any, format_spec: str) -> str:
        if isinstance(value, bool):
            return _YES_NO[self.language][0 if value else 1]
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            # A p-value below one keeps four decimals; "1.0000" would read as a thousands
            # group followed by a zero, so one is written "1.00".
            four = format_spec == "p" and abs(value) < 1
            text = f"{value:.4f}" if four else f"{value:.2f}"
            if float(text) == 0:
                text = text.lstrip("-")  # never "-0.00"
            return text.replace(".", ",") if self.language == "tr" else text
        return WORDS[self.language].get(str(value), str(value))


def _fields_of(template: str) -> list[str]:
    return [name for _, name, _, _ in string.Formatter().parse(template) if name]


def _usable(value: object) -> bool:
    return value is not None and not (isinstance(value, float) and value != value)


def _sentence(key: tuple[str, str], scope: dict, language: str) -> str | None:
    template = TEMPLATES[key][language]
    if not all(_usable(scope.get(name)) for name in _fields_of(template)):
        return None  # a placeholder without a value: no sentence
    return _Formatter(language).format(template, **scope)


def _usable_calls(analysis) -> list:
    """Allowed calls with a result id and no error; the same result counts once."""
    seen: set[str] = set()
    calls = []
    for call in analysis.tool_calls:
        output = call.output
        if not call.allowed or not isinstance(output, dict) or "error" in output:
            continue
        result_id = output.get("result_id")
        if not isinstance(result_id, str) or result_id in seen:
            continue
        seen.add(result_id)
        calls.append(call)
    return calls


def _items_of_call(call, language: str) -> list[tuple[str, object, str]]:
    """(field path, value, sentence) for each template of the call's tool, in template order."""
    output = call.output
    top = {k: v for k, v in output.items() if not isinstance(v, dict | list)}
    found = []
    for key in TEMPLATES:
        if key[0] != call.tool:
            continue
        name = key[1]
        if "." not in name:
            if _usable(output.get(name)):
                sentence = _sentence(key, top, language)
                if sentence:
                    found.append((name, output[name], sentence))
            continue
        container, leaf = name.split(".", 1)
        for row_key, row in ROWS[(call.tool, container)](output):
            if not _usable(row.get(leaf)):
                continue
            sentence = _sentence(key, {**top, **row}, language)
            if sentence:
                found.append((f"{container}[{row_key}].{leaf}", row[leaf], sentence))
    return found


# --- committed evidence set --------------------------------------------------------------
# Minimum evidence per scenario: requirement name -> the (tool, field) kinds that satisfy it.
# A requirement is met when at least one of its kinds is present; every present kind is
# committed. The order of requirements is the order they are reported in.
_Key = tuple[str, str]
_TECH: tuple[str, tuple[_Key, ...]] = (
    "technical_state",
    (
        ("calculate_indicators", "rsi"),
        ("calculate_indicators", "rsi_state"),
        ("calculate_indicators", "macd_state"),
        ("calculate_indicators", "close_vs_sma_20"),
    ),
)
_BACKTEST: tuple[str, tuple[_Key, ...]] = (
    "backtest_summary",
    tuple(
        ("run_backtest", f)
        for f in (
            "trades",
            "win_rate_pct",
            "average_trade_return_pct",
            "max_drawdown_pct",
            "by_period.win_rate_pct",
            "by_period.average_trade_return_pct",
        )
    ),
)
MINIMUM: dict[str, tuple[tuple[str, tuple[_Key, ...]], ...]] = {
    "SECTOR_LAGGARD": (
        (
            "sector_median",
            (("rank_sector_relative_strength", "sector_median_return_pct"),),
        ),
        (
            "lag_score",
            (
                ("rank_sector_relative_strength", "members.lag_score_pct"),
                ("rank_sector_relative_strength", "members.return_pct"),
            ),
        ),
        (
            "sector_vs_index",
            (
                ("rank_sector_relative_strength", "sector_strong"),
                ("rank_sector_relative_strength", "benchmark_return_pct"),
            ),
        ),
        _TECH,
        _BACKTEST,
    ),
    "CALENDAR_PATTERN": (
        (
            "pattern_result",
            (
                ("test_weekday_pattern", "best_day"),
                ("test_weekday_pattern", "spread_pct"),
                ("test_weekday_pattern", "mean_after_cost_pct"),
            ),
        ),
        (
            "significance",
            (
                ("test_weekday_pattern", "p_value"),
                ("test_weekday_pattern", "p_value_bonferroni"),
            ),
        ),
        _BACKTEST,
    ),
    "TECHNICAL_REVERSAL": (
        (
            "reversal_stats",
            tuple(
                ("detect_reversal_events", f)
                for f in (
                    "successful_events",
                    "success_rate_pct",
                    "average_forward_return_pct",
                    "median_forward_return_pct",
                )
            ),
        ),
        _TECH,
        _BACKTEST,
    ),
    "FUNDAMENTAL_REACTION": (
        (
            "fundamental_change",
            tuple(
                ("calculate_fundamental_change", f)
                for f in (
                    "fundamental_trend",
                    "net_profit_real_yoy_pct",
                    "net_margin_change_pp",
                    "ebitda_margin_change_pp",
                )
            ),
        ),
        (
            "price_reaction",
            (
                ("calculate_fundamental_change", "quarters.reaction_5d_pct"),
                ("calculate_fundamental_change", "quarters.abnormal_vs_index_5d_pct"),
            ),
        ),
        _TECH,
        _BACKTEST,
    ),
    "BACKTEST": (
        _BACKTEST,
        (
            "benchmark_comparison",
            (
                ("run_backtest", "excess_vs_xu100_pct"),
                ("run_backtest", "excess_vs_buy_and_hold_pct"),
            ),
        ),
    ),
    "PRICE_SUMMARY": (
        (
            "price_change",
            (
                ("get_stock_history", "period_return_pct"),
                ("get_stock_history", "last_close"),
            ),
        ),
        _TECH,
    ),
    "MACRO_CONTEXT": (
        (
            "macro_context",
            tuple(
                ("get_macro_context", f)
                for f in (
                    "policy_rate_end",
                    "policy_rate_change_pp",
                    "cpi_annual_pct",
                    "usdtry_change_pct",
                    "eurtry_change_pct",
                )
            ),
        ),
    ),
    "NEWS_CONTEXT": (("news_count", (("get_news_events", "total"),)),),
    # ADVICE_REQUEST, PREDICTION_REQUEST and OUT_OF_SCOPE end early: no evidence is needed.
}

_ROW_PATH = re.compile(r"^(\w+)\[.+?\]\.(\w+)$")


def _key_of(item: Evidence) -> _Key:
    return item.tool, _ROW_PATH.sub(r"\1.\2", item.field)


def missing_requirements(evidence: Sequence[Evidence], scenario: str) -> list[str]:
    """Names of the minimum-evidence requirements of the scenario that no item meets."""
    present = {_key_of(item) for item in evidence}
    return [name for name, kinds in MINIMUM.get(scenario, ()) if not present & set(kinds)]


def committed_set(evidence: Sequence[Evidence], scenario: str) -> list[Evidence]:
    """The items of the scenario's minimum evidence, in evidence order, flagged committed.

    Only existing items are chosen; a requirement nothing meets is reported by
    ``missing_requirements`` and adds nothing here.
    """
    wanted = {kind for _, kinds in MINIMUM.get(scenario, ()) for kind in kinds}
    return [
        item if item.committed else dataclasses.replace(item, committed=True)
        for item in evidence
        if _key_of(item) in wanted
    ]


# --- building ----------------------------------------------------------------------------
def build_evidence(analysis, *, language: str) -> list[Evidence]:
    """Every templated sentence of the analysis, labelled E1..En in tool-call order.

    ``committed`` marks the items of the scenario's committed evidence set; the explanation
    may cite only those.
    """
    language = language if language in LANGUAGES else "en"
    items = []
    for call in _usable_calls(analysis):
        for field, value, sentence in _items_of_call(call, language):
            items.append(
                Evidence(
                    label=f"E{len(items) + 1}",
                    tool=call.tool,
                    result_id=call.output["result_id"],
                    field=field,
                    value=value,
                    sentence=sentence,
                    committed=False,
                )
            )
    scenario = (analysis.intent or {}).get("scenario")
    chosen = {item.label for item in committed_set(items, scenario)} if scenario else set()
    return [dataclasses.replace(item, committed=item.label in chosen) for item in items]


def collect_warnings(analysis, *, language: str = "en") -> list[dict]:
    """The disclaimer, then the warnings and flags of every usable call, once each.

    A warning is ``{"tool", "result_id", "text"}``; the disclaimer has no tool.
    """
    language = language if language in LANGUAGES else "en"
    found = [{"tool": None, "result_id": None, "text": DISCLAIMER[language]}]
    seen: set[tuple[str, str]] = set()
    for call in _usable_calls(analysis):
        output = call.output
        texts: list[Any] = [output.get("sample_warning"), output.get("coverage_warning")]
        for name in ("warnings", "flags", "interpretation_flags"):
            value = output.get(name)
            texts.extend(value if isinstance(value, list) else [])
        for text in texts:
            if isinstance(text, str) and text and (output["result_id"], text) not in seen:
                seen.add((output["result_id"], text))
                found.append({"tool": call.tool, "result_id": output["result_id"], "text": text})
    return found
