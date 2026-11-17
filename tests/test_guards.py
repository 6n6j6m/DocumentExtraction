"""
Fault injection: prove each guard catches the failure it exists for.

The happy path already scores 40/40, so a scorecard cannot demonstrate that the
validation, grounding and abstention layers do anything -- a system with all of them
removed would score identically on clean input. Safety machinery is only observable
when something goes wrong, so each test here breaks one specific thing and asserts
that the right guard fires.

Run:  python -m pytest tests/ -v
"""

import sys
from pathlib import Path

try:
    import pytest
except ImportError:                                   # pytest is optional
    class _Stub:                                      # minimal shim so the module
        @staticmethod                                 # imports and __main__ can run
        def skip(msg): raise RuntimeError(msg)
        @staticmethod
        def fixture(**kw):
            def deco(fn): return fn
            return deco
        class raises:
            def __init__(self, exc): self.exc = exc
            def __enter__(self): return self
            def __exit__(self, t, v, tb):
                if t is None: raise AssertionError(f"{self.exc.__name__} not raised")
                return issubclass(t, self.exc)
    pytest = _Stub()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from schema import FinancialStatementExtraction as F        # noqa: E402
from validate import validate, validate_against_document, ERROR  # noqa: E402
from confidence import score_extraction, apply_abstention    # noqa: E402
from extract import read_page_texts, build_document_text     # noqa: E402
from normalize import extract_fx_rate, to_idr, detect_scale   # noqa: E402
from page_select import select_from_page_texts                # noqa: E402

PDF = ROOT / "data" / "raw" / "Q1_2022_ARCI.pdf"

# ARCI Q1 2022, as printed in the filing (US Dollars).
TRUTH = dict(
    period_end_date="2022-03-31", aset=694671337, total_aset_lancar=73325265,
    kas=23125502, liabilitas=452486029, utang_bank=102357484,
    utang_bank_jangka_pendek=34220811, utang_bank_bagian_lancar=68136673,
    ekuitas=242262040, total_ekuitas=242185308, kepentingan_non_pengendali=-76732,
    pendapatan=80129305, laba_bersih=9450480, kas_dari_aktivitas_operasi=36388972,
    total_share=24835000000, currency="USD", reporting_scale="FULL",
    statement_scope="CONSOLIDATED",
)

NON_CURRENT_BANK_LOAN = 184336390   # the third "Utang bank" row, which must be excluded


@pytest.fixture(scope="module")
def document_text():
    if not PDF.exists():
        pytest.skip(f"{PDF.name} not present")
    return build_document_text(read_page_texts(str(PDF), [4, 5, 6, 7, 8, 9, 10, 11]))


def assess(extraction, document_text):
    issues = validate(extraction) + validate_against_document(extraction, document_text)
    scores = score_extraction(extraction, document_text, issues)
    abstained = apply_abstention(extraction, scores)
    return issues, scores, abstained


# --- baseline: the guards must not fire on a correct extraction -----------------

def test_correct_extraction_passes_cleanly(document_text):
    """No false positives: a right answer must not be validated or abstained away."""
    e = F(**TRUTH)
    issues, scores, abstained = assess(e, document_text)
    assert issues == [], f"unexpected issues: {[i.message for i in issues]}"
    assert abstained == [], f"wrongly abstained: {abstained}"
    assert scores["aset"].grounded is True


def test_derived_field_is_not_punished_for_being_absent(document_text):
    """utang_bank is a SUM, so it is correctly not printed anywhere.

    Grading it on its own grounding would abstain on the right answer -- a real bug
    this test exists to prevent recurring.
    """
    e = F(**TRUTH)
    _, scores, abstained = assess(e, document_text)
    assert "utang_bank" not in abstained
    assert scores["utang_bank"].confidence >= 0.9


# --- injected faults ------------------------------------------------------------

def test_hallucinated_value_is_caught(document_text):
    """A figure not printed in the filing must not survive to the output."""
    e = F(**{**TRUTH, "kas": 88888888})
    _, scores, abstained = assess(e, document_text)
    assert scores["kas"].grounded is False
    assert "kas" in abstained
    assert e.kas is None, "abstention must remove the value, not merely flag it"


def test_wrong_but_real_row_is_caught(document_text):
    """The hard case: a value copied from the wrong row.

    184.336.390 IS printed in the filing, so grounding verifies it. Only its section
    distinguishes it, which is what validate_against_document checks.
    """
    e = F(**{**TRUTH, "utang_bank_bagian_lancar": NON_CURRENT_BANK_LOAN,
             "utang_bank": 34220811 + NON_CURRENT_BANK_LOAN})
    issues, scores, abstained = assess(e, document_text)
    assert any(i.rule == "wrong_section" for i in issues)
    assert "utang_bank" in abstained


def test_unbalanced_balance_sheet_is_caught(document_text):
    e = F(**{**TRUTH, "liabilitas": 400000000})
    issues, _, abstained = assess(e, document_text)
    assert any(i.rule == "balance_sheet_identity" for i in issues)
    assert {"aset", "liabilitas", "total_ekuitas"} <= set(abstained)


def test_containment_violation_is_caught(document_text):
    e = F(**{**TRUTH, "kas": 99999999999})
    issues, _, _ = assess(e, document_text)
    assert any(i.rule == "containment" for i in issues)


def test_fractional_share_count_is_caught(document_text):
    e = F(**{**TRUTH, "total_share": 24835000000.5})
    issues, _, _ = assess(e, document_text)
    assert any(i.rule == "share_count" for i in issues)


# --- conversion -----------------------------------------------------------------

def test_fx_rate_comes_from_the_filing():
    fx = extract_fx_rate(str(PDF))
    assert fx is not None and fx.source == "disclosed_rate_table"
    assert abs(fx.idr_per_usd - 14347.2) < 1      # BI middle rate 31 Mar 2022: 14,349
    assert "1.000 Rupiah" in fx.evidence


def test_share_count_is_never_converted():
    """Scaling a share count corrupts every per-share metric by ~14,000x."""
    e = F(**TRUTH)
    values = to_idr(e, pdf_path=str(PDF))["values"]
    assert values["total_share"] == TRUTH["total_share"]
    assert values["aset"] > TRUTH["aset"] * 10000     # money WAS converted


def test_usd_without_a_rate_refuses_rather_than_guesses():
    e = F(**{**TRUTH, "currency": "USD"})
    with pytest.raises(ValueError):
        to_idr(e, fx=None, pdf_path=None)


# --- generalisation to other issuers ---------------------------------------------

def test_scale_is_read_from_the_header_not_guessed():
    """A missed "dalam ribuan" is a 1000x error in every figure."""
    assert detect_scale("(Disajikan dalam ribuan Rupiah)") == "THOUSANDS"
    assert detect_scale("(Expressed in millions of Rupiah)") == "MILLIONS"
    assert detect_scale("(Disajikan dalam milyar Rupiah)") == "BILLIONS"


def test_a_header_naming_only_a_currency_means_full_units():
    """Absence of a scale word in the header is an answer, not a silence.

    The header is the one place a filing states its scale, so a header that names a
    currency and no scale says "whole units". Reading that as "unknown" leaves the
    expensive half of the mistake uncaught -- see the next test.
    """
    assert detect_scale("(Disajikan dalam Dolar Amerika Serikat)") == "FULL"
    assert detect_scale("(Expressed in Rupiah, unless otherwise stated)") == "FULL"


def test_no_header_at_all_is_still_unknown():
    """An unreadable page must not be mistaken for a page that says "full units"."""
    assert detect_scale("Total Aset 111.111.111") is None
    assert detect_scale("") is None


def test_a_header_without_the_verb_is_still_a_header():
    """DSNG writes "(Dalam jutaan Rupiah, ...)" with no "Disajikan" in front of it."""
    assert detect_scale("(Dalam jutaan Rupiah, kecuali dinyatakan lain/"
                        "In millions of Rupiah, unless otherwise specified)") == "MILLIONS"
    # Admitting "(in" must not admit every parenthetical that starts with it: without a
    # currency this is not a statement of units, and reading it as FULL would override
    # a correct scale.
    assert detect_scale("(in accordance with PSAK 1)") is None
    assert detect_scale("(dalam hal ini Direksi)") is None


def test_a_header_with_a_subject_before_the_verb_is_still_a_header():
    """AKRA 2022 - Q3 2023: "(Angka disajikan ..." was missed, and the par-value line
    "(dalam Rupiah penuh)" further down the equity page was read as the header instead."""
    page = ("LAPORAN POSISI KEUANGAN KONSOLIDASIAN CONSOLIDATED STATEMENT OF\n"
            "Tanggal 31 Maret 2023 As of March 31, 2023\n"
            "(Angka disajikan dalam ribuan Rupiah, (Amounts are expressed in thousands of Rupiah,\n"
            "kecuali dinyatakan lain) unless otherwise stated)\n"
            "EKUITAS EQUITY\n"
            "Modal saham - nilai nominal\n"
            "Rp20 per saham Capital stock - Rp20 par value\n"
            "(dalam Rupiah penuh) (in full Rupiah)\n")
    assert detect_scale(page) == "THOUSANDS"
    assert detect_scale("(Amounts are expressed in millions of Rupiah)") == "MILLIONS"
    assert detect_scale("(Angka dalam tabel ini disusun ulang)") is None


def test_printed_scale_overrides_the_model():
    """The header is unambiguous; the model's answer is not. The header wins."""
    e = F(**{**TRUTH, "currency": "IDR", "reporting_scale": "FULL"})
    result = to_idr(e, document_text="(Disajikan dalam ribuan Rupiah)")
    assert result["scale_applied"] == 1000
    assert any("header says THOUSANDS" in w for w in result["warnings"])


