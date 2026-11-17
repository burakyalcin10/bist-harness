"""Reading statement figures from a KAP financial-report page (K-055)."""

from datetime import date

import pytest

from bist_harness.data import kap_report_parser as kp
from bist_harness.data import kap_reports


def _header_table(unit: str, nature: str) -> str:
    return (
        '<table class="financial-header-table">'
        f'<tr><td class="financial-header-title">Sunum Para Birimi</td><td>{unit}</td></tr>'
        f'<tr><td class="financial-header-title">Finansal Tablo Niteliği</td><td>{nature}</td></tr>'
        "</table>"
    )


def _context(tr: str, en: str, span: int = 1) -> str:
    # as on KAP: lower-case colspan, a column id, and a style on each language block
    attrs = f' colspan="{span}"' if span > 1 else ""
    return (
        f'<td align="center" class="context-header" column-id="5"{attrs}><div>'
        f'<div class="gwt-HTML multi-language-content content-tr" style="display: block;">{tr}</div>'
        f'<div class="gwt-HTML multi-language-content content-en" style="display: none;">{en}</div>'
        "</div></td>"
    )


def _part(tr: str, en: str) -> str:
    return (
        '<td class="context-header"><div>'
        f'<div class="gwt-HTML multi-language-content content-tr">{tr}</div>'
        f'<div class="gwt-HTML multi-language-content content-en">{en}</div></div></td>'
    )


def _row(concept: str, values: list[str | None], first_col: int = 4) -> str:
    cells = "".join(
        f'<td class="taxonomy-context-value col-order-class-{first_col + i}"><div>'
        + (
            f'<div class="gwt-Label taxonomy-label-field" title="{v}">{v}</div>'
            if v is not None
            else ""
        )
        + "</div></td>"
        for i, v in enumerate(values)
    )
    return (
        '<tr class="row data-input-row">'
        '<td class="taxonomy-field-name-cell"><div class="gwt-Label taxonomy-field-name">'
        f'{concept}|</div></td><td class="taxonomy-field-title">label</td>{cells}</tr>'
    )


def _table(role: str, header_rows: list[str], rows: list[str]) -> str:
    head = "".join(f'<tr><td colSpan="3"></td>{r}</tr>' for r in header_rows)
    return f'<table class="financial-table tbl_{role}"><tbody>{head}{"".join(rows)}</tbody></table>'


INCOME = _table(
    "general_role_310000",
    [
        _context(
            "Cari Dönem<br/>01.01.2024 - 30.09.2024", "Current Period<br/>01.01.2024 - 30.09.2024"
        )
        + _context(
            "Önceki Dönem<br/>01.01.2023 - 30.09.2023",
            "Previous Period<br/>01.01.2023 - 30.09.2023",
        )
        + _context(
            "Cari Dönem 3 Aylık<br/>01.07.2024 - 30.09.2024",
            "Current Period 3 Months<br/>01.07.2024 - 30.09.2024",
        )
    ],
    [
        _row("ifrs-full_Revenue", ["599332000", "450000000", "210000000"]),
        _row("ifrs-full_ProfitLoss", ["-13868020", None, "-1000"]),
        _row("ifrs-full_Revenue", ["1", "1", "1"]),  # a repeated concept: the first one counts
    ],
)
BALANCE = _table(
    "general_role_210015",
    [
        _context("Cari Dönem<br/>30.09.2024", "Current Period<br/>30.09.2024")
        + _context("Önceki Dönem<br/>31.12.2023", "Previous Period<br/>31.12.2023")
    ],
    [_row("ifrs-full_Equity", ["245109097", "230000000"])],
)
EQUITY_CHANGES = _table("general_role_610000", [], [_row("ifrs-full_Equity", ["9", "9"])])
BANK_BALANCE = _table(
    "banks_role_210011",
    [
        _context("Cari Dönem<br/>30.09.2024", "Current Period<br/>30.09.2024", span=3)
        + _context("Önceki Dönem<br/>31.12.2023", "Previous Period<br/>31.12.2023", span=3),
        _part("TP", "TC")
        + _part("YP", "FC")
        + _part("Toplam", "Total")
        + _part("TP", "TC")
        + _part("YP", "FC")
        + _part("Toplam", "Total"),
    ],
    [_row("ifrs-full_Assets", ["1530206103", "874083826", "2404289929", "1", "2", "3"])],
)


def _page(*parts: str) -> str:
    return "<html><body>" + "".join(parts) + "</body></html>"


