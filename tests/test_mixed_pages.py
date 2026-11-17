#!/usr/bin/env python3
"""
Pages whose text layer is not the page, and the bank-debt rows that look alike.

Every test here is a filing from the PURA/RCCC/TRIN/TRUK evaluation, traced back to the
page that broke it. The first group is about WHICH text a page contributes: a header
over a scanned table, a table typed one glyph per run. The second is the validator that
withheld two correct TRIN figures and could not repair two wrong ones.

No model, no API key, no network. The PDF tests skip when the archive is not present.

Run:  python -m pytest tests/test_mixed_pages.py -v
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pdftext import page_needs_ocr, text_layer_spaced           # noqa: E402
from schema import FinancialStatementExtraction                  # noqa: E402
from validate import (repair_current_maturity_from_long_term,    # noqa: E402
                      validate_against_document)

ARCHIVE = Path.home() / "FinancialReport"


def _pdf(name):
    ticker = name.split("_")[-1]
    path = ARCHIVE / ticker / f"{name}.pdf"
    if not path.exists():
        pytest.skip("the filing archive is not on this machine")
    return path


class _Page:
    width, height = 600.0, 800.0

    def __init__(self, images=()):
        self.images = list(images)


HEADER = ("PT CONTOH Tbk LAPORAN POSISI KEUANGAN STATEMENTS OF FINANCIAL POSITION\n"
          "31 Desember 2023 dan 2022 December 31, 2023 and 2022\n"
          "(Disajikan dalam Rupiah, kecuali dinyatakan lain) (Expressed in Rupiah)\n"
          "Catatan atas laporan keuangan terlampir merupakan bagian yang tidak "
          "terpisahkan dari laporan keuangan secara keseluruhan.\n")


# --- which text a page contributes ---------------------------------------------------

def test_a_text_header_over_a_scanned_table_is_ocrd():
    """PURA Q4 2023: ~500 characters of header, the figures an image underneath."""
    table_image = {"x0": 40, "x1": 560, "top": 150, "bottom": 500}
    assert page_needs_ocr(_Page([table_image]), HEADER)
    # The same header with the figures in the text layer is left alone ...
    with_figures = HEADER + "Jumlah aset 579.886.971.947 497.321.106.442\n" \
                            "Jumlah liabilitas 81.653.675.338 76.144.183.416\n" \
                            "Jumlah ekuitas 498.233.296.609 421.176.923.026\n"
    assert not page_needs_ocr(_Page([table_image]), with_figures)
    # ... and so is a page whose only image is a logo.
    logo = {"x0": 20, "x1": 80, "top": 20, "bottom": 60}
    assert not page_needs_ocr(_Page([logo]), HEADER)


def test_a_partly_glyph_spaced_page_is_ocrd_and_prose_is_not():
    spaced = HEADER + "\n".join(["P e m e g a n g S a h a m",
                                 "P T R a ja w a li In ti (R I) 1 5 ,2 8 %",
                                 "M a s y a r a k a t 5 9 ,0 6 %",
                                 "T o ta l 1 0 0 %"] * 3)
    assert text_layer_spaced(spaced)
    assert not text_layer_spaced(HEADER * 4)


def test_the_flag_turns_the_new_rule_off(monkeypatch):
    monkeypatch.setenv("OCR_MIXED_PAGES", "false")
    table_image = {"x0": 40, "x1": 560, "top": 150, "bottom": 500}
    assert not page_needs_ocr(_Page([table_image]), HEADER)


def test_pura_q4_2023_statement_pages_are_recognised_as_scanned_figures():
    import pdfplumber
    with pdfplumber.open(_pdf("Q4_2023_PURA")) as pdf:
        for n in range(9, 14):                       # pages 10-14
            page = pdf.pages[n]
            assert page_needs_ocr(page, page.extract_text() or ""), n + 1
        # The table of contents beside them carries no image and stays as text.
        assert not page_needs_ocr(pdf.pages[1], pdf.pages[1].extract_text() or "")


def test_a_glyph_spaced_balance_sheet_reaches_the_model_as_ocr_not_as_glyphs():
    """RCCC Q1 2026 page 5: rebuilt from word boxes it read "K a s d a n B a n k 4 3 2 3
    .2 9 6 .3 3 8", and the model answered 4.323.296.338 for 323.296.338."""
    from pagemd import page_markdown
    pdf = _pdf("Q1_2026_RCCC")
    built = page_markdown(str(pdf), [4], fallback={4: "OCR TEXT OF PAGE 5"})
    assert built[4] == "OCR TEXT OF PAGE 5"


