#!/usr/bin/env python3
"""
Evaluate a pipeline run: every cell of <ticker>.csv against the label workbook AND the PDF.

`run_eval.py` scores the extractor against data/ground_truth with its own cached
predictions. This script evaluates what the user actually got -- the CSV and workbook
that `pdf_to_excel.py` wrote into ~/FinancialReport/<TICKER>/ -- and, because a label
can be wrong too (see data/ground_truth/CORRECTIONS.md: shifted columns, comparative
figures, a thousandfold scale), it does not stop at "differs from the label". For every
cell it gathers the evidence needed to decide WHO is wrong:

  * is the pipeline's figure printed in the filing, on which page and line, and is it
    the FIRST figure on that line (the current-period column in most layouts)?
  * when it disagrees with the label, is the LABEL's figure printed there?

Printed is searched at every scale the filing could use (full, thousands, millions) and,
for a dollar filer, in US dollars at the row's own rate -- the same search
`agenttools.number_hits` uses. utang_bank and total_share are often sums or
differences of printed lines, so "not printed verbatim" is not evidence against them.

**Not found is not absent.** A figure missing from the text layer may still be on the
page (a scanned page, a figure split across columns). The report says "not found in
the text", never "not in the PDF"; the evaluator looks at the page before claiming
the filing lacks something.

Nothing here decides or changes anything. It writes a report:

    output/evaluation/<TICKER>_<date>.md    the cells that need a decision, with evidence
    output/evaluation/<TICKER>_<date>.json  every cell

Usage:
    python scripts/evaluate_output.py --ticker AKRA
    python scripts/evaluate_output.py --ticker AKRA ENRG --periods Q1_2023 Q2_2023
"""

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from evalkit import compare  # noqa: E402
from numfmt import grouped_numbers  # noqa: E402
from periods import parse_period  # noqa: E402
from schema import EXCEL_ROWS  # noqa: E402

DEFAULT_ARCHIVE = Path.home() / "FinancialReport"
GROUND_TRUTH = ROOT / "data" / "ground_truth"
OUT_DIR = ROOT / "output" / "evaluation"
TOLERANCE = 1e-4                      # run_eval's default
FIELDS = list(EXCEL_ROWS)
# Often not one printed line: current bank loans plus current maturities; issued shares
# less treasury shares.
DERIVED = {"utang_bank", "total_share"}
SCALES = (("FULL", 1), ("THOUSANDS", 1_000), ("MILLIONS", 1_000_000))
MAX_HITS = 4


def _number(text):
    if text in (None, ""):
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def printed_at(texts: dict, value, fx_rate=None, count: bool = False) -> list:
    """Where `value` (full Rupiah, or a share count) is printed. [] if nowhere found.

    Each hit: page (1-indexed), the reading that found it, whether the figure is the
    first on its line, and the line itself.
    """
    if value in (None, 0):
        return []
    readings = [("COUNT", 1, "", 1.0)] if count else \
        [(scale, mult, "IDR", 1.0) for scale, mult in SCALES]
    if fx_rate and not count:
        readings += [(scale, mult, "USD", fx_rate) for scale, mult in SCALES]
    hits = []
    for n in sorted(texts):
        for line in (texts[n] or "").split("\n"):
            numbers = grouped_numbers(line)
            if not numbers:
                continue
            for scale, mult, currency, rate in readings:
                target = abs(value) / (mult * rate)
                slack = 0.5 if currency != "USD" else max(0.5, target * 2e-3)
                if target < 1:
                    continue
                position = next((i for i, v in enumerate(numbers)
                                 if abs(abs(v) - target) <= slack), None)
                if position is not None:
                    hits.append({"page": n + 1, "reading": f"{currency} {scale}".strip(),
                                 "first_on_line": position == 0,
                                 "line": " ".join(line.split())[:180]})
                    break
            if len(hits) >= MAX_HITS:
                return hits
    return hits


def read_labels(ticker: str) -> dict:
    """{(period, field): value} from data/ground_truth/<TICKER>.xlsx, {} if none."""
    path = GROUND_TRUTH / f"{ticker}.xlsx"
    if not path.exists():
        return {}
    import openpyxl
    sheet = openpyxl.load_workbook(path, data_only=True)["Sheet1"]
    columns = {}
    for cell in sheet[3]:
        period = parse_period(cell.value) if isinstance(cell.value, str) else None
        if period:
            columns[period] = cell.column
    labels = {}
    for field, (row, _label) in EXCEL_ROWS.items():
        for period, column in columns.items():
            value = sheet.cell(row=row, column=column).value
            if isinstance(value, (int, float)):
                labels[(period, field)] = value
    return labels


