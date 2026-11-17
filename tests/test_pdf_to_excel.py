#!/usr/bin/env python3
"""
The end-to-end script's own decisions: which filings it sends to the model, what it
does to a value someone typed into the workbook, and the layout it writes. No model and
no network -- extraction and prices are what the other scripts' tests cover.

Run:  python -m pytest tests/test_pdf_to_excel.py -v
"""

import importlib.util
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("pdf_to_excel",
                                              ROOT / "scripts" / "pdf_to_excel.py")
p2x = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p2x)

Q1, Q4 = ("Q1", 2023), ("Q4", 2022)


def _row(name, **values):
    row = {"file": name, "status": "ok", "fields_filled": "10/10", "abstained": "",
           "issues": "", "notes": "", "abstention_details": "", "model": "m"}
    row.update({field: "" for field in p2x.EXCEL_ROWS})
    row.update({k: str(v) for k, v in values.items()})
    return row


def test_a_filing_already_answered_is_not_sent_to_the_model_again(tmp_path):
    pdfs = [tmp_path / f"{p}_AKRA.pdf" for p in ("Q1_2023", "Q2_2023", "Q3_2023")]
    existing = {"Q1_2023_AKRA.pdf": {"status": "ok"},
                "Q2_2023_AKRA.pdf": {"status": "partial"}}
    pick = lambda **kw: [p.name for p in p2x.choose(pdfs, existing, **kw)]  # noqa: E731
    base = dict(force=False, retry_partial=False, refresh=set())
    assert pick(**base) == ["Q3_2023_AKRA.pdf"]
    assert pick(**{**base, "retry_partial": True}) == ["Q2_2023_AKRA.pdf", "Q3_2023_AKRA.pdf"]
    assert pick(**{**base, "refresh": {"Q1_2023"}}) == ["Q1_2023_AKRA.pdf", "Q3_2023_AKRA.pdf"]
    assert len(pick(**{**base, "force": True})) == 3


def test_a_hand_entered_value_is_kept_and_the_pipelines_own_cell_follows_the_new_run():
    key_edit, key_own, key_abstain, key_new = ((Q1, "aset"), (Q1, "kas"),
                                               (Q1, "utang_bank"), (Q1, "ekuitas"))
    pipeline = {key_edit: 100, key_own: 5, key_abstain: 7}          # what it wrote before
    values = {key_edit: 999, key_own: 5, key_abstain: 7}            # aset typed over
    new = {key_edit: 101, key_own: 6, key_abstain: None, key_new: 42}
    final, last, kept = p2x.merge(new, values, pipeline, overwrite=False)
    assert final[key_edit] == 999 and kept == {key_edit: 101}
    assert final[key_own] == 6
    assert final[key_abstain] == 7          # an abstention never erases a value
    assert final[key_new] == 42
    assert last[key_edit] == 101 and last[key_abstain] == 7
    final, _last, kept = p2x.merge(new, values, pipeline, overwrite=True)
    assert final[key_edit] == 101 and kept == {}


def test_the_workbook_has_the_ratio_sheet_layout_and_marks_blanks(tmp_path):
    rows = {"Q1_2023_AKRA.pdf": _row("Q1_2023_AKRA.pdf", aset=1000, total_aset_lancar=600,
                                     kas=50, liabilitas=400, utang_bank=30, ekuitas=600,
                                     laba_bersih=60, pendapatan=900,
                                     kas_dari_aktivitas_operasi=-20, total_share=10),
            "Q4_2022_AKRA.pdf": _row("Q4_2022_AKRA.pdf", status="partial", aset=900,
                                     abstained="kas",
                                     abstention_details='{"kas": {"reasons": ["x"]}}')}
    prices = {Q1: {"price": 1450, "price_date": "2023-06-16", "note": ""},
              Q4: {"price": "", "note": "no trading day"}}
    path = tmp_path / "AKRA.xlsx"
    summary = p2x.write_workbook(path, "AKRA", rows, prices)
    sheet = openpyxl.load_workbook(path)["Sheet1"]
    assert sheet["D1"].value == "AKRA"
    assert [sheet["B3"].value, sheet["C3"].value] == ["Q1 2023", "TAHUNAN 2022"]
    assert sheet["B4"].value == 1000 and sheet["B12"].value == -20
    assert sheet["B14"].value == 1450
    assert sheet["A15"].value == "Book Value per share" and sheet["B15"].value == "=B9/B13"
    assert sheet["C20"].value == "=C14/C21"
    assert sheet["C6"].value is None and "Abstain: x" in sheet["C6"].comment.text
    assert sheet["C14"].comment.text == "no trading day"
    assert "TAHUNAN 2022 kas" in summary["blank"]
    # A rerun after a hand edit keeps the edit.
    book = openpyxl.load_workbook(path)
    book["Sheet1"]["B4"] = 1234
    book.save(path)
    summary = p2x.write_workbook(path, "AKRA", rows, {})
    sheet = openpyxl.load_workbook(path)["Sheet1"]
    assert sheet["B4"].value == 1234 and summary["kept"] == {(Q1, "aset"): 1000}
    assert sheet["B14"].value == 1450       # no prices fetched: the old one stays
    assert (tmp_path / "AKRA.xlsx.bak").exists()