# --- bank debt that looks alike ------------------------------------------------------

def _doc(*pages):
    return "\n".join(f"--- PAGE {i + 1} ---\n{text}" for i, text in enumerate(pages))


BALANCE_SHEET = """LIABILITAS JANGKA PENDEK
Bagian Liabilitas Jangka Panjang Jatuh Tempo dalam Satu Tahun
Utang Bank dan Lembaga
Keuangan Non-Bank 23 693.083.365 695.981.931
Jumlah Liabilitas Jangka Pendek 1.301.992.021 1.366.610.327
LIABILITAS JANGKA PANJANG
Dikurangi Bagian Jatuh Tempo dalam Satu Tahun
Utang Bank dan Lembaga
Keuangan Non-Bank 23 53.538.503 12.486.620
Jumlah Liabilitas Jangka Panjang 478.899.159 437.492.817"""

# The loan note repeats the current portion inside its long-term table.
NOTE = """23. UTANG BANK DAN LEMBAGA KEUANGAN NON-BANK
Liabilitas jangka panjang
Utang bank 746.621.868 708.468.551
Dikurangi bagian lancar
Utang bank 693.083.365 695.981.931"""


def test_a_figure_printed_under_its_own_section_is_not_called_non_current():
    """TRIN Q2 2025: the right current-maturity figure was ALSO in the note's long-term
    table, and the long-term check ran first and withdrew it."""
    e = FinancialStatementExtraction()
    e.utang_bank_jangka_pendek, e.utang_bank_bagian_lancar = 0, 693083365
    issues = validate_against_document(e, _doc(BALANCE_SHEET, NOTE))
    assert not [i for i in issues if i.rule == "wrong_section"]


def test_a_figure_printed_only_as_non_current_is_still_caught():
    e = FinancialStatementExtraction()
    e.utang_bank_jangka_pendek, e.utang_bank_bagian_lancar = 0, 53538503
    issues = validate_against_document(e, _doc(BALANCE_SHEET))
    assert [i for i in issues if i.rule == "wrong_section"]


def test_the_non_current_row_is_replaced_by_the_same_column_one_row_up():
    """TRIN Q1 2025: the model took 53.538.503 from "Dikurangi Bagian Jatuh Tempo"; the
    current-maturity row prints 693.083.365 in the same column."""
    e = FinancialStatementExtraction()
    e.utang_bank_jangka_pendek, e.utang_bank_bagian_lancar = 0, 53538503
    e.utang_bank = 53538503
    message = repair_current_maturity_from_long_term(e, _doc(BALANCE_SHEET))
    assert message and e.utang_bank_bagian_lancar == 693083365 and e.utang_bank == 693083365
    # A comparative read stays comparative: column 2 maps to column 2.
    e2 = FinancialStatementExtraction()
    e2.utang_bank_jangka_pendek, e2.utang_bank_bagian_lancar = 0, 12486620
    repair_current_maturity_from_long_term(e2, _doc(BALANCE_SHEET))
    assert e2.utang_bank_bagian_lancar == 695981931


def test_no_repair_when_the_current_maturity_row_is_ambiguous():
    two_rows = BALANCE_SHEET.replace(
        "Keuangan Non-Bank 23 693.083.365 695.981.931",
        "Keuangan Non-Bank 23 693.083.365 695.981.931\nUtang bank lain 11.111.111 22.222.222")
    e = FinancialStatementExtraction()
    e.utang_bank_jangka_pendek, e.utang_bank_bagian_lancar = 0, 53538503
    assert repair_current_maturity_from_long_term(e, _doc(two_rows)) is None
    assert e.utang_bank_bagian_lancar == 53538503
    # And a figure already under current maturity is never touched.
    ok = FinancialStatementExtraction()
    ok.utang_bank_bagian_lancar = 693083365
    assert repair_current_maturity_from_long_term(ok, _doc(BALANCE_SHEET)) is None