def verdict(pred, label, pred_hits, label_hits, field) -> tuple:
    """(status, hint). status is what happened; hint is where to look first."""
    derived = field in DERIVED
    if label is None:
        if pred is None:
            return "blank_no_label", "both empty: check the filing reports this field"
        if pred_hits or derived:
            return "no_label", ""
        return "check_unprinted", "no label, and the figure was not found in the text"
    if pred is None:
        where = (f"label printed p{label_hits[0]['page']}" if label_hits
                 else "label not found in the text")
        return "missed", f"pipeline left it blank; {where}"
    status, _error, kind = compare(pred, label, TOLERANCE,
                                   grounded=bool(pred_hits) or None)
    if status == "correct":
        return "correct", ""
    pred_first = any(h["first_on_line"] for h in pred_hits)
    label_first = any(h["first_on_line"] for h in label_hits)
    if pred_hits and not label_hits:
        hint = ("likely LABEL error: the pipeline's figure is printed"
                + (" as the line's first figure" if pred_first else "")
                + ", the label's is not found" + (" (label may be a sum)" if derived else ""))
    elif label_hits and not pred_hits:
        hint = ("likely EXTRACTION error: the label's figure is printed, the pipeline's "
                "is not found" + (" (pipeline may have summed lines)" if derived else ""))
    elif label_hits and pred_hits:
        hint = ("both printed: wrong row, wrong column or a convention choice"
                + (" -- the label's is the first figure on its line" if label_first
                   and not pred_first else "")
                + (" -- the pipeline's is the first figure on its line" if pred_first
                   and not label_first else ""))
    else:
        hint = "neither found verbatim: check the page (sums, scanned page)"
    return f"wrong:{kind}", hint


def evaluate(ticker: str, archive: Path, periods: set, variant: str = "") -> dict:
    from pdftext import page_texts
    folder = archive / ticker
    csv_path = (folder / f"{ticker.lower()}_{variant}.csv" if variant else
                next((folder / name for name in (f"{ticker.lower()}.csv",
                                                  f"{ticker.upper()}.csv")
                      if (folder / name).exists()), folder / f"{ticker.lower()}.csv"))
    if not csv_path.exists():
        raise SystemExit(f"no {csv_path}; run scripts/pdf_to_excel.py --ticker {ticker}")
    with open(csv_path, newline="", encoding="utf-8") as handle:
        # Some archive CSVs were re-saved by Excel with ";" between fields (ARCI).
        delimiter = ";" if handle.readline().count(";") > 3 else ","
        handle.seek(0)
        rows = list(csv.DictReader(handle, delimiter=delimiter))
    labels = read_labels(ticker)
    cells, filings = [], []
    for row in sorted(rows, key=lambda r: r["file"]):
        period = parse_period("_".join(row["file"].split("_")[:2]))
        if not period or (periods and f"{period[0]}_{period[1]}" not in periods):
            continue
        pdf = folder / row["file"]
        # The pages the pipeline read first: that is where its figures should be, and a
        # whole 120-page filing costs ten times as long. The rest of the document is
        # read only for a cell that found no evidence there.
        selected = [int(p) - 1 for p in (row.get("pages_selected") or "").split()
                    if p.isdigit()]
        texts = (page_texts(str(pdf), selected) if selected else page_texts(str(pdf))) \
            if pdf.exists() else {}
        whole = {}

        def everywhere():
            if not whole and pdf.exists():
                whole.update(page_texts(str(pdf)))
            return whole
        fx = _number(row.get("fx_rate"))
        filings.append({"period": f"{period[0]} {period[1]}", "file": row["file"],
                        "status": row.get("status"), "issues": row.get("issues", ""),
                        "notes": row.get("notes", ""), "error": row.get("error", ""),
                        "pages_selected": row.get("pages_selected", ""),
                        "pdf_found": pdf.exists()})
        for field in FIELDS:
            pred = _number(row.get(field))
            label = labels.get((period, field))
            count = field == "total_share"
            pred_hits = printed_at(texts, pred, fx, count)
            label_hits = (printed_at(texts, label, fx, count)
                          if label is not None and (pred is None or abs(pred - label) >
                                                    TOLERANCE * max(abs(label), 1)) else [])
            status, hint = verdict(pred, label, pred_hits, label_hits, field)
            if status not in ("correct", "no_label") and pdf.exists() and \
                    len(texts) < len(everywhere()):
                pred_hits = printed_at(whole, pred, fx, count)
                if label is not None and status != "blank_no_label":
                    label_hits = printed_at(whole, label, fx, count)
                status, hint = verdict(pred, label, pred_hits, label_hits, field)
            cells.append({"period": f"{period[0]} {period[1]}", "field": field,
                          "pred": pred, "label": label, "status": status, "hint": hint,
                          "pred_printed": pred_hits, "label_printed": label_hits,
                          "abstained": field in (row.get("abstained") or "").split(),
                          "file": row["file"]})
    return {"ticker": ticker, "date": date.today().isoformat(),
            "has_labels": bool(labels), "filings": filings, "cells": cells}