def test_the_header_also_overrides_a_scale_the_model_invented():
    """The direction that actually cost money.

    ARCI's header says nothing about scale in any quarter of any year, yet the model
    answered THOUSANDS on three of its fourteen filings and every figure in those rows
    came out a thousandfold too large. reporting_scale is the one field grounding
    cannot check -- a scale is a word, not a number -- so the header has to be
    authoritative in BOTH directions or this passes silently.
    """
    e = F(**{**TRUTH, "currency": "IDR", "reporting_scale": "THOUSANDS"})
    result = to_idr(e, document_text="(Disajikan dalam Rupiah, kecuali dinyatakan lain)")
    assert result["scale_applied"] == 1
    assert any("header says FULL" in w for w in result["warnings"])


def test_pages_declaring_different_scales_say_so():
    """A note tabulated at another scale is not resolved silently."""
    e = F(**{**TRUTH, "currency": "IDR", "reporting_scale": "FULL"})
    result = to_idr(e, document_text="(Disajikan dalam Rupiah)\n"
                                     "(Disajikan dalam ribuan Rupiah)")
    assert result["scale_applied"] == 1
    assert any("more than one scale" in w for w in result["warnings"])


def test_a_text_layer_shredded_into_single_characters_is_not_trusted():
    """The failure that made one issuer look like two different systems.

    PT Grahaprima files Q1 2024, Q1 2025 and Q1 2026 typeset so that every glyph is
    its own text run; pdfplumber returns the balance sheet a character at a time with
    the columns interleaved. Nothing else about the filing changed -- the other
    quarters of the same issuer come out clean -- and the page is perfectly legible
    to the model reading the image. But the text layer is what every deterministic
    check verifies against, so grounding failed on every figure at once and the
    confidence layer withdrew twelve fields that had been read correctly.

    Length, letters and encoding all look fine on such a page, which is why the two
    existing tests pass it. It has to be recognised on its shape.
    """
    from pdftext import text_layer_usable

    shredded = ("T o ta l A s e t L a n c a r 2 0 .4 0 9 .3 0 1 .3\n"
                "K a s d a n s e ta ra k a s 1 5 7 .7 2 3 .6 7 7 .7\n"
                "P iu ta n g u s a h a - n e to 2 1 .8 7 9 .9 0 2 .8\n") * 12
    assert not text_layer_usable(shredded)


def test_a_dense_ordinary_page_is_still_trusted():
    """The detector must not send readable pages to OCR.

    Two ratios have to agree before a page is called shredded, because either alone
    has honest counter-examples: a note page of short bilingual labels scores high on
    the first, and a page of dates and note references scores high on the second.
    """
    from pdftext import text_layer_usable

    ordinary = ("PT CONTOH TBK DAN ENTITAS ANAKNYA\n"
                "LAPORAN POSISI KEUANGAN KONSOLIDASIAN\n"
                "(Disajikan dalam Rupiah, kecuali dinyatakan lain)\n"
                "Kas dan setara kas 2c,4 20.409.301.364 15.284.771.902\n"
                "Piutang usaha - neto 5 157.723.677.712 143.006.912.550\n") * 12
    assert text_layer_usable(ordinary)


def test_a_bank_row_is_found_whatever_the_issuer_calls_it():
    """The validator must not memorise the wording the prompt was taught to generalise.

    The extraction prompt describes bank debt by meaning, so that "Pinjaman" and
    "Utang bank" and "Bank loans" all reach the same field. The position check behind
    it still matched the single string "Utang bank", which disarmed it completely for
    an issuer that says "Pinjaman bank": the section map came back empty on all
    fifteen of that issuer's filings and the warning saying so fired every time.

    A note reference between the label and the figure, and a leading digit the text
    layer split off, both have to survive too -- reading "3.048.092.371" out of
    "Pinjaman bank 14 4 3.048.092.371" would report a wrong-section ERROR against a
    value that was right.
    """
    from validate import _bank_rows_by_section

    text = ("LIABILITAS JANGKA PENDEK\n"
            "Pinjaman bank jangka pendek 10 17.729.771.107 17.744.025.136\n"
            "Liabilitas jangka panjang yang jatuh tempo dalam satu tahun:\n"
            "Pinjaman bank 14 4 3.048.092.371 2 4.611.346.132\n")
    rows = _bank_rows_by_section(text)
    assert 17_729_771_107 in rows["short_term"]
    assert 43_048_092_371 in rows["current_maturity"]


def test_a_title_behind_the_translation_notice_is_still_found():
    """LSIP opens every page with a translation notice and a bilingual company name.

    Its statement titles then start around character 248, and a 250-character title
    region cut them mid-word -- every LSIP filing fell back to its first ten pages. The
    notice identifies nothing, so it is removed before the region is measured.
    """
    from page_select import select_from_page_texts, classify_pages
    notice = ("The original interim consolidated financial statements included herein\n"
              "are in Indonesian language.\n"
              "PT PERUSAHAAN PERKEBUNAN LONDON SUMATRA INDONESIA Tbk PT PERUSAHAAN PERKEBUNAN\n"
              "LONDON SUMATRA INDONESIA Tbk DAN ENTITAS ANAKNYA AND ITS SUBSIDIARIES\n")
    pages = (["cover"] * 3
             + [notice + "LAPORAN POSISI KEUANGAN KONSOLIDASIAN INTERIM"] * 2
             + [notice + "LAPORAN LABA RUGI DAN PENGHASILAN KOMPREHENSIF LAIN"]
             + [notice + "LAPORAN ARUS KAS KONSOLIDASIAN INTERIM"]
             + ["notes"] * 20)
    assert len(notice) > 200, "the test must actually push the title past the region"
    selection = select_from_page_texts(pages)
    assert selection.method == "keyword_match" and selection.pages[0] == 3
    groups = classify_pages({n: pages[n] for n in selection.pages})
    assert groups["income"] == [5] and groups["cash_flow"][0] == 6


def test_a_title_split_across_bilingual_columns_is_still_found():
    """TLDN and PTBA print the Indonesian title in two halves around the English one."""
    from page_select import select_from_page_texts, classify_pages
    split = ("PT TELADAN PRIMA AGRO TBK\n"
             "LAPORAN POSISI CONSOLIDATED STATEMENT OF\n"
             "KEUANGAN KONSOLIDASIAN FINANCIAL POSITION\n")
    pages = ["cover"] * 4 + [split, "LAPORAN POSISI KEUANGAN KONSOLIDASIAN (lanjutan)"] + ["notes"] * 20
    selection = select_from_page_texts(pages)
    assert selection.pages[0] == 4, "the first balance-sheet page carries cash and current assets"
    assert classify_pages({n: pages[n] for n in selection.pages})["balance_sheet"][0] == 4


def test_a_title_extracted_without_spaces_is_still_found():
    """PGAS Q4 2023's text layer has no spaces at all, notice included:
    "LAPORANPOSISIKEUANGAN", "STATEMENTOFPROFITORLOSS". No title matched, selection fell
    back to the cover and auditor's report, and nine of ten fields came back empty."""
    from page_select import select_from_page_texts, classify_pages
    notice = ("Theoriginalconsolidatedfinancialstatementsincludedherein\n"
              "areintheIndonesianlanguage.\n"
              "PTPERUSAHAANGASNEGARATBK\nDANENTITASANAK/ANDITSSUBSIDIARIES\nHalaman1/1Page\n")
    pages = (["cover"] * 14
             + [notice + "LAPORANPOSISIKEUANGAN CONSOLIDATED\nKONSOLIDASIAN "
                         "STATEMENTOFFINANCIALPOSITION"] * 2
             + [notice + "LAPORANLABARUGI CONSOLIDATED\nDANPENGHASILANKOMPREHENSIFLAIN "
                         "STATEMENTOFPROFITORLOSS"]
             + [notice + "LAPORANARUSKAS CONSOLIDATED\nKONSOLIDASIAN STATEMENTOFCASHFLOWS"]
             + ["notes"] * 20)
    selection = select_from_page_texts(pages)
    assert selection.method == "keyword_match" and selection.pages[0] == 14
    groups = classify_pages({n: pages[n] for n in selection.pages})
    assert groups["balance_sheet"] == [14, 15] and groups["income"] == [16]
    assert groups["cash_flow"] == [17]


def test_a_cash_flow_page_titled_as_notes_after_the_statements_is_still_selected():
    """ENRG Q1 2023 heads its cash-flow page with the notes title and prints it after the
    equity statement, so the span of titled pages ended one page short of it."""
    from page_select import _untitled_cash_flow_after, classify_pages
    notes_head = "CATATAN ATAS LAPORAN KEUANGAN NOTES TO THE CONSOLIDATED\n"
    titles = (["cover"] * 2 + ["LAPORAN POSISI KEUANGAN KONSOLIDASIAN"] * 2
              + ["LAPORAN LABA RUGI KONSOLIDASIAN", "LAPORAN PERUBAHAN EKUITAS KONSOLIDASIAN"]
              + [notes_head] * 4)
    layer = {n: t for n, t in enumerate(titles)}
    # As ENRG's text layer has it: the heading broken across lines by the English half.
    layer[6] = (notes_head + "ARUS KAS DARI CASH FLOWS FROM\nAKTIVITAS OPERASI OPERATING ACTIVITIES\n"
                "Arus Kas Neto Diperoleh dari Net Cash Provided by\nAktivitas Operasi 28.619.851\n"
                "ARUS KAS DARI CASH FLOWS FROM\nAKTIVITAS INVESTASI INVESTING ACTIVITIES")
    layer[7] = notes_head + "1. UMUM\nPerusahaan didirikan berdasarkan akta"
    span = [2, 3, 4, 5]
    assert _untitled_cash_flow_after(span, titles, layer) == [6]
    assert classify_pages({n: layer[n] for n in span + [6]})["cash_flow"] == [6]
    # A titled cash-flow page in the span means nothing is added.
    titles[5] = "LAPORAN ARUS KAS KONSOLIDASIAN"
    assert _untitled_cash_flow_after(span, titles, layer) == []
    # A notes page that is not a cash-flow statement is not added either.
    titles[5] = "LAPORAN PERUBAHAN EKUITAS KONSOLIDASIAN"
    layer[6] = notes_head + "1. UMUM\nPerusahaan didirikan"
    assert _untitled_cash_flow_after(span, titles, layer) == []