def _escaped(html: str) -> str:
    """KAP pages also carry the same HTML once more, escaped inside a script string."""
    return html.replace("<", "\\u003c").replace(">", "\\u003e").replace('"', '\\"')


def test_unit_and_consolidation_are_read_from_the_page():
    report = kp.parse_report(_page(_header_table("1.000 TL", "Konsolide"), INCOME))
    assert report.unit == 1000 and report.consolidated is True
    solo = kp.parse_report(_page(_header_table("TL", "Konsolide Olmayan"), INCOME))
    assert solo.unit == 1 and solo.consolidated is False
    millions = kp.parse_report(_page(_header_table("1.000.000 TL", "Konsolide"), INCOME))
    assert millions.unit == 1_000_000


def test_flow_values_are_found_by_concept_and_period_and_scaled_to_lira():
    report = kp.parse_report(_page(_header_table("1.000 TL", "Konsolide"), INCOME))
    current = report.value("ifrs-full_Revenue", start=date(2024, 1, 1), end=date(2024, 9, 30))
    prior = report.value("ifrs-full_Revenue", start=date(2023, 1, 1), end=date(2023, 9, 30))
    quarter = report.value("ifrs-full_Revenue", start=date(2024, 7, 1), end=date(2024, 9, 30))
    assert (current, prior, quarter) == (599_332_000_000.0, 450_000_000_000.0, 210_000_000_000.0)
    loss = report.value("ifrs-full_ProfitLoss", start=date(2024, 1, 1), end=date(2024, 9, 30))
    assert loss == -13_868_020_000.0
    assert (
        report.value("ifrs-full_ProfitLoss", start=date(2023, 1, 1), end=date(2023, 9, 30)) is None
    )
    assert report.value("ifrs-full_Missing", start=date(2024, 1, 1), end=date(2024, 9, 30)) is None


def test_balance_values_are_found_by_their_date():
    report = kp.parse_report(_page(_header_table("1.000 TL", "Konsolide"), BALANCE))
    assert report.value("ifrs-full_Equity", end=date(2024, 9, 30)) == 245_109_097_000.0
    assert report.value("ifrs-full_Equity", end=date(2023, 12, 31)) == 230_000_000_000.0


def test_bank_balance_sheets_use_the_total_column_not_the_lira_part():
    report = kp.parse_report(_page(_header_table("1.000 TL", "Konsolide"), BANK_BALANCE))
    assert report.value("ifrs-full_Assets", end=date(2024, 9, 30)) == 2_404_289_929_000.0
    assert report.value("ifrs-full_Assets", end=date(2023, 12, 31)) == 3_000.0


def test_the_escaped_copy_and_the_equity_change_table_add_nothing():
    html = _page(_header_table("1.000 TL", "Konsolide"), INCOME, BALANCE, EQUITY_CHANGES)
    report = kp.parse_report(html + _escaped(html))
    equities = [f for f in report.facts if f.concept == "ifrs-full_Equity"]
    assert len(equities) == 2  # current and prior column of the balance sheet only
    revenues = [f for f in report.facts if f.concept == "ifrs-full_Revenue"]
    assert len(revenues) == 3


def test_a_page_without_statements_is_reported():
    with pytest.raises(ValueError, match="no financial statement"):
        kp.parse_report("<html>bildirim bulunamadı</html>")


@pytest.mark.real_data
def test_real_pages_give_the_figures_seen_on_kap():
    pages = kap_reports.report_folder() / "pages"
    if not (pages / "1393446.html.gz").is_file():
        pytest.skip("KAP pages not downloaded")
    tuprs = kp.parse_report(kap_reports.read_page(pages, 1393446))  # TUPRS 2024 annual
    assert tuprs.unit == 1000 and tuprs.consolidated is True
    assert tuprs.value("ifrs-full_Revenue", start=date(2024, 1, 1), end=date(2024, 12, 31)) == (
        810_385_588_000.0
    )
    assert tuprs.value("ifrs-full_Revenue", start=date(2023, 1, 1), end=date(2023, 12, 31)) == (
        991_202_993_000.0
    )
    akbnk = kp.parse_report(kap_reports.read_page(pages, 1350568))  # AKBNK 2024Q3, consolidated
    assert akbnk.value("ifrs-full_Assets", end=date(2024, 9, 30)) == 2_404_289_929_000.0
    thyao = kp.parse_report(kap_reports.read_page(pages, 1353359))  # THYAO 2024Q3, million TL
    assert thyao.value("ifrs-full_Revenue", start=date(2024, 1, 1), end=date(2024, 9, 30)) == (
        551_928_000_000.0
    )