def summary(result: dict) -> dict:
    cells = result["cells"]
    labelled = [c for c in cells if c["label"] is not None]
    correct = sum(1 for c in labelled if c["status"] == "correct")
    return {"cells": len(cells), "labelled": len(labelled), "correct": correct,
            "accuracy": round(correct / len(labelled), 4) if labelled else None,
            "filled": sum(1 for c in cells if c["pred"] is not None),
            "by_status": dict(Counter(c["status"].split(":")[0] for c in cells))}


def _fmt(value) -> str:
    return "" if value is None else f"{value:,.0f}".replace(",", ".")


def markdown(result: dict) -> str:
    s = summary(result)
    lines = [f"# Evaluasi {result['ticker']} -- {result['date']}", ""]
    if result["has_labels"]:
        lines.append(f"- Ground truth: {s['correct']}/{s['labelled']} sel cocok "
                     f"({s['accuracy']:.2%})")
    else:
        lines.append("- Ground truth: tidak ada workbook label; hanya dicek ke PDF")
    lines.append(f"- Terisi: {s['filled']}/{s['cells']} sel; status: {s['by_status']}")
    lines.append("")
    review = [c for c in result["cells"]
              if c["status"] not in ("correct", "no_label")]
    lines.append(f"## Perlu diputuskan ({len(review)})")
    lines.append("")
    if not review:
        lines.append("Tidak ada.")
    for c in review:
        lines.append(f"### {c['period']} -- {c['field']} -- `{c['status']}`")
        lines.append(f"- pipeline: {_fmt(c['pred']) or '(kosong)'}"
                     + ("  (abstain)" if c["abstained"] else ""))
        lines.append(f"- label: {_fmt(c['label']) or '(tidak ada)'}")
        if c["hint"]:
            lines.append(f"- petunjuk: {c['hint']}")
        for who, hits in (("pipeline", c["pred_printed"]), ("label", c["label_printed"])):
            for h in hits:
                lines.append(f"  - {who} tercetak p{h['page']} [{h['reading']}"
                             f"{', angka pertama' if h['first_on_line'] else ''}]: "
                             f"`{h['line']}`")
        lines.append("")
    flagged = [f for f in result["filings"] if f["status"] != "ok" or f["error"]]
    if flagged:
        lines.append("## Filing tidak lengkap")
        lines.append("")
        for f in flagged:
            lines.append(f"- {f['period']} {f['file']}: {f['status']} "
                         f"{f['error'] or ''} issues: {f['issues'] or '-'}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ticker", nargs="+", required=True)
    ap.add_argument("--periods", nargs="+", metavar="Q1_2023")
    ap.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    ap.add_argument("--variant", default="",
                    help="evaluate <t>_<variant>.csv (e.g. claude) instead of <t>.csv")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    periods = {p.upper() for p in (args.periods or [])}
    needs_review = 0
    for ticker in (t.upper() for t in args.ticker):
        try:
            result = evaluate(ticker, Path(args.archive).expanduser(), periods,
                              args.variant.lower())
        except (SystemExit, Exception) as exc:      # noqa: BLE001 - one bad ticker only
            print(f"{ticker}: not evaluated -- {type(exc).__name__}: {exc}")
            needs_review += 1
            continue
        stem = OUT_DIR / (f"{ticker}_{args.variant.lower()}_{result['date']}"
                          if args.variant else f"{ticker}_{result['date']}")
        stem.with_suffix(".json").write_text(json.dumps(result, indent=1, default=str))
        stem.with_suffix(".md").write_text(markdown(result))
        s = summary(result)
        review = [c for c in result["cells"] if c["status"] not in ("correct", "no_label")]
        needs_review += len(review)
        accuracy = (f"{s['correct']}/{s['labelled']} vs GT ({s['accuracy']:.2%})"
                    if s["labelled"] else "no labels")
        print(f"{ticker}: {accuracy}; filled {s['filled']}/{s['cells']}; "
              f"{len(review)} cell(s) to decide -> {stem.with_suffix('.md')}")
        for c in review:
            print(f"   {c['period']:8s} {c['field']:28s} {c['status']:28s} {c['hint']}")
    return 0 if needs_review == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