def test_a_note_mentioning_a_statement_is_not_a_title():
    """Widening the region was rejected because notes mention the statements too."""
    from page_select import _is_statement_title, _title_head
    note = ("5. KAS DAN SETARA KAS\n" + "Rincian kas dan setara kas adalah sebagai berikut " * 6
            + "sebagaimana disajikan dalam laporan posisi keuangan konsolidasian")
    assert not _is_statement_title(_title_head(note))


def test_older_balance_sheet_wording_is_still_found():
    """Some issuers still title the balance sheet "Neraca"."""
    pages = ["cover"] * 3 + ["NERACA KONSOLIDASIAN\n\nPT Contoh Tbk"] + ["notes"] * 20
    assert 3 in select_from_page_texts(pages).matched_pages


def test_unmatched_section_headings_warn_instead_of_passing_silently(document_text):
    """If the wrong-row guard cannot run, it must say so.

    An issuer wording its headings differently would otherwise skip the check while
    confidence stayed high -- the guard disabled without anyone noticing.
    """
    e = F(**TRUTH)
    issues = validate_against_document(e, "Utang bank 34.220.811\nUtang bank 68.136.673")
    assert any(i.rule == "section_map_incomplete" for i in issues)


def test_bank_sections_resolve_for_a_second_issuer():
    """The bank-debt guard must work on an issuer it was not developed against.

    JPFA files the current portion of its long-term loans under the CURRENT
    liabilities heading while still labelling the row "Utang bank jangka panjang",
    where ARCI uses an explicit "Bagian lancar" sub-heading. Both must resolve, and
    in both cases the genuinely non-current row must land in `long_term` so the
    wrong-row check can exclude it.
    """
    from validate import _bank_rows_by_section
    from page_select import select_statement_pages

    for ticker in ("ARCI", "JPFA"):
        pdf = ROOT / "data" / "raw" / f"Q1_2022_{ticker}.pdf"
        if not pdf.exists():
            continue
        text = build_document_text(
            read_page_texts(str(pdf), select_statement_pages(str(pdf)).pages))
        rows = _bank_rows_by_section(text)
        assert "short_term" in rows, f"{ticker}: no current-liabilities section found"
        # Asserted structurally rather than on fixed amounts: the figures differ by
        # issuer and period, but no amount may appear in two sections at once, which
        # is what a heading being stolen by the wrong pattern would produce.
        seen = [v for values in rows.values() for v in values]
        assert len(seen) == len(set(seen)), f"{ticker}: a row landed in two sections: {rows}"


def test_a_figure_found_under_no_heading_is_unverified_not_wrong():
    """wrong_section must be proven, not inferred from absence.

    PTBA prints its current portion of long-term bank borrowings as "Pinjaman bank 100"
    under "Bagian jangka pendek dari liabilitas jangka panjang". The model read 100
    correctly; 100 carries no thousands separator, so it never entered the section map,
    and the old rule reported the correct value as copied from the wrong row. A value
    printed under no heading at all is unverifiable -- a warning, not an error.
    """
    e = F(**{**TRUTH, "utang_bank_jangka_pendek": 1_950_000, "utang_bank_bagian_lancar": 100})
    text = ("LIABILITAS JANGKA PENDEK\n"
            "Pinjaman bank jangka pendek 1.950.000 20 1.397.680\n"
            "Bagian jangka pendek dari\n"
            "liabilitas jangka panjang:\n"
            "Pinjaman bank 100 20 -\n"
            "LIABILITAS JANGKA PANJANG\n"
            "Liabilitas jangka panjang setelah bagian lancar:\n"
            "Pinjaman bank 1.277.425 20 -\n")
    issues = validate_against_document(e, text)
    assert not any(i.rule == "wrong_section" for i in issues), [i.message for i in issues]
    assert any(i.rule == "section_map_incomplete" and "utang_bank_bagian_lancar" in i.fields
               for i in issues)

    # The case the rule exists for still fires: a long-term figure reported as current.
    wrong = F(**{**TRUTH, "utang_bank_jangka_pendek": 1_950_000,
                 "utang_bank_bagian_lancar": 1_277_425})
    assert any(i.rule == "wrong_section" for i in validate_against_document(wrong, text))


def test_missing_long_term_section_does_not_crash():
    """A filing whose non-current section falls outside the selected pages.

    JPFA Q1 2022 hit exactly this: `rows` had no "long_term" key, and the exclusion
    check iterated None. Absent must mean "nothing to exclude", not a crash midway
    through an extraction that had already cost three API calls.
    """
    e = F(**TRUTH)
    text = ("Liabilitas Jangka Pendek\n"
            "Utang bank jangka pendek 34.220.811\n"
            "Bagian lancar atas liabilitas jangka panjang:\n"
            "Utang bank 68.136.673\n")
    issues = validate_against_document(e, text)      # must not raise
    assert not any(i.severity == ERROR for i in issues)


def test_grounding_survives_a_broken_text_layer():
    """A figure split by the PDF's own spacing is still present in the document.

    CPIN extracts "14.406" as "1 4.406". Reading that as absent made the guard
    abstain on a correctly extracted non-controlling interest -- and because equity
    is derived from it, the equity figure was lost too. A false negative here is
    expensive: it discards right answers.
    """
    from confidence import check_grounding
    text = "Kepentingan Nonpengendali 1 4.406 2,19 1 4.711 Noncontrolling Interests"
    assert check_grounding(14406, text) is True
    # Repairing the gaps must not start accepting figures that are simply not there.
    assert check_grounding(99999999, text) is False


# --- parsing and defaults --------------------------------------------------------

def test_indonesian_number_strings_are_parsed_correctly():
    """A model that echoes the filing's own formatting must not shift the magnitude.

    Deciding whether a dot is a separator by counting dots gets a single group wrong:
    "694.671" read as a decimal understates the figure by a thousand, and a
    parenthesised negative silently came back positive.
    """
    from extract import _coerce_numbers
    assert _coerce_numbers({"aset": "694.671.337"})["aset"] == 694671337
    assert _coerce_numbers({"aset": "694.671"})["aset"] == 694671
    assert _coerce_numbers({"aset": "15.000,50"})["aset"] == 15000.50
    assert _coerce_numbers({"aset": "(76.732)"})["aset"] == -76732
    assert _coerce_numbers({"aset": "tidak ada"})["aset"] is None


def test_balance_check_needs_total_equity_to_run():
    """The identity holds on TOTAL equity, so it must not fall back to the parent share.

    Substituting `ekuitas` when `total_ekuitas` is missing dropped `liabilitas` from
    the sum entirely and reported a perfectly good balance sheet as broken.
    """
    from extract import derive_fields
    e = F(aset=100, liabilitas=60, ekuitas=40, total_ekuitas=None)
    assert not any("does not balance" in w for w in derive_fields(e))


def test_share_capital_split_across_classes_is_summed_and_not_punished():
    """An issuer with Seri A and Seri B prints a count per class and no total.

    ARCI issues one class, so a directly-read count was all the system ever needed.
    JPFA issues two (8.814.985.201 + 2.911.590.000), and their sum is nowhere in the
    filing -- so grounding the total verbatim would abstain on the right answer, the
    same trap utang_bank fell into.
    """
    from extract import derive_fields
    text = ("Modal ditempatkan dan disetor - Issued and fully paid -\n"
            "8.814.985.201 saham Seri A\n"
            "2.911.590.000 saham Seri B\n")
    e = F(total_share_components=[8814985201, 2911590000], currency="IDR",
          reporting_scale="MILLIONS")
    derive_fields(e)
    assert e.total_share == 11726575201

    _, scores, abstained = assess(e, text)
    assert "total_share" not in abstained
    assert scores["total_share"].confidence >= 0.9
    assert scores["total_share_components"].grounded is True


def test_an_invented_share_class_is_still_caught():
    """Summing components must not become a way to smuggle one in."""
    text = "8.814.985.201 saham Seri A\n2.911.590.000 saham Seri B\n"
    e = F(total_share_components=[8814985201, 7777777777], currency="IDR")
    _, scores, abstained = assess(e, text)
    assert scores["total_share_components"].grounded is False
    assert "total_share_components" in abstained


def test_missing_currency_refuses_rather_than_assuming_idr():
    """An abstained currency must stop normalisation, not default to no conversion.

    Assuming IDR for a filing that is actually in USD understates every figure by the
    exchange rate -- roughly 14,000x -- with nothing but a warning to show for it.
    """
    e = F(**{**TRUTH, "currency": None})
    with pytest.raises(ValueError):
        to_idr(e, pdf_path=str(PDF))


