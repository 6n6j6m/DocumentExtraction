#!/usr/bin/env python3
"""
The evaluator's evidence: where a figure is printed, and who a disagreement points at.

Run:  python -m pytest tests/test_evaluate_output.py -v
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("evaluate_output",
                                              ROOT / "scripts" / "evaluate_output.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

# AKRA Q1 2023 p5, in thousands of Rupiah: current period first, December 2022 after
# the notes column.
PAGE = {4: ("Hutang bank jangka pendek dan lainnya - 2t,3,17 1.573.705 Short-term bank loans\n"
            "yang jatuh tempo dalam satu tahun 548.258.806 2t,3,18 554.639.521 bank loans\n"
            "Jumlah Aset 23.825.391.538 27.187.608.036 Total Assets")}


def test_a_figure_is_found_at_the_scale_it_is_printed_and_its_column_is_told():
    hits = ev.printed_at(PAGE, 23_825_391_538_000)
    assert hits[0]["page"] == 5 and hits[0]["reading"] == "IDR THOUSANDS"
    assert hits[0]["first_on_line"] is True
    comparative = ev.printed_at(PAGE, 27_187_608_036_000)
    assert comparative[0]["first_on_line"] is False
    assert ev.printed_at(PAGE, 999_999_000) == []
    # A dollar filer is searched in dollars at the row's own rate.
    assert ev.printed_at({0: "Jumlah aset 1.201.620.447"}, 1_201_620_447 * 15_062,
                         fx_rate=15_062)[0]["reading"] == "USD FULL"


def test_who_a_disagreement_points_at():
    label_sum = 549_832_511_000           # the old label: current + the comparative line
    pred = 548_258_806_000
    pred_hits = ev.printed_at(PAGE, pred)
    label_hits = ev.printed_at(PAGE, label_sum)
    status, hint = ev.verdict(pred, label_sum, pred_hits, label_hits, "utang_bank")
    assert status.startswith("wrong") and "LABEL" in hint
    status, hint = ev.verdict(label_sum, pred, label_hits, pred_hits, "utang_bank")
    assert "EXTRACTION" in hint
    assert ev.verdict(pred, pred, pred_hits, [], "utang_bank")[0] == "correct"
    assert ev.verdict(None, pred, [], pred_hits, "utang_bank")[0] == "missed"
    assert ev.verdict(123_456, None, [], [], "kas")[0] == "check_unprinted"
    assert ev.verdict(123_456, None, [], [], "utang_bank")[0] == "no_label"   # a sum