@pytest.mark.parametrize("name,pages,read,expected", [
    ("Q2_2025_TRIN", [5, 6, 7, 8, 9, 68, 69, 103], 178961211, 178961211),
    ("Q2_2024_TRIN", [5, 6, 7, 8, 9, 69, 70, 93], 698873355, 698873355),
    ("Q1_2025_TRIN", [5, 6, 7, 8, 9, 68, 69, 101], 53538503, 693083365),
    ("Q1_2026_TRIN", [5, 6, 7, 8, 9, 65, 95], 10065837, 714891426),
])
def test_trin_current_maturity_on_the_real_filings(name, pages, read, expected):
    """The four TRIN cells: two right answers that were withheld, two wrong rows."""
    from extract import build_document_text
    from pdftext import page_texts
    text = build_document_text(page_texts(str(_pdf(name)), [p - 1 for p in pages]),
                               condense=False)
    e = FinancialStatementExtraction()
    e.utang_bank_jangka_pendek, e.utang_bank_bagian_lancar, e.utang_bank = 0, read, read
    repair_current_maturity_from_long_term(e, text)
    assert e.utang_bank_bagian_lancar == expected
    assert not [i for i in validate_against_document(e, text) if i.rule == "wrong_section"]


# --- a failed statement call is retried, then recorded -----------------------------

def _run_with(monkeypatch, provider):
    import extract
    pdf = ROOT / "data" / "raw" / "Q1_2022_ARCI.pdf"
    if not pdf.exists():
        pytest.skip("the committed ARCI filing is not present")
    monkeypatch.setenv("GEMINI_INPUT_MODE", "markdown")
    monkeypatch.setattr(extract, "get_provider_chain", lambda: [provider])
    return extract.extract_from_pdf(str(pdf))


class _Flaky:
    """Fails the first `fail_times` calls -- the balance sheet is asked first -- and
    answers everything after."""
    name, model, input_mode, supports_tools = "stub:flaky", "flaky", "markdown", False

    def __init__(self, fail_times):
        self.fail_times = fail_times

    def complete(self, system, user, images=None, usage=None):
        from llm import LLMError
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMError("Gemini returned no candidates")
        return '{"currency": "USD", "reporting_scale": "FULL", "pendapatan": 1}'


def test_a_statement_call_that_fails_once_is_retried(monkeypatch):
    result = _run_with(monkeypatch, _Flaky(fail_times=1))
    assert not [i for i in result.issues if i["rule"] == "group_call_failed"]


def test_a_statement_call_that_keeps_failing_is_recorded_not_hidden(monkeypatch):
    """RCCC Q2 2023 lost eight fields this way and the CSV showed an ordinary partial."""
    result = _run_with(monkeypatch, _Flaky(fail_times=2))   # both attempts
    failures = [i for i in result.issues if i["rule"] == "group_call_failed"]
    assert len(failures) == 1 and failures[0]["message"].startswith("balance_sheet")
    assert "aset" in failures[0]["fields"]


class _BlindToTheImage:
    """Misses the profit line on the image and reads it from text, as APEX Q2 2024 did."""
    name, model, input_mode, supports_tools = "stub:vision", "vision", "image", False

    def __init__(self, image_answer):
        self.image_answer = image_answer
        self.text_prompts = []

    def complete(self, system, user, images=None, usage=None):
        if images:
            return self.image_answer
        self.text_prompts.append(user)
        return '{"laba_bersih": 335380, "pendapatan": 999}'