def test_ground_truth_sheet_must_match_the_ticker():
    """A copied workbook that was never re-labelled must not be scored against.

    These sheets are made by copying an existing one; a copy still naming the issuer
    it came from scores one company's extraction against another's figures, and every
    field fails for a reason that appears nowhere in the output.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "scripts" / "run_eval.py")
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)

    xlsx = ROOT / "data" / "ground_truth" / "ARCI.xlsx"
    if not xlsx.exists():
        pytest.skip("ARCI.xlsx not present")
    with pytest.raises(ValueError):
        run_eval.load_ground_truth(xlsx, "Q1 2022", ticker="JPFA")
    # ...and the matching ticker still loads.
    assert run_eval.load_ground_truth(xlsx, "Q1 2022", ticker="ARCI")["aset"]


# --- failure classification -----------------------------------------------------

def test_failure_kinds_are_distinguished():
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "scripts" / "run_eval.py")
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)

    truth = 694671337
    assert run_eval.classify_failure(truth * 1000, truth, None) == "wrong_scale_1e3"
    assert run_eval.classify_failure(truth, -truth, None) == "wrong_sign"
    assert run_eval.classify_failure(truth * 14347, truth, None) == "wrong_currency_conversion"
    assert run_eval.classify_failure(truth * 1.01, truth, None) == "wrong_near_miss"
    assert run_eval.classify_failure(123, truth, False) == "hallucinated"


def test_an_annual_column_is_recognised_as_q4():
    """The share-price script must not skip a quarter because the sheet renames it.

    Every workbook in data/ground_truth labels its annual column "TAHUNAN 2024" rather
    than "Q4 2024" -- for every year except 2025, which uses the Q4 spelling. A parser
    that only knew "Q4" found no fourth quarter at all for 2020-2024 and quietly priced
    three quarters a year instead of four. Nothing failed; the columns just stayed empty.

    Both spellings must collapse to the same tuple, because the price is looked up under
    one and written into a column headed the other.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fetch_share_prices", ROOT / "scripts" / "fetch_share_prices.py")
    prices = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prices)

    assert prices.parse_period("TAHUNAN 2024") == ("Q4", 2024)
    assert prices.parse_period("Q4 2024") == prices.parse_period("TAHUNAN 2024")
    assert prices.parse_period("Q1_2024") == ("Q1", 2024)
    # A label is not a period. Matching one would write a price into a data row.
    assert prices.parse_period("Harga saham rupiah") is None
    assert prices.parse_period("2024") is None


def test_an_empty_window_falls_back_to_any_session_in_the_same_month(monkeypatch):
    """A suspension can leave nothing within twelve days of the 17th. The month is then
    read from the 1st in order and its first session prices the period -- nothing from
    the month before or after ever does."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fetch_share_prices", ROOT / "scripts" / "fetch_share_prices.py")
    prices = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prices)
    from datetime import date
    today = date(2026, 1, 1)
    target = date(2024, 6, 17)
    series = {date(2024, 6, 2): 100.0, date(2024, 6, 3): 101.0, date(2024, 7, 1): 120.0}
    with pytest.raises(prices.PriceUnavailable):
        prices.close_nearest(series, target, today=today)
    assert prices.close_in_month(series, target, today=today) == (date(2024, 6, 2), 100.0)
    with pytest.raises(prices.PriceUnavailable):
        prices.close_in_month({date(2024, 5, 31): 1.0, date(2024, 7, 1): 2.0}, target,
                              today=today)
    # One month back, walking from its end; never the month after.
    assert prices.close_last_in_month({date(2024, 5, 30): 1.0, date(2024, 5, 31): 2.0,
                                       date(2024, 7, 1): 3.0}, date(2024, 5, 31),
                                      today=today) == (date(2024, 5, 31), 2.0)

    # The collector uses the fallback only when the window is empty, and says so.
    calls = []

    def fake_fetch(ticker, start, end):
        calls.append((start, end))
        window = {d: v for d, v in series.items() if start <= d <= end}
        if not window:
            raise prices.PriceUnavailable("no trading days for TEST.JK in the window")
        return window

    monkeypatch.setattr(prices, "fetch_daily_closes", fake_fetch)
    monkeypatch.setattr(prices.time, "sleep", lambda s: None)
    row = prices.collect("TEST", [("Q1", 2024)])[0]
    assert row["price"] == 100.0 and row["price_date"] == "2024-06-02"
    assert "first session of June 2024" in row["note"]
    assert calls[-1] == (date(2024, 6, 1), date(2024, 6, 30))
    blank = prices.collect("TEST", [("Q1", 2024)], month_fallback=False)[0]
    assert blank["price"] == ""


def test_a_17th_not_yet_reached_is_priced_provisionally_from_the_1st(monkeypatch):
    """On 2 November 2026 Q3's 17 November has not come. The month is read from the 1st
    and its first FINAL close is used, marked provisional; with none yet, the previous
    month's last session. Today's bar counts only after 17:00 Jakarta time, and a month
    not yet started stays in the future."""
    import importlib.util
    from datetime import date, datetime
    spec = importlib.util.spec_from_file_location(
        "fetch_share_prices", ROOT / "scripts" / "fetch_share_prices.py")
    prices = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prices)

    jkt = prices.JAKARTA
    assert prices.last_final_day(datetime(2026, 11, 2, 15, 4, tzinfo=jkt)) == date(2026, 11, 1)
    assert prices.last_final_day(datetime(2026, 11, 2, 17, 5, tzinfo=jkt)) == date(2026, 11, 2)

    series = {date(2026, 10, 30): 1.0, date(2026, 11, 2): 1400.0, date(2026, 11, 3): 1410.0}
    monkeypatch.setattr(prices, "fetch_daily_closes", lambda t, a, b: {
        d: v for d, v in series.items() if a <= d <= b})
    monkeypatch.setattr(prices.time, "sleep", lambda s: None)

    # Before 17:00 on the 2nd: no final close in November yet, so October's LAST session.
    monkeypatch.setattr(prices, "last_final_day", lambda: date(2026, 11, 1))
    row = prices.collect("TEST", [("Q3", 2026)])[0]
    assert row["price"] == 1.0 and row["price_date"] == "2026-10-30"
    assert "last session of October 2026" in row["note"] and "PROVISIONAL" in row["note"]
    # The 3rd: the 2nd is the first final close of November.
    monkeypatch.setattr(prices, "last_final_day", lambda: date(2026, 11, 3))
    row = prices.collect("TEST", [("Q3", 2026)])[0]
    assert row["price"] == 1400.0 and row["price_date"] == "2026-11-02"
    assert row["note"].startswith("PROVISIONAL") and "--overwrite" in row["note"]
    # Q4 2026 is priced in May 2027: not started, still the future.
    assert "in the future" in prices.collect("TEST", [("Q4", 2026)])[0]["note"]
    # With the fallback off, a 17th not yet reached stays blank.
    assert "in the future" in prices.collect("TEST", [("Q3", 2026)],
                                             month_fallback=False)[0]["note"]


def test_the_nearest_session_to_the_17th_prices_the_period():
    """Either side of the 17th, whichever is nearer; the earlier one on a tie; never a
    session that has not happened yet."""
    import importlib.util
    from datetime import date
    spec = importlib.util.spec_from_file_location(
        "fetch_share_prices", ROOT / "scripts" / "fetch_share_prices.py")
    prices = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prices)
    near = prices.close_nearest
    today = date(2030, 1, 1)

    # 17 August 2024 was a Saturday and a holiday: Friday the 16th, not Monday the 19th.
    series = {date(2024, 8, 16): 100.0, date(2024, 8, 19): 200.0}
    assert near(series, date(2024, 8, 17), today=today) == (date(2024, 8, 16), 100.0)
    # Only a later session near the 17th: it is used rather than one a week before.
    series = {date(2024, 8, 9): 90.0, date(2024, 8, 18): 110.0}
    assert near(series, date(2024, 8, 17), today=today) == (date(2024, 8, 18), 110.0)
    # Equal distance: the earlier session.
    series = {date(2024, 8, 15): 1.0, date(2024, 8, 19): 2.0}
    assert near(series, date(2024, 8, 17), today=today)[0] == date(2024, 8, 15)
    # A session after today is not available.
    series = {date(2024, 8, 18): 5.0, date(2024, 8, 10): 4.0}
    assert near(series, date(2024, 8, 17), today=date(2024, 8, 17))[0] == date(2024, 8, 10)
    with pytest.raises(prices.PriceUnavailable):
        near({date(2024, 9, 30): 1.0}, date(2024, 8, 17), today=today)

    # Q4 prices on 17 May of the FOLLOWING year: the annual report is audited and does
    # not reach the market in December. The other three quarters stay in their own year.
    from datetime import date
    assert prices.price_date("Q4", 2024) == date(2025, 5, 17)
    assert prices.price_date("Q4", 2024, q4_same_year=True) == date(2024, 5, 17)
    assert prices.price_date("Q1", 2024) == date(2024, 6, 17)


def test_a_ratio_is_blank_when_any_input_is():
    """An abstained field must not reappear as a confident ratio.

    The extractor withdraws a value it cannot verify. If the ratio layer then treats
    that blank as zero, the abstention is undone one step downstream and the analyst
    sees a number with a decimal point where the system had actually declined to
    answer -- the exact failure the confidence layer exists to prevent, reintroduced
    by arithmetic.

    Blanking has to propagate, too: PBV and PE stand on BVPS and EPS, so a missing
    share count takes four ratios with it, not two.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_dataset", ROOT / "scripts" / "build_dataset.py")
    dataset = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dataset)

    whole = dict(aset=100, total_aset_lancar=60, liabilitas=40, ekuitas=60,
                 laba_bersih=10, total_share=5)
    values, why = dataset.ratios(whole, price=24.0)
    assert values["bvps"] == 12.0 and values["eps"] == 2.0
    assert values["pbv"] == 2.0 and values["pe"] == 12.0 and not why

    # An abstained equity blanks what depends on it and nothing else.
    values, why = dataset.ratios({**whole, "ekuitas": None}, price=24.0)
    assert values["bvps"] is None and values["roe"] is None and values["der"] is None
    assert values["pbv"] is None, "PBV survived a missing BVPS"
    assert values["eps"] == 2.0 and values["roa"] == 0.1 and values["pe"] == 12.0
    assert "ekuitas missing" in why["roe"]

    # A missing share count reaches four ratios through two.
    values, why = dataset.ratios({**whole, "total_share": None}, price=24.0)
    assert {k for k, v in values.items() if v is None} == {"bvps", "eps", "pbv", "pe"}

    # Zero is a real printed figure, and the ratio it denominates does not exist --
    # which is not the same as it being infinite, and not the same as it being missing.
    values, why = dataset.ratios({**whole, "ekuitas": 0}, price=24.0)
    assert values["roe"] is None and "is zero" in why["roe"]

    # No price: the two market ratios go, the accounting ones stay.
    values, why = dataset.ratios(whole, price=None)
    assert values["pbv"] is None and values["pe"] is None
    assert values["roa"] == 0.1 and values["der"] is not None


