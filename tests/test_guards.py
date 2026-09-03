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
from validate import validate, validate_against_document    # noqa: E402
from confidence import score_extraction, apply_abstention    # noqa: E402
from extract import read_page_texts, build_document_text     # noqa: E402
from normalize import extract_fx_rate, to_idr                # noqa: E402

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