def _images_run(monkeypatch, provider):
    import extract
    pdf = ROOT / "data" / "raw" / "Q1_2022_ARCI.pdf"
    if not pdf.exists():
        pytest.skip("the committed ARCI filing is not present")
    monkeypatch.setattr(extract, "group_pages", lambda *a, **k: {"income": [0]})
    page = ("PT APEXINDO PRATAMA DUTA Tbk\n"
            "LAPORAN LABA RUGI DAN PENGHASILAN KOMPREHENSIF LAIN INTERIM\n"
            "(Dalam US Dolar Penuh) (In Full US Dollar)\n"
            "PENDAPATAN 22 42.578.385 33.136.394 REVENUES\n"
            "BEBAN LANGSUNG 23 (32.066.772) (23.247.979) DIRECT COSTS\n"
            "LABA SEBELUM PAJAK 524.395 839.143 INCOME BEFORE TAX\n"
            "LABA BERSIH PERIODE BERJALAN 335.380 1.565.823 NET INCOME FOR THE PERIOD")
    return extract._extract_from_images(str(pdf), [0], extract.ExtractorConfig(), provider,
                                        page_texts={0: page})


def test_a_headline_the_image_left_null_is_asked_from_the_page_text(monkeypatch):
    provider = _BlindToTheImage('{"currency": "USD", "reporting_scale": "FULL", '
                                '"pendapatan": 42578385, "laba_bersih": null}')
    result = _images_run(monkeypatch, provider)
    assert result.laba_bersih == 335380
    assert result.pendapatan == 42578385          # the image's answer is not overruled
    assert len(provider.text_prompts) == 1 and "laba_bersih" in provider.text_prompts[0]


def test_an_image_that_answered_every_headline_costs_no_text_call(monkeypatch):
    provider = _BlindToTheImage('{"currency": "USD", "reporting_scale": "FULL", '
                                '"pendapatan": 42578385, "laba_bersih": 1}')
    assert _images_run(monkeypatch, provider).laba_bersih == 1
    assert provider.text_prompts == []


# --- the comparative column --------------------------------------------------------

from validate import header_years, repair_comparative_columns          # noqa: E402

INCOME = """PT CONTOH Tbk
LAPORAN LABA RUGI DAN PENGHASILAN KOMPREHENSIF LAIN
Untuk Periode Sembilan Bulan yang Berakhir pada 30 September 2025 dan 2024 Ended September 30, 2025, and 2024
(Disajikan dalam Ribuan Rupiah)
Notes 2025 2024
PENJUALAN DAN PENDAPATAN 2,32 181.607.666 194.277.418 SALES AND REVENUES
Pemilik Entitas Induk 28.483.202 (45.211.769) Owners of The Parent
Kepentingan Nonpengendali 31b 2.612.801 (17.237.291) Non-Controlling Interest"""


def test_header_years_come_only_from_the_column_header_row():
    assert header_years(INCOME) == [2025, 2024]
    assert header_years("2025 2024\nKas 1.000.000 2.000.000") == [2025, 2024]
    # PTBA Q3 2022: the wrapped title names 2021 first while the columns run 2022, 2021.
    ptba = ("INTERIM PADA TANGGAL 30 SEPTEMBER 2022 DAN FINANCIAL POSITION AS AT\n"
            "31 DESEMBER 2021 30 SEPTEMBER 2022 AND 31 DECEMBER 2021\nNotes 2022 2021")
    assert header_years(ptba) == [2022, 2021]
    # TOTL Q3 2025: no column-header row at all, so nothing is decided.
    assert header_years("PADA TANGGAL-TANGGAL 30 SEPTEMBER 2025\nDAN 2024 (TIDAK DIAUDIT) "
                        "SEPTEMBER 30, 2025 AND 2024") == []


def test_a_spaced_parenthesis_keeps_its_sign():
    """TRIN Q2 2023 prints "( 230.537.354)": the repair took the right column but
    dropped the sign before this."""
    page = "Notes 2023 2022\nAktivitas Operasi ( 230.537.354) (66.612.336) Activities"
    e = FinancialStatementExtraction()
    e.kas_dari_aktivitas_operasi = -66612336
    repair_comparative_columns(e, {8: page}, 2023)
    assert e.kas_dari_aktivitas_operasi == -230537354