def test_a_rate_quoted_directly_as_rupiah_per_dollar_is_read():
    """ITMG states its rate on every report; it just does not use the 1.000-Rupiah table.

    "Rupiah per AS$ 16,782" is the rate itself. Reading only the table form reported
    all eighteen ITMG filings as disclosing no rate, and every row failed conversion.
    The neighbouring "AS$ per Euro" row must not be mistaken for it.
    """
    from normalize import _rate_from_direct_quote as quote
    assert quote("Rupiah per AS$ 16,782 16,162 equivalent to US$1") == (16782.0, (16162.0,))
    assert quote("Rupiah per Dolar AS 14,349 14,269 equivalent to US$1")[0] == 14349.0
    assert quote("US$1 = Rp15.731")[0] == 15731.0
    assert quote("AS$ per Euro 0.8496 0.9591 US$1 equivalent to Euro") is None
    # The table form still belongs to the table reader, not this one.
    assert quote("Rupiah 10.000 (Rp) 0.56 0.60 Rupiah 10,000") is None


def test_a_rate_quoted_in_dollars_per_one_rupiah_is_read():
    """MEDC prints "Rupiah/AS$1 0,000060 0,000062": dollars per ONE Rupiah, no 1.000 unit.

    Without the unit the row was skipped and all eighteen MEDC filings failed conversion.
    Six decimals of a number this small is two significant figures, so the rate carries
    almost 1% rounding uncertainty, and that is said rather than hidden.
    """
    from normalize import _rate_from_line
    rate, places, quoted, others = _rate_from_line(
        "Rupiah/AS$1 0,000060 0,000062 Rupiah/US$1")
    assert round(rate, 2) == 16666.67 and places == 6 and quoted == 0.00006
    assert others == (16129.03,)
    # The neighbouring rows quote other currencies per dollar, not the Rupiah.
    assert _rate_from_line("Euro/AS$1 1,0787 1,0427 Euro/US$1") is None


def test_a_rate_quoted_dollar_first_with_a_slash_is_read():
    """ENRG and PGAS print "1 Dolar AS/Rp 16.588,00 16.162,00" and were taken for filers
    that disclose no rate. pdfplumber also splits ENRG's figure as "1 6.588,00" and
    glues PGAS's words together; neither may lose the rate. ENRG's rights-issue price
    "Rp14.572 per USD 1" on an earlier page is not a rate."""
    from normalize import _rate_from_direct_quote
    assert _rate_from_direct_quote(
        "1 Dolar AS/Rp 1 6.588,00 1 6.162,00 US Dolar 1/Rp") == (16588.0, (16162.0,))
    assert _rate_from_direct_quote(
        "1dolarAS/Rupiah(nilaipenuh) 15.439 15.731 1USdollar/Rupiah(fullamount)") \
        == (15439.0, (15731.0,))
    assert _rate_from_direct_quote(
        "1 Dolar Amerika Serikat/Rp 16.782 16.162 1 United States Dollar/Rp")[0] == 16782.0
    assert _rate_from_direct_quote("amounting to Rp14,572 per USD 1. This PUT III") is None


def test_bi_excel_export_is_read_by_header(tmp_path):
    """BI's Kurs Transaksi export: title rows, then NO/Nilai/Kurs Jual/Kurs Beli/Tanggal
    with Indonesian-formatted text and month-first dates. The quarter-end row uses the
    last fixing on or before the date (31 March 2025 fell in the Lebaran closure)."""
    import importlib.util
    from datetime import date

    import openpyxl
    spec = importlib.util.spec_from_file_location(
        "fetch_fx_rates", Path(__file__).resolve().parent.parent / "scripts" / "fetch_fx_rates.py")
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append([None] * 5)
    sheet.append(["Kurs Transaksi USD"] * 4 + [None])
    sheet.append(["NO", "Nilai", "Kurs Jual", "Kurs Beli", "Tanggal"])
    sheet.append([1, "1,00", "16.670,94", "16.505,06", "3/27/2025 12:00:00 AM"])
    sheet.append([2, "1,00", "16.700,00", "16.600,00", "4/8/2025 12:00:00 AM"])
    path = tmp_path / "kurs.xlsx"
    book.save(path)

    fixings = fetch.fixings_from_excel(path)
    assert fixings[date(2025, 3, 27)] == (16505.06, 16670.94)
    row = fetch.middle_rate_at(date(2025, 3, 31), fixings)
    assert row["rate_date"] == "2025-03-27" and row["idr_per_usd"] == 16588.0


def _bi_table(tmp_path):
    path = tmp_path / "fx_rates_bi.csv"
    path.write_text("period_end,rate_date,idr_per_usd,buy,sell,source\n"
                    "2025-03-31,2025-03-27,16588.0,16505.06,16670.94,BI\n")
    return path


def test_a_filing_with_no_rate_is_converted_at_bank_indonesias_and_says_so(
        tmp_path, monkeypatch):
    """ESSA and APEX print no period-end rate; their notes name BI's middle
    rate. That published rate is used and labelled -- never passed off as the filing's."""
    import normalize
    monkeypatch.setattr(normalize, "extract_fx_rate", lambda pdf: None)
    table = _bi_table(tmp_path)
    fx, note = normalize.fx_for_filing("x.pdf", "2025-03-31", table)
    assert fx.idr_per_usd == 16588.0 and fx.source == "bi_middle_rate"
    assert "discloses no exchange rate" in note and "2025-03-27" in note
    # A quarter the table does not carry is still refused, not filled from a neighbour.
    assert normalize.fx_for_filing("x.pdf", "2025-06-30", table) == (None, None)


def test_a_rate_derived_from_a_translated_amount_gives_way_to_bis(tmp_path, monkeypatch):
    """ESSA Q4 2025 has no rate table; the only Rp/US$ pair is a 2017 share transfer,
    "Rp 245.520.000.000 (setara dengan US$ 25.389.223)" = 9.670. It is not a period-end
    rate and must not convert a 2025 balance sheet when BI's rate is known."""
    import normalize
    pair = normalize.FxRate(idr_per_usd=9670.24, source="derived_from_pair", page=19,
                            evidence="Rp 245.520.000.000 US$ 25,389,223")
    monkeypatch.setattr(normalize, "extract_fx_rate", lambda pdf: pair)
    table = _bi_table(tmp_path)
    fx, note = normalize.fx_for_filing("x.pdf", "2025-03-31", table)
    assert fx.idr_per_usd == 16588.0 and fx.source == "bi_middle_rate"
    assert "9,670.24" in note and "ignored" in note
    # Without a BI rate for the quarter the pair is still the only evidence, as before.
    assert normalize.fx_for_filing("x.pdf", "2025-06-30", table) == (pair, None)


def test_a_coarse_disclosed_rate_is_sharpened_only_inside_its_own_rounding(
        tmp_path, monkeypatch):
    """MEDC's 0,000060 means 16,529-16,807. BI's 16,588 lies inside, so both say the same
    rate and BI's says it exactly. A precise disclosed rate is never replaced."""
    import normalize
    table = _bi_table(tmp_path)
    coarse = normalize.FxRate(idr_per_usd=1 / 0.00006, source="disclosed_rate_table",
                              page=36, evidence="Rupiah/AS$1 0,000060", decimals=6,
                              quoted_value=0.00006)
    monkeypatch.setattr(normalize, "extract_fx_rate", lambda pdf: coarse)
    fx, note = normalize.fx_for_filing("x.pdf", "2025-03-31", table)
    assert fx.idr_per_usd == 16588.0
    assert fx.source == "bi_middle_rate_within_filing_rounding" and fx.page == 36
    assert "16,529-16,807" in note
    # BI outside the quote's rounding: the filing's own figure stands.
    off = normalize.FxRate(idr_per_usd=1 / 0.000070, source="disclosed_rate_table",
                           page=38, evidence="Rupiah/AS$1 0,000070", decimals=6,
                           quoted_value=0.00007)
    monkeypatch.setattr(normalize, "extract_fx_rate", lambda pdf: off)
    assert normalize.fx_for_filing("x.pdf", "2025-03-31", table) == (off, None)
    # A rate quoted to four decimals (ARCI's 0,0697) is precise enough to stand.
    fine = normalize.FxRate(idr_per_usd=1000 / 0.0697, source="disclosed_rate_table",
                            page=20, evidence="1.000 Rupiah 0,0697", decimals=4,
                            quoted_value=0.0697)
    monkeypatch.setattr(normalize, "extract_fx_rate", lambda pdf: fine)
    assert normalize.fx_for_filing("x.pdf", "2025-03-31", table) == (fine, None)


