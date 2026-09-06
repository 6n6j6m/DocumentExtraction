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