def test_a_figure_read_from_the_comparative_column_is_moved_to_the_current_one():
    """TRIN Q3 2025: revenue 194.277.418 and parent profit (45.211.769) were the 2024
    column, at confidence 1.0, because both are printed."""
    e = FinancialStatementExtraction()
    e.pendapatan, e.laba_bersih = 194277418, -45211769
    messages = repair_comparative_columns(e, {6: INCOME}, 2025)
    assert e.pendapatan == 181607666 and e.laba_bersih == 28483202
    assert len(messages) == 2


def test_a_current_figure_and_an_ambiguous_one_are_left_alone():
    e = FinancialStatementExtraction()
    e.pendapatan = 181607666                          # already current
    assert repair_comparative_columns(e, {6: INCOME}, 2025) == []
    # The comparative figure ALSO printed as a current amount elsewhere: not proven.
    other = "Ringkasan segmen\n2025 2024\nPendapatan segmen 194.277.418 100.000.000"
    e.pendapatan = 194277418
    assert repair_comparative_columns(e, {6: INCOME, 7: other}, 2025) == []
    assert e.pendapatan == 194277418
    # No year in the header: nothing to decide from.
    assert repair_comparative_columns(e, {6: INCOME.replace("2025", "x").replace("2024", "y")},
                                      2025) == []


def test_the_trin_q3_2025_pages_themselves():
    from pdftext import page_texts
    pdf = _pdf("Q3_2025_TRIN")
    texts = page_texts(str(pdf), [6])
    e = FinancialStatementExtraction()
    e.pendapatan, e.laba_bersih = 194277418, -45211769
    repair_comparative_columns(e, texts, 2025)
    assert (e.pendapatan, e.laba_bersih) == (181607666, 28483202)


def test_a_figure_also_printed_where_the_column_cannot_be_named_is_left_alone():
    """LSIP Q2 2024: the NCI (1.683) is on a balance sheet with no year row, and the
    same digits sit in another line's comparative column in the cash flow."""
    balance = "LAPORAN POSISI KEUANGAN\nKepentingan Nonpengendali (1.683.000) 21 (1.177.000)"
    cash = "Notes 2024 2023\naset tidak lancar lainnya (15.566.000) (1.683.000) non-current"
    e = FinancialStatementExtraction()
    e.kepentingan_non_pengendali = -1683000
    assert repair_comparative_columns(e, {4: balance, 8: cash}, 2024) == []
    assert e.kepentingan_non_pengendali == -1683000


# --- signs --------------------------------------------------

from validate import repair_printed_signs                                     # noqa: E402

CASH = "Notes 2025 2024\nAktivitas Operasi 32.613.471 ( 16.186.590) Activities"


def test_a_sign_the_row_prints_otherwise_is_corrected():
    """TRIN Q1 2025: positive this quarter, negative last; the model answered negative."""
    e = FinancialStatementExtraction()
    e.kas_dari_aktivitas_operasi = -32613471
    assert repair_printed_signs(e, {8: CASH}, 2025)
    assert e.kas_dari_aktivitas_operasi == 32613471


def test_an_unsigned_outflow_row_is_never_flipped():
    """A filer that writes outflows unsigned under "digunakan untuk" uses no
    parentheses on the row, so the printed sign proves nothing."""
    unsigned = "Notes 2025 2024\nKas neto digunakan untuk aktivitas operasi 32.613.471 16.186.590"
    e = FinancialStatementExtraction()
    e.kas_dari_aktivitas_operasi = -32613471
    assert repair_printed_signs(e, {8: unsigned}, 2025) == []
    assert e.kas_dari_aktivitas_operasi == -32613471
    # Nor a figure printed anywhere its column cannot be named.
    e.kas_dari_aktivitas_operasi = -32613471
    assert repair_printed_signs(e, {8: CASH, 9: "Ringkasan 32.613.471"}, 2025) == []


# --- components -----------------------------------------------------------------------