def test_share_count_search_reads_only_the_shareholder_table():
    """Three pages DSNG really prints, in the order it prints them.

    The balance sheet puts authorised capital beside the issued-capital phrase; the
    notes open with the share count at listing; the shareholder table ends in the count
    in issue now. Only the table says what is outstanding, so only the table is found --
    the share-capital line of the statements is not a source even when it prints a count.
    """
    from page_select import find_shareholder_table_pages as find, shareholder_note_pages
    pages = {
        5: "Modal dasar: 35.000.000.000 saham\n"
           "Modal ditempatkan dan disetor penuh 28 211.997 211.997",
        11: "Perseroan mencatatkan saham\n"
            "jumlah saham beredar menjadi 1.844.700.000 saham.",
        77: "Susunan pemegang saham\n"
            "Masyarakat 4.109.621.351 82.194 38,77\n"
            "10.599.842.400 211.997 100,00",
    }
    assert find(pages) == [77]
    assert find({5: pages[5]}) == [], "authorised capital is not a count"
    arci = {6: "Modal dasar - 80.000.000.000 saham\n"
               "Ditempatkan dan disetor penuh -\n"
               "24.835.000.000 saham 20.350.482"}
    assert find(arci) == [], "the statements' share-capital line is not the source"

    # As DSNG actually lays it out: heading on page 76, total row alone on page 77, and
    # the listing-date count still earlier. The total page is found, and its heading page
    # travels with it, because the rows above the total are there.
    split = {11: pages[11],
             76: "Susunan pemegang saham Perusahaan adalah sebagai berikut:\n"
                 "Masyarakat 4.109.621.351 82.194 38,77",
             77: "10.599.842.400 211.997 100,00"}
    assert find(split) == [77]
    assert shareholder_note_pages(split, 77) == [76, 77]
    assert shareholder_note_pages(pages, 77) == [77]
    # A heading that is not on the preceding page vouches for nothing.
    far = {10: "pemegang saham", 77: "10.599.842.400 211.997 100,00"}
    assert find(far) == []

    # The current date's table comes first: EMAS Q1 2026, pages 63 and 64.
    emas = {63: "Pemegang saham/Shareholders 31 Maret/March 2026\n"
                "Jumlah/Total 14,731,366,060 100.00% 139,149,609",
            64: "Pemegang saham/Shareholders 31 Desember/December 2025\n"
                "Saham treasuri/Treasury stock 1,448,866,615 8.95% 13,741,835\n"
                "Jumlah/Total 16,180,232,675 100.00% 152,891,444"}
    assert find(emas) == [63]
    # Two total rows the pattern once missed, as printed.
    assert find({76: "Pemegang saham\nTotal 40,882,331,500 100 303,919,662"}) == [76]  # ADMR Q1 2023
    assert find({106: "Pemegang saham\nTotal 19.852.540.000 100,0000 1.985.254"}) == [106]  # TAPG Q3 2023
    # PURA Q1 2023 prints an inconsistent 104% ownership total, while the total share
    # count is explicit and matches the sum of shareholder counts. Q2 prints 100%.
    assert find({50: "Pemegang saham\nTotal 6.301.930.902 104% 315.096.545.100"}) == [50]
    assert find({50: "Pemegang saham\nTotal 6.301.930.902 120% 315.096.545.100"}) == []
    assert find({50: "Pemegang saham\nMasyarakat 6.301.930.902 104% 315.096.545.100"}) == []
    # A subsidiary table on a page naming its shareholders: ownership first, then assets.
    admr = {15: "Pemegang saham ASC adalah PT Trinugraha Thohir\n"
                "PT Alamtri Indo Aluminium Investasi Indonesia - 100.00% 100.00% 1,069,356,077 629,420,541",
            77: "Pemegang saham\nTotal 40,882,331,500 100 303,919,662"}
    assert find(admr) == [77]                                                             # ADMR Q2 2025

    # A par value is not a percentage. This sentence is on DSNG's page 12, beside the
    # listing-date count, on a page that does mention shareholders.
    par = {11: "Pemegang saham\nRp 100 (Rupiah penuh) per saham sehingga jumlah "
               "outstanding shares changed to 1,844,700,000 shares."}
    from page_select import _HUNDRED_PERCENT_RE
    assert not _HUNDRED_PERCENT_RE.search(par[11]) and find(par) == []
    for printed in ("100,00", "100.00", "100%", "100,00%", "100,000", "100 %"):
        assert _HUNDRED_PERCENT_RE.search(f"Total 1.234.567.890 {printed} 123.456"), printed

    # English-style grouping, and "100%" rather than "100,00".
    comma = {40: "Shareholders\nJumlah/Total 7,786,891,760 100.00 2,519,582"}
    assert find(comma) == [40]
    ptba = {103: "Pemegang saham\ndan disetor penuh 11,520,659,250 100% 1,152,066"}
    assert find(ptba) == [103]


def test_only_the_shareholder_table_group_supplies_share_counts():
    """A count a statement group volunteers is dropped, not merged.

    DSNG, as it actually happened: the balance-sheet group invented 10.599.850.000
    (capital divided by par value, printed nowhere) and beat the 10.599.842.400 the note
    read. And an issued count from the share-capital line is not outstanding either. So
    no statement group can supply one -- not first, and not in place of a missing table.
    """
    from extract import merge_group, GROUP_FIELDS
    merged = F()
    merge_group(merged, F(total_share=10_599_850_000, saham_treasuri=1, aset=5), "balance_sheet")
    assert merged.total_share is None and merged.saham_treasuri is None and merged.aset == 5
    merge_group(merged, F(total_share=10_599_842_400), "share_capital")
    assert merged.total_share == 10_599_842_400

    assert "total_share" not in GROUP_FIELDS["balance_sheet"]
    assert GROUP_FIELDS["equity"] == [], "the equity statement is no longer asked anything"


def test_cash_printed_as_sub_lines_is_summed_and_each_line_is_checked():
    """LSIP's balance sheet carries no cash total, only its two parts.

    Asked for kas, the model summed them in its head: 3.460.442 for a true 3.460.392,
    and wrong by 2 to 128 on six of eighteen filings. Grounding withdrew each, correctly,
    because that sum is printed nowhere -- which left the field empty. The parts ARE
    printed, so they are what is asked for, the total is computed, and each part is
    checked on its own.
    """
    from extract import derive_fields
    from confidence import score_extraction, apply_abstention
    text = ("Kas dan setara kas 5 Cash and cash equivalents\n"
            "Pihak berelasi 877.632 29 518.756 Related party\n"
            "Pihak ketiga 2.582.760 2.849.111 Third parties\n")

    e = F(kas=3_460_442, kas_components=[877_632, 2_582_760], currency="IDR")
    warnings = derive_fields(e)
    assert e.kas == 3_460_392, "the printed parts decide, not the model's sum"
    assert any("sub-line" in w for w in warnings)
    scores = score_extraction(e, text, [])
    assert scores["kas_components"].grounded is True
    assert "kas" not in apply_abstention(e, scores)

    # One invented part takes the computed total down with it.
    bad = F(kas_components=[877_632, 9_999_999], currency="IDR")
    derive_fields(bad)
    scores = score_extraction(bad, text, [])
    abstained = apply_abstention(bad, scores)
    assert scores["kas_components"].grounded is False
    assert "kas_components" in abstained and "kas" in abstained


def test_total_share_is_the_outstanding_count():
    """EPS, BVPS and PBV divide by shares outstanding, not shares issued.

    Treasury shares are held by the issuer and share in neither profit nor equity (IAS 33
    excludes them). The three layouts in the archive, as printed:
      JPFA  prints the outstanding total      11.627.669.901 of 11.726.575.201 issued
      EMAS  prints only treasury shares        1.448.866.615 of 16.180.232.675 issued
      ARCI  has no treasury shares at all
    The issued count is kept beside the result so the adjustment is visible.
    """
    from extract import derive_fields
    jpfa = F(total_share=11_726_575_201, saham_beredar=11_627_669_901)
    derive_fields(jpfa)
    assert jpfa.total_share == 11_627_669_901 and jpfa.saham_ditempatkan == 11_726_575_201

    emas = F(total_share=16_180_232_675, saham_treasuri=1_448_866_615)
    derive_fields(emas)
    assert emas.total_share == 14_731_366_060 and emas.saham_ditempatkan == 16_180_232_675

    arci = F(total_share=24_835_000_000)
    derive_fields(arci)
    assert arci.total_share == 24_835_000_000 == arci.saham_ditempatkan

    # Classes summed first, then the outstanding adjustment -- JPFA prints both.
    classes = F(total_share_components=[8_814_985_201, 2_911_590_000], saham_beredar=11_627_669_901)
    derive_fields(classes)
    assert classes.saham_ditempatkan == 11_726_575_201 and classes.total_share == 11_627_669_901

    # Impossible figures are refused rather than believed.
    bad = F(total_share=1_000_000_000, saham_beredar=2_000_000_000, saham_treasuri=1_000_000_000)
    warnings = derive_fields(bad)
    assert bad.total_share == 1_000_000_000 and len(warnings) == 2


def test_a_computed_outstanding_count_is_graded_on_what_it_was_computed_from():
    """EMAS prints issued and treasury but no outstanding total, so the result is
    printed nowhere. It must be graded on its two inputs, not withdrawn for absence."""
    from extract import derive_fields
    from confidence import score_extraction, apply_abstention
    text = ("Saham treasuri/Treasury stock 1,448,866,615 8.95% 13,741,835\n"
            "Jumlah/Total 16,180,232,675 100.00% 152,891,444\n")
    e = F(total_share=16_180_232_675, saham_treasuri=1_448_866_615, currency="USD")
    derive_fields(e)
    scores = score_extraction(e, text, [])
    assert scores["saham_treasuri"].grounded is True
    assert "total_share" not in apply_abstention(e, scores)
    assert e.total_share == 14_731_366_060


def test_a_computed_outstanding_figure_does_not_sink_a_total_its_inputs_support():
    """EMAS Q4 2025, as it actually ran.

    Page 72 prints issued (16,180,232,675) and treasury (1,448,866,615) shares, and no
    outstanding total. The model subtracted anyway and put 14,731,366,060 in
    saham_beredar. Grounding rightly withdrew that figure -- it is not on the page -- but
    total_share was graded on it alone and was withdrawn too, although it equals issued
    less treasury, both printed. When the three agree, the printed pair decides.
    """
    from extract import derive_fields
    from confidence import score_extraction, apply_abstention
    text = ("Saham treasuri/Treasury stock 1,448,866,615 8.95% 13,741,835\n"
            "Jumlah/Total 16,180,232,675 100.00% 152,891,444\n")
    e = F(total_share=16_180_232_675, saham_treasuri=1_448_866_615,
          saham_beredar=14_731_366_060, currency="USD")
    derive_fields(e)
    scores = score_extraction(e, text, [])
    abstained = apply_abstention(e, scores)
    assert "saham_beredar" in abstained, "the computed figure is still not printed"
    assert "total_share" not in abstained
    assert e.total_share == 14_731_366_060

    # A printed outstanding total that disagrees with issued less treasury still wins,
    # and is graded on itself -- JPFA-style.
    text2 = ("Total saham beredar 11.627.669.901 99,16\nTotal 11.726.575.201 100,00\n"
             "Modal saham diperoleh kembali 98.905.300 0,84\n")
    j = F(total_share=11_726_575_201, saham_beredar=11_627_669_901, saham_treasuri=98_905_300)
    derive_fields(j)
    scores = score_extraction(j, text2, [])
    assert "total_share" not in apply_abstention(j, scores)
    assert j.total_share == 11_627_669_901


