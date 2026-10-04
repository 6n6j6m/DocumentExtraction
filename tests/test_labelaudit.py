#!/usr/bin/env python3
"""
The label audit's deterministic half: the checks a model's citation has to survive.

The auditor is only as trustworthy as these. A citation is evidence only if the figure
is printed on the page it names and sits under this period's column -- and the column
is decided by the page's geometry, not by what the agent says it read. The errors
planted here are the ones this corpus actually had.

No model, no API key, no network.

Run:  python -m pytest tests/test_labelaudit.py -v
"""

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from labelaudit import (AUDIT_FIELDS, Evidence, PageSource, Part,  # noqa: E402
                        bootstrap_rate, cell_status, convert, diff_columns,
                        evidence_from_args, header_matches_period, inject_errors,
                        read_columns, screen_columns, value_on_page, verify_evidence,
                        verify_part, workbook_at)

ARCHIVE = Path.home() / "FinancialReport"
GTRA_Q2_2024 = ARCHIVE / "GTRA" / "Q2_2024_GTRA.pdf"
FILLER = "Catatan atas laporan keuangan konsolidasian yang merupakan bagian. " * 4


def _page(*lines):
    return "\n".join(["LAPORAN POSISI KEUANGAN (Dinyatakan dalam Rupiah)", *lines, FILLER])


# --- which period a column is ---------------------------------------------------------

def test_a_header_names_its_period_in_either_language():
    assert header_matches_period("30 Juni 2024", "Q2", 2024) is True
    assert header_matches_period("June 30, 2024", "Q2", 2024) is True
    assert header_matches_period("31/12/2023", "Q4", 2023) is True
    # The comparative column: a date, and not this one.
    assert header_matches_period("31 Desember 2023", "Q2", 2024) is False
    # No date at all is "cannot tell", never "wrong".
    assert header_matches_period("Jumlah", "Q2", 2024) is None


# --- is the figure on the page -------------------------------------------------------

def test_a_figure_split_by_the_text_layer_is_still_found():
    """GTRA prints 17.149.123.737 as "1 7.149.123.737". A check that missed it would
    reject a correct citation and push a right label into "unverifiable"."""
    text = _page("Pinjaman bank 13 18.672.839.545 1 7.149.123.737 Bank loans")
    assert value_on_page("17.149.123.737", text)
    assert value_on_page("18.672.839.545", text)
    assert not value_on_page("17.149.123.738", text)


def test_a_citation_of_a_figure_not_on_the_page_is_not_evidence():
    source = PageSource(texts={4: _page("Total aset 111.111.111 222.222.222")})
    part = verify_part(Part("333.333.333", page=5, column_header="30 Juni 2024"),
                       source, "Q2", 2024)
    assert part.on_page is False and not part.verified
    assert "not printed on page 5" in part.problems[0]


def test_the_agent_naming_the_comparative_column_is_caught():
    source = PageSource(texts={4: _page("Total aset 111.111.111 222.222.222")})
    part = verify_part(Part("222.222.222", page=5, column_header="31 Desember 2023"),
                       source, "Q2", 2024)
    assert part.claimed_header_check == "other_period" and not part.verified


@pytest.mark.skipif(not GTRA_Q2_2024.exists(), reason="the filing archive is not here")
def test_the_page_geometry_catches_a_comparative_figure_the_agent_calls_current():
    """The agent may SAY it read the current column. The page table built from word
    positions says where the figure really is: 17.149.123.737 sits under 31 December
    2023 on GTRA Q2 2024 page 5, whatever header the citation claims."""
    source = PageSource(pdf_path=str(GTRA_Q2_2024))
    lying = verify_part(Part("17.149.123.737", page=5, column_header="30 Juni 2024"),
                        source, "Q2", 2024)
    assert lying.on_page and lying.column_check == "other_period" and not lying.verified
    honest = verify_part(Part("18.672.839.545", page=5, column_header="30 Juni 2024"),
                         source, "Q2", 2024)
    assert honest.column_check == "current" and honest.verified


# --- arithmetic is code ------------------------------------------------------------------

def test_components_are_summed_with_their_signs_and_the_header_scale_wins():
    source = PageSource(texts={6: "LAPORAN POSISI KEUANGAN (Dalam ribuan Rupiah)\n"
                                  "Total ekuitas 900.000 850.000\n"
                                  "Kepentingan nonpengendali (11.111) (10.000)\n" + FILLER})
    evidence = evidence_from_args({
        "field": "ekuitas", "scale": "FULL", "currency": "IDR",
        "components": [{"printed_value": "900.000", "page": 7, "sign": "+"},
                       {"printed_value": "(11.111)", "page": 7, "sign": "-"}]})
    verify_evidence(evidence, source, "Q2", 2024)
    # 900.000 - (-11.111) = 911.111 thousand: the NCI keeps its own sign, as printed.
    assert evidence.value == 911_111_000
    assert any("header says THOUSANDS" in p for p in evidence.problems)


def test_a_share_count_is_never_scaled():
    evidence = Evidence("total_share", [Part("1.894.375.000", page=1)], scale="MILLIONS")
    assert convert(evidence, detected_scale="MILLIONS").value == 1_894_375_000


def test_a_dollar_figure_with_no_disclosed_rate_is_not_converted():
    evidence = Evidence("aset", [Part("1.000", page=1)], currency="USD")
    assert convert(evidence, fx=None).value is None