def test_two_cash_components_that_are_one_rows_two_periods_become_the_current_figure():
    """RCCC Q4 2022: "Kas dan bank 2.143.011.281 447.546.306" reported as two
    components, summed to 2.590.557.587 -- printed nowhere."""
    from validate import repair_components_across_columns
    page = "Notes 2022 2021\nKas dan bank 2d,3,25 2.143.011.281 447.546.306 Cash"
    e = FinancialStatementExtraction()
    e.kas_components = [2143011281, 447546306]
    assert repair_components_across_columns(e, {7: page}, 2022)
    assert e.kas == 2143011281 and e.kas_components is None
    # Real counterparty components on two lines are left alone.
    split = "Notes 2022 2021\nPihak berelasi 111.111 100.000\nPihak ketiga 222.222 200.000"
    e2 = FinancialStatementExtraction()
    e2.kas_components = [111111, 222222]
    assert repair_components_across_columns(e2, {7: split}, 2022) == []


def test_a_nil_statement_answer_does_not_beat_note_components():
    """TRIN Q2 2022: 0 from the balance sheet, four note lenders summing to the printed
    590.740.287 (reported in parentheses, so negative)."""
    from extract import derive_fields
    e = FinancialStatementExtraction()
    e.utang_bank_jangka_pendek, e.utang_bank_bagian_lancar = 0, 0
    e.utang_bank_bagian_lancar_components = [-7042862, -140722511, -1920640, -441054274]
    derive_fields(e)
    assert e.utang_bank_bagian_lancar == 590740287 and e.utang_bank == 590740287


# --- digits the page printed apart ---------------------------------------------------

def test_split_digits_join_only_when_the_page_printed_them_together():
    """5.711 touching pairs, 1.661 separated, none between: the geometry decides."""
    from numfmt import grouped_numbers, repair_digit_gaps
    assert grouped_numbers("Pinjaman bank 13 18.672.839.545 1 7.149.123.737") == \
        [18672839545, 17149123737]                        # GTRA: touching, one figure
    assert grouped_numbers("Kas 2,4,45,46 1  77.250.439 34.276.645") == [77250439, 34276645]
    assert grouped_numbers("Utang Bank 2,8&9  7.008.790.794 5.882.925.347") == \
        [7008790794, 5882925347]                          # TRUK: a note number
    assert "177250439" not in repair_digit_gaps("1  77.250.439")


def test_the_page_text_marks_separated_tokens():
    from pdftext import page_texts
    pdf = _pdf("Q3_2022_TRIN")
    text = page_texts(str(pdf), [4], use_ocr=False)[4]
    assert "1  77.250.439" in text


def test_a_stray_digit_glued_on_by_the_model_is_removed():
    from validate import repair_separated_lead_digits
    page = "Notes 2022 2021\nKas dan Setara Kas 2,4,45,46 1  77.250.439 34.276.645"
    e = FinancialStatementExtraction()
    e.kas = 177250439
    assert repair_separated_lead_digits(e, {4: page})
    assert e.kas == 77250439
    # A figure that IS printed is never touched.
    e.kas = 77250439
    assert repair_separated_lead_digits(e, {4: page}) == []


# --- a component that is not a loan ---------------------------------------------------

ADMR_LIKE = _doc("""LIABILITAS JANGKA PENDEK
Liabilitas sewa - bagian Lease liabilities
jangka pendek 18 101,091 963 - current portion
Utang bank - bagian Bank loans
jangka pendek 19 214,671 27,943 - current portion
Total liabilitas jangka pendek 900,000 800,000
LIABILITAS JANGKA PANJANG
Utang bank 19 943,113 685,080 Bank loans""")


def test_a_lease_added_to_a_bank_loan_is_removed():
    """ADMR Q2 2026: 214.671 bank + 101.091 lease reported as utang_bank."""
    from validate import repair_non_bank_component
    e = FinancialStatementExtraction()
    e.utang_bank_jangka_pendek, e.utang_bank_bagian_lancar = 214671, 101091
    e.utang_bank = 315762
    assert repair_non_bank_component(e, ADMR_LIKE)
    assert e.utang_bank == 214671