def test_a_shareholder_table_ocr_split_into_columns_is_still_found():
    """APEX Q3 2025's share note is OCR'd one column at a time: holders, then counts,
    then "Jumlah 3.546.466.661" alone, and the percentages further down. No count sits
    beside a percentage, so total_share was never asked for. Authorised capital on a
    bare total line still does not count."""
    from page_select import find_shareholder_table_pages
    page = ("MODAL SAHAM\n14. CAPITAL STOCK\nSusunan pemegang saham Perusahaan\n"
            "Pemegang Saham Shares\nPT Aserra Capital\nMasyarakat\n\n1.897.730.677\n"
            "1.648.735.984\n\nJumlah 3.546.466.661\n\n53,510% 81.961.076 PT Aserra Capital\n"
            "46,490% 71.207.246 Public\n100% 153.168.322 Total\n")
    assert find_shareholder_table_pages({10: "notes", 52: page}) == [52]
    authorised = page.replace("Jumlah 3.546.466.661", "Modal dasar\nJumlah 3.546.466.661")
    assert find_shareholder_table_pages({52: authorised}) == []


def test_the_shareholder_table_is_found_and_the_eps_note_is_not():
    """Outstanding and treasury counts live in the shareholder table, not the statements.

    JPFA's balance sheet prints its treasury count beside its cost, and page 112 is the
    only page printing 11.627.669.901 outstanding. An EPS note's weighted "shares
    outstanding" is an average over the period and has no 100% row, so it is never taken
    for the table. An issuer without treasury shares is found the same way: its total is
    what is outstanding.
    """
    from page_select import find_shareholder_table_pages as find_tables
    jpfa = {
        4: "Modal saham diperoleh kembali 98.905.300 saham (147.851) Treasury shares",
        111: "Susunan pemegang saham Perusahaan adalah sebagai berikut:",
        112: "Masyarakat 5.001.234.567 42,65 1.000.247\n"
             "Total saham beredar 11.627.669.901 99,16 1.731.610 Total outstanding shares\n"
             "Modal saham diperoleh kembali 98.905.300 0,84 147.851 Treasury shares\n"
             "Total 11.726.575.201 100,00 1.879.461 Total",
        129: "11.627.669.901 Weighted average number of shares outstanding",
    }
    assert find_tables(jpfa) == [112]

    emas = {71: "Pemegang saham/Shareholders",
            72: "Saham treasuri/Treasury stock 1,448,866,615 8.95% 13,741,835\n"
                "Jumlah/Total 16,180,232,675 100.00% 152,891,444",
            80: "saham biasa yang beredar 14,314,810,852 13,447,820,577 outstanding common stocks"}
    assert find_tables(emas) == [72]

    arci = {77: "Pemegang saham", 78: "Total 24.835.000.000 100,00% 20.350.482 Total"}
    assert find_tables(arci) == [78], "no treasury shares: the total is outstanding"


def test_treasury_shares_from_another_date_are_not_subtracted():
    """A shareholder note shows two dates; the balance sheet says which one has treasury.

    ITMG Q2 2022, as it ran: the note's 31 December 2021 column listed 33,369,100 treasury
    shares, all sold by April 2022, and the model subtracted them -- 1,096,555,900
    outstanding instead of 1,129,925,000, with both inputs printed, so nothing objected.
    The balance sheet's current column is nil for treasury shares, printed as a dash, and
    that is decisive. Each line below is copied from a real filing.
    """
    from extract import treasury_current_on_balance_sheet as current
    assert current("Saham treasuri 20 - (19,211) Treasury shares") is False            # ITMG Q2 2022
    assert current("Saham treasuri 2y - ( 13,741,835 ) Treasury stock") is False        # EMAS Q1 2026
    assert current("Saham treasuri 2z, 21 ( 13,741,835 ) - Treasury stock") is True     # EMAS Q4 2025
    assert current("Saham treasuri 24 (12,521) (12,521) Treasury shares") is True       # PTBA Q2 2025
    # JPFA: the label is a heading line, its figures below, the count is not the amount.
    assert current("Saham treasuri - Treasury shares -\n"
                   "98.905.300 saham (147.851) 2,24 (147.851) 98,905,300 shares") is True
    # JPFA from Q4 2024: the dash separates label and count; the amount beside it is current.
    assert current("Saham treasuri - 98.905.300 saham (147.851) 2,24 (147.851) "
                   "Treasury shares - 98,905,300 shares") is True                       # JPFA Q4 2024
    assert current("Saham treasuri - 21.704.500 saham Treasury shares - 21,704,500 shares\n"
                   "(2025: 98.905.300 saham) (41.152) 2aa,28 (147.851)") is True         # JPFA Q2 2026
    assert current("Modal saham 1.234.567") is None

    from extract import _apply_treasury_date_guard, derive_fields
    itmg = F(total_share=1_129_925_000, saham_treasuri=33_369_100, saham_beredar=1_096_555_900)
    _apply_treasury_date_guard(itmg, {7: "Saham treasuri 20 - (19,211) Treasury shares"},
                               {"balance_sheet": [7]})
    derive_fields(itmg)
    assert itmg.total_share == 1_129_925_000 and itmg.saham_treasuri is None


def test_a_total_from_the_comparative_table_is_replaced_by_the_current_one():
    """EMAS Q1 2026: 14.731.366.060 at the current date; the note's December 2025 table
    says 16.180.232.675. A total equal to a LATER 100% row was read from the comparative
    table, so the first row -- current by position -- replaces it. A total matching no
    row is left alone, for grounding to judge."""
    from extract import _apply_current_table_guard, group_pages
    texts = {63: "Jumlah/Total 14,731,366,060 100.00% 139,149,609\n"
                 "Saham treasuri/Treasury stock 1,448,866,615 8.95% 13,741,835\n"
                 "Jumlah/Total 16,180,232,675 100.00% 152,891,444"}
    groups = group_pages({4: "LAPORAN POSISI KEUANGAN", 63: "notes"}, [63])
    assert groups["share_capital"] == [63]

    e = F(total_share=16_180_232_675)
    _apply_current_table_guard(e, texts, groups)
    assert e.total_share == 14_731_366_060

    unknown = F(total_share=1_234_567_890)
    _apply_current_table_guard(unknown, texts, groups)
    assert unknown.total_share == 1_234_567_890


def test_mixed_bank_loan_note_is_selected_and_kept_as_its_own_group():
    from page_select import find_bank_loan_note_pages
    from extract import group_pages
    pages = {
        4: "LAPORAN POSISI KEUANGAN\nUtang Bank dan Lembaga Bank loans\n"
            "Keuangan Non-Bank 672.925.827",
        20: "Persediaan digunakan sebagai jaminan utang bank dan lembaga keuangan non-bank.",
        70: "23. UTANG BANK DAN LEMBAGA KEUANGAN NON-\nBANK\nTotal 690.692.892",
        71: "Dikurangi bagian lancar\nPT Bank Maybank (1.705.294)\n"
            "PT Bank Pan Indonesia (524.205.898)\nSub-total (672.925.827)",
    }
    assert find_bank_loan_note_pages(pages) == [70, 71]
    assert find_bank_loan_note_pages(pages, mixed_row_present=False) == []
    groups = group_pages({4: pages[4], 70: pages[70], 71: pages[71]}, [], [70, 71])
    assert groups == {"balance_sheet": [4], "bank_note": [70, 71]}


def test_bank_note_components_sum_only_after_each_amount_is_grounded():
    from extract import derive_fields
    e = F(utang_bank_jangka_pendek=15_000,
          utang_bank_bagian_lancar_components=[-5_000, -7_000])
    derive_fields(e)
    assert e.utang_bank_bagian_lancar == 12_000
    assert e.utang_bank == 27_000

    source = ("Utang bank jangka pendek 15.000; Bank C (5.000); "
              "Bank D (7.000)")
    issues = validate(e) + validate_against_document(e, source)
    scores = score_extraction(e, source, issues)
    assert scores["utang_bank_bagian_lancar_components"].grounded is True
    assert scores["utang_bank_bagian_lancar"].confidence >= 0.55
    assert scores["utang_bank"].confidence >= 0.55


def test_combined_bank_and_nonbank_financial_institution_row_is_valid_debt():
    from validate import _bank_rows_by_section
    source = ("Bagian Liabilitas Jangka Panjang Jatuh Tempo dalam Satu Tahun\n"
              "Utang Bank dan Lembaga Keuangan Non-Bank 359.124.216\n"
              "Liabilitas Jangka Panjang Setelah Dikurangi Bagian Lancar\n"
              "Utang Bank dan Lembaga Keuangan Non-Bank 211.178.167")
    e = F(**{**TRUTH, "utang_bank": 359_124_216,
             "utang_bank_jangka_pendek": 0,
             "utang_bank_bagian_lancar": 359_124_216})

    assert _bank_rows_by_section(source) == {
        "current_maturity": [359_124_216], "long_term": [211_178_167]}
    assert not [issue for issue in validate(e) + validate_against_document(e, source)
                if issue.severity == "ERROR"]