def test_cell_status_needs_a_verified_reading_before_it_disputes_anything():
    ok = Evidence("aset", [Part("1.000", page=1, on_page=True)], value=1000.0)
    unchecked = Evidence("aset", [Part("1.000", page=1, on_page=False)], value=1000.0)
    assert cell_status(None, ok) == "unlabelled"
    assert cell_status(1000.0, None) == "not_found"
    assert cell_status(1000.0, ok) == "confirmed"
    assert cell_status(2000.0, ok) == "disputed"
    assert cell_status(2000.0, unchecked) == "unverifiable"


# --- the free screen ------------------------------------------------------------------------

def _columns():
    base = {"aset": 1000.0, "total_aset_lancar": 400.0, "kas": 50.0, "liabilitas": 600.0,
            "utang_bank": 30.0, "ekuitas": 390.0, "laba_bersih": 10.0, "pendapatan": 100.0,
            "kas_dari_aktivitas_operasi": 20.0, "total_share": 5000.0}
    return {("Q1", 2024): dict(base),
            ("Q2", 2024): {k: v * 1.1 for k, v in base.items()},
            ("Q3", 2024): {k: v * 1.2 for k, v in base.items()},
            ("Q4", 2024): {k: v * 1.3 for k, v in base.items()}}


def test_the_screen_flags_a_shifted_column_a_scale_jump_and_a_part_above_its_total():
    columns = _columns()
    columns[("Q4", 2024)] = dict(columns[("Q2", 2024)])          # GTRA's signature
    columns[("Q3", 2024)]["kas"] = columns[("Q3", 2024)]["kas"] * 1000
    flags = screen_columns("TEST", columns)
    kinds = {(f.kind, f.quarter, f.field) for f in flags}
    assert ("duplicate_column", "Q4", None) in kinds
    assert ("scale_jump", "Q3", "kas") in kinds
    assert ("part_exceeds_total", "Q3", "kas") in kinds


def test_revenue_doubling_from_q1_to_q2_is_a_business_not_an_error():
    """Flows are cumulative through the year; only balance-sheet stocks are checked for
    a factor of two."""
    columns = _columns()
    columns[("Q2", 2024)]["pendapatan"] = columns[("Q1", 2024)]["pendapatan"] * 2
    assert not [f for f in screen_columns("TEST", columns) if f.kind == "double_jump"]


def _git_has_head_workbook(ticker):
    try:
        return subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e",
                               f"HEAD:data/ground_truth/{ticker}.xlsx"],
                              capture_output=True).returncode == 0
    except OSError:
        return False


@pytest.mark.skipif(not _git_has_head_workbook("GTRA"), reason="no git history here")
def test_the_screen_finds_the_gtra_shift_in_the_committed_labels(tmp_path):
    """The shift that cost 117 cells was found by reading the corpus scorecard by hand.
    The committed workbook still has it, so the free screen must see it."""
    path = workbook_at("GTRA", "HEAD", ROOT / "data" / "ground_truth", tmp_path)
    columns, _ = read_columns(path)
    flags = [f for f in screen_columns("GTRA", columns) if f.kind == "duplicate_column"]
    assert flags, "a copied column is the shift's signature"


# --- scoring the auditor ------------------------------------------------------------------

def test_planted_errors_differ_from_the_truth_and_leave_the_original_alone():
    columns = _columns()
    before = {p: dict(v) for p, v in columns.items()}
    corrupted, key = inject_errors(columns, per_kind=1, seed=3)
    assert columns == before
    assert key and len(set(key.values())) >= 4
    for (q, y, f), kind in key.items():
        assert corrupted[(q, y)][f] != columns[(q, y)][f], kind
    again, key_again = inject_errors(columns, per_kind=1, seed=3)
    assert key_again == key, "the same seed plants the same errors"


def test_a_cell_emptied_by_a_correction_still_counts_as_a_known_error():
    wrong = {("Q3", 2022): {"aset": 5.0, "kas": 1.0}}
    right = {("Q3", 2022): {"aset": None, "kas": 1.0}}
    assert diff_columns(wrong, right) == {("Q3", 2022, "aset"): (5.0, None)}


def test_the_error_rate_interval_is_clustered_by_filing():
    """Ten cells of one filing share a reading; resampled as ten, the interval would be
    too narrow."""
    lumpy = bootstrap_rate({"A": [1] * 10, "B": [0] * 10, "C": [0] * 10}, iters=2000)
    assert lumpy["rate"] == pytest.approx(1 / 3)
    assert lumpy["clusters"] == 3 and lumpy["hi"] - lumpy["lo"] > 0.5


def test_the_audit_never_writes_a_workbook(tmp_path, monkeypatch, capsys):
    """Proposals are a form for a person. The screen and the report read the workbooks;
    this proves they left every byte where it was."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import audit_labels
    books = sorted((ROOT / "data" / "ground_truth").glob("*.xlsx"))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in books}
    monkeypatch.setattr(sys, "argv", ["audit_labels.py", "--tickers", "ARCI", "GTRA",
                                      "--phase", "screen", "--out", str(tmp_path)])
    assert audit_labels.main() == 0
    monkeypatch.setattr(sys, "argv", ["audit_labels.py", "--tickers", "ARCI",
                                      "--phase", "report", "--out", str(tmp_path)])
    monkeypatch.setenv("AUDIT_EVALUATED_MODELS", "none-of-these")
    assert audit_labels.main() == 0
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in books}
    assert before == after
    assert len(AUDIT_FIELDS) == 10