def test_a_tax_payable_reported_as_bank_debt_is_withheld():
    """LSIP Q3 2025 has no bank loan; the model reported "Utang pajak 177.362"."""
    doc = _doc("LIABILITAS JANGKA PENDEK\nUtang usaha 1.000.000 900.000\n"
               "Utang pajak 177.362 3,18 217.933 Taxes payable\n")
    e = FinancialStatementExtraction()
    e.utang_bank_jangka_pendek, e.utang_bank_bagian_lancar = 0, 177362
    assert [i for i in validate_against_document(e, doc) if i.rule == "non_bank_row"]


def test_a_real_bank_figure_is_never_called_non_bank():
    from validate import repair_non_bank_component
    e = FinancialStatementExtraction()
    e.utang_bank_jangka_pendek, e.utang_bank_bagian_lancar = 214671, 0
    assert repair_non_bank_component(e, ADMR_LIKE) == []
    assert not [i for i in validate_against_document(e, ADMR_LIKE) if i.rule == "non_bank_row"]


# --- a share count read from the paid-up amount -----------------------------------------

def test_a_share_count_taken_from_the_amount_column_is_replaced_by_the_count():
    """PURA: "Total 6.301.930.902 100% 315.096.545.100" -- shares, ownership, Rupiah.
    Read from the image, the model answered the Rupiah amount."""
    from validate import repair_share_amount_column
    page = "Pemegang Saham\nTotal 6.301.930.902 100% 315.096.545.100 Total"
    e = FinancialStatementExtraction()
    e.total_share = 315096545100
    assert repair_share_amount_column(e, {54: page})
    assert e.total_share == 6301930902
    # The count itself is left alone, and so is a figure on no such row.
    e.total_share = 6301930902
    assert repair_share_amount_column(e, {54: page}) == []
    e.total_share = 123456789
    assert repair_share_amount_column(e, {54: page}) == []


def test_the_amount_column_is_read_from_the_alternate_ocr_too():
    from pdftext import OCRText
    from validate import repair_share_amount_column
    text = OCRText("Total\n6.301.930.902\n100%\n315.096.545.100")
    text.alternate = "Total 6.301.930.902 100% 315.096.545.100 Tot"
    e = FinancialStatementExtraction()
    e.total_share = 315096545100
    repair_share_amount_column(e, {54: text})
    assert e.total_share == 6301930902


def test_the_group_image_route_is_off_by_default(monkeypatch):
    """Measured on 24 filings: neutral on GTRA/JPFA, eight PURA cells worse."""
    import extract, inspect
    monkeypatch.delenv("GROUP_IMAGE_FALLBACK", raising=False)
    assert '"GROUP_IMAGE_FALLBACK", "false"' in inspect.getsource(extract)


def test_a_share_count_scaled_by_the_rupiah_header_is_put_back():
    """TRIN Q4 2025, 2026-11-10: the model answered 4.424.040.000 for the printed
    4.424.040 under "(Disajikan dalam Ribuan Rupiah)"; grounding withheld it."""
    from validate import repair_share_count_scale
    page = ("(Disajikan dalam Ribuan Rupiah, kecuali dinyatakan lain)\n"
            "Sub-total 4.424.040 97,20% 442.404.118 Sub-total\n"
            "Saham treasuri 127.417 2,80% 12.741.660 Treasury share\n"
            "Total 4.551.457 100,00% 455.145.778 Total")
    e = FinancialStatementExtraction()
    e.saham_beredar, e.saham_treasuri, e.saham_ditempatkan = 4424040000, 127417000, 4551457
    assert len(repair_share_count_scale(e, {102: page})) == 2
    assert (e.saham_beredar, e.saham_treasuri, e.saham_ditempatkan) == (4424040, 127417, 4551457)
    # A count that is printed as it stands, or one with no such row, is left alone.
    e.total_share = 4551457000
    page_with_full = page + "\nJumlah saham 4.551.457.000"
    assert repair_share_count_scale(e, {102: page_with_full}) == []
    e.total_share = 7000000
    assert repair_share_count_scale(e, {102: page}) == []