def test_printed_combined_current_total_wins_over_incomplete_note_components():
    from extract import derive_fields
    e = F(utang_bank_jangka_pendek=0, utang_bank_bagian_lancar=359_124_216,
          utang_bank_bagian_lancar_components=[200_000_000])
    warnings = derive_fields(e)
    assert e.utang_bank_bagian_lancar == 359_124_216
    assert e.utang_bank == 359_124_216
    assert any("keeping statement total" in w for w in warnings)


def test_split_trin_headings_and_rows_repair_duplicate_or_long_term_component():
    from validate import (_bank_rows_by_section,
                          repair_misclassified_short_term_debt)
    source = ("--- PAGE 5 ---\n"
              "LIABILITAS JANGKA\nPENDEK\n"
              "Bagian Liabilitas Jangka\npanjang jatuh tempo Current maturity\n"
              "dalam satu tahun: of long-term liabilities:\n"
              "Utang Bank dan Bank loans\nlembaga keuangan and non-bank financial\n"
              "non-bank 24 178.961.211 695.981.931 loans\n"
              "Liabilitas jangka panjang -\ndikurangi bagian jatuh\n"
              "tempo: Long-term liabilities - net of current portion:\n"
              "Utang Bank dan Lembaga Bank loans and non-bank\n"
              "Keuangan Non-Bank 23 576.947.572 12.486.620 loans")
    rows = _bank_rows_by_section(source)
    assert rows["short_term"] == []
    assert rows["current_maturity"] == [178_961_211, 695_981_931]
    assert rows["long_term"] == [576_947_572, 12_486_620]

    e = F(**{**TRUTH, "utang_bank": 755_908_783,
             "utang_bank_jangka_pendek": 576_947_572,
             "utang_bank_bagian_lancar": 178_961_211})
    warning = repair_misclassified_short_term_debt(e, source)
    assert warning and "long_term" in warning
    assert e.utang_bank_jangka_pendek == 0
    assert e.utang_bank == 178_961_211

    issues = validate(e) + validate_against_document(e, source)
    scores = score_extraction(e, source, issues)
    assert not any(i.severity == "error" for i in issues)
    assert scores["utang_bank"].confidence >= 0.55

    duplicate = F(**{**TRUTH, "utang_bank": 357_922_422,
                     "utang_bank_jangka_pendek": 178_961_211,
                     "utang_bank_bagian_lancar": 178_961_211})
    warning = repair_misclassified_short_term_debt(duplicate, source)
    assert warning and "current_maturity" in warning
    assert duplicate.utang_bank_jangka_pendek == 0
    assert duplicate.utang_bank == 178_961_211


if __name__ == "__main__":
    # Runnable without pytest, so the guards can be demonstrated anywhere.
    text = build_document_text(read_page_texts(str(PDF), [4, 5, 6, 7, 8, 9, 10, 11]))
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        args = (text,) if fn.__code__.co_argcount else ()
        try:
            fn(*args)
            print(f"  PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)


def test_a_derived_field_cannot_outlive_an_abstained_component(document_text):
    """Observed on JPFA Q4, the first period of the first scored second issuer.

    The balance sheet did not balance, so `total_ekuitas` was implicated, capped and
    abstained. `ekuitas` is nothing but that figure minus the non-controlling interest,
    and it went out at 0.925 -- wrong by exactly the balance-sheet gap. Grading a
    derived field on its components' grounding was never enough: grounding asks whether
    a number is printed, and that number was printed. A structural verdict has to travel
    to everything built on top of it.
    """
    e = F(**{**TRUTH, "liabilitas": 400000000})      # breaks the identity
    _, scores, abstained = assess(e, document_text)

    assert "total_ekuitas" in abstained
    assert "ekuitas" in abstained, "a sum of an abstained row must not be asserted"
    assert e.ekuitas is None
    assert any("component" in r for r in scores["ekuitas"].reasons)


def test_grounding_survives_a_digit_split_from_its_separator():
    """A second shape of the same broken-text-layer problem, seen on GTRA.

    CPIN splits a number between two digits ("1 4.406"); GTRA splits the leading digit
    from the separator that follows it, so "1.092.421.914.566" extracts as
    "1 .092.421.914.566". The first repair did not close that gap, and total assets --
    the single most basic field in the filing -- was reported as absent and abstained
    away, on a balance sheet that balanced to the rupiah.
    """
    from confidence import check_grounding
    text = "TOTAL ASET 1 .092.421.914.566 9 89.890.084.157 TOTAL ASSETS"
    assert check_grounding(1092421914566, text) is True
    assert check_grounding(989890084157, text) is True
    # Repairing the gaps must not start accepting figures that are simply not there.
    assert check_grounding(777777777777, text) is False


def test_a_nil_current_column_is_not_a_bank_row_ignored():
    """ESSA Q3 2025 repaid every loan: "Utang bank 15 - 42.216.691", a dash this period
    against last December's figure. The correct nil was withheld as "bank_row_ignored"
    because the comparative read as the row's amount. A real current figure still fires
    (TRIN Q4 2024's printed 695.981.931 against a reported 0)."""
    from schema import FinancialStatementExtraction
    from validate import validate_against_document
    def page(row):
        return ("--- PAGE 5 ---\nLIABILITAS JANGKA PENDEK\nUtang usaha 14 1.000.000 2.000.000\n"
                "Liabilitas jangka panjang yang jatuh tempo dalam satu tahun\n" + row + "\n"
                "LIABILITAS JANGKA PANJANG\nLiabilitas jangka panjang setelah dikurangi "
                "bagian yang jatuh tempo dalam satu tahun\nUtang bank 15 - 16.016.645\n")
    nil = FinancialStatementExtraction(utang_bank_bagian_lancar=0, utang_bank_jangka_pendek=0)
    codes = lambda text: [i.rule for i in validate_against_document(nil, text)]
    assert "bank_row_ignored" not in codes(page("Utang bank 15 - 42.216.691 Bank loans"))
    assert "bank_row_ignored" in codes(page("Utang bank 15 695.981.931 600.000.000"))


def test_an_explicit_nil_is_not_position_checked(document_text):
    """Zero means the row does not exist, so there is no row to locate it in.

    CPIN reports short-term bank loans and long-term bank loans with no separate
    current-portion line. The model correctly answered 0 for the current portion, and
    the wrong-row guard -- using a fallback added for JPFA, which files its current
    portion under the current-liabilities heading -- compared that zero against the
    short-term row and abstained on a correct extraction.
    """
    e = F(**{**TRUTH, "utang_bank_bagian_lancar": 0, "utang_bank": 34220811})
    issues = validate_against_document(e, document_text)
    assert not any(i.rule == "wrong_section" and "bagian_lancar" in " ".join(i.fields)
                   for i in issues), [i.message for i in issues]


ENRG_Q1_2023 = """TOTAL ASET
1.201.620.447

1.194.330.408
Total Liabilitas 668.220.525 679.404.122 Total Liabilities
Ekuitas - Neto 532.218.646 514.926.286 Equity - Net
TOTAL LIABILITAS TOTAL LIABILITIES
DAN EKUITAS 1.200.439.171 1.194.330.408 AND EQUITY"""


def test_a_filing_whose_own_balance_sheet_does_not_balance_is_reported_with_a_warning():
    """ENRG Q1 2023 prints assets 1.201.620.447 against L+E 1.200.439.171. The model read
    every figure correctly and all three were withheld; the user chose to report them."""
    from validate import filing_prints_unbalanced
    e = F()
    e.aset, e.liabilitas, e.total_ekuitas = 1201620447, 668220525, 532218646
    assert "does not balance" in filing_prints_unbalanced(e, ENRG_Q1_2023)
    # Liabilities and equity from the comparative column land on the comparative L+E
    # total, which never leads its line: still a misread, still withheld.
    e.liabilitas, e.total_ekuitas = 679404122, 514926286
    assert filing_prints_unbalanced(e, ENRG_Q1_2023) is None
    # So is an assets figure taken from the comparative column.
    e.aset, e.liabilitas, e.total_ekuitas = 1194330408, 668220525, 532218646
    assert filing_prints_unbalanced(e, ENRG_Q1_2023 + "\nTOTAL ASET 1.201.620.447 "
                                    "1.194.330.408") is None


MEDC_Q2_2024 = """PENDAPATAN REVENUES
Pendapatan dari kontrak dengan
pelanggan 2,34 1.141.062.168 1.094.111.984
customers
Pendapatan keuangan 2,34 24.306.353 22.094.150 Finance income
JUMLAH PENDAPATAN 1.165.368.521 1.116.206.134 TOTAL REVENUES
BEBAN POKOK PENDAPATAN"""


def test_a_revenue_block_with_a_printed_total_reports_the_total():
    """The user's convention for MEDC: JUMLAH PENDAPATAN, not its first line."""
    from validate import repair_revenue_block_total
    e = F()
    e.pendapatan = 1141062168
    assert repair_revenue_block_total(e, {7: MEDC_Q2_2024})
    assert e.pendapatan == 1165368521
    # Already the total: nothing to do.
    assert repair_revenue_block_total(e, {7: MEDC_Q2_2024}) == []
    # AKRA before 2024 prints no total; the first line stands.
    akra = ("Pendapatan dari Kontrak dengan Pelanggan 10.891.301.304 10.071.527.947\n"
            "Pendapatan Sewa 67.571.271 62.724.201 Rental Income\n"
            "Beban Pokok Penjualan dan Pendapatan (9.888.680.270) (9.395.848.827)")
    e.pendapatan = 10891301304
    assert repair_revenue_block_total(e, {6: akra}) == [] and e.pendapatan == 10891301304
    # A total the lines in between do not add up to belongs to another block.
    e.pendapatan = 1141062168
    wrong = MEDC_Q2_2024.replace("24.306.353", "20.000.000")
    assert repair_revenue_block_total(e, {7: wrong}) == [] and e.pendapatan == 1141062168
