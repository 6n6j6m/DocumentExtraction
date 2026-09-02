#!/usr/bin/env python3
"""
Evaluate the extraction pipeline against the ground truth in data/ground_truth/<TICKER>.xlsx.

The spreadsheet is the system of record: one column per period, one row per field
(the row numbers live in src/schema.py EXCEL_ROWS). Its figures are stated in full
Rupiah, so predictions -- which come out of the filing in whatever currency and
scale it was printed in -- are normalised to Rupiah before being compared.

Two comparisons are reported per field, because they fail for different reasons:

  as-printed (USD)  isolates EXTRACTION error -- did the model read the right line?
  converted (IDR)   adds CONVERSION error    -- was the scale and rate right?

A field can be right in USD and wrong in IDR (bad rate/scale), which is a different
bug from reading the wrong row, so they are never collapsed into one number.

Predictions are cached under output/predictions/, so re-running to inspect results
costs no API calls. Use --no-cache to force a fresh extraction.

Usage:
    python scripts/run_eval.py                          # all periods
    python scripts/run_eval.py --periods Q1 Q2          # a subset
    python scripts/run_eval.py --no-cache --tolerance 0.001
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import openpyxl

from schema import FinancialStatementExtraction, EXCEL_ROWS
from normalize import to_idr, extract_fx_rate
from extract import extract_from_pdf
from llm import get_provider_with_fallback

HEADER_ROW = 3

# Spreadsheet period label -> (pdf stem, expected period end date).
# "TAHUNAN 2022" is the annual filing, which is the Q4 document.
PERIODS = {
    "Q1": ("Q1 2022", "Q1_2022_{ticker}", "2022-03-31"),
    "Q2": ("Q2 2022", "Q2_2022_{ticker}", "2022-06-30"),
    "Q3": ("Q3 2022", "Q3_2022_{ticker}", "2022-09-30"),
    "Q4": ("TAHUNAN 2022", "Q4_2022_{ticker}", "2022-12-31"),
}


def load_ground_truth(xlsx_path: Path, period_label: str) -> dict:
    """Read one period's column. Returns {field: idr_value_or_None}."""
    ws = openpyxl.load_workbook(xlsx_path, data_only=True)["Sheet1"]

    column = None
    for cell in ws[HEADER_ROW]:
        if isinstance(cell.value, str) and cell.value.strip() == period_label:
            column = cell.column_letter
            break
    if column is None:
        raise KeyError(f"No column headed {period_label!r} in row {HEADER_ROW} of {xlsx_path.name}")

    truth = {}
    for field, (row, _label) in EXCEL_ROWS.items():
        value = ws[f"{column}{row}"].value
        truth[field] = float(value) if isinstance(value, (int, float)) else None
    return truth


def predict(pdf_path: Path, cache_path: Path, use_cache: bool):
    """Extract from a filing, caching the raw (as-printed) result."""
    if use_cache and cache_path.exists():
        data = json.loads(cache_path.read_text())
        return FinancialStatementExtraction.from_dict(data), True

    result = extract_from_pdf(str(pdf_path))
    if result is None:
        return None, False

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result.to_dict(), indent=2))
    return result, False


def compare(pred, truth, rel_tol):
    """Compare one field. Returns (status, rel_error_or_None)."""
    if truth is None and pred is None:
        return "both_absent", None
    if truth is None:
        return "no_truth", None
    if pred is None:
        return "missed", None
    denominator = max(abs(truth), 1.0)
    error = abs(pred - truth) / denominator
    return ("correct" if error <= rel_tol else "wrong"), error


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="ARCI")
    ap.add_argument("--periods", nargs="*", default=list(PERIODS))
    ap.add_argument("--tolerance", type=float, default=1e-4,
                    help="relative tolerance, default 0.0001 (0.01%%)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--out", default="output")
    ap.add_argument("--provider", help="override LLM_PROVIDER for this run (gemini|ollama)")
    args = ap.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
        os.environ["LLM_FALLBACK_PROVIDER"] = ""   # comparing providers means no silent switch
    provider_tag = get_provider_with_fallback()[0].name.replace(":", "_").replace("/", "_")
    print(f"provider: {provider_tag}")

    xlsx = ROOT / "data" / "ground_truth" / f"{args.ticker}.xlsx"
    out_dir = ROOT / args.out
    report = {"ticker": args.ticker, "tolerance": args.tolerance, "periods": {}}
    tally = {"correct": 0, "wrong": 0, "missed": 0, "no_truth": 0, "both_absent": 0}

    for key in args.periods:
        label, stem, expected_date = PERIODS[key]
        pdf = ROOT / "data" / "raw" / f"{stem.format(ticker=args.ticker)}.pdf"
        if not pdf.exists():
            print(f"[{key}] SKIP - {pdf.name} not found")
            continue

        print(f"\n{'='*78}\n{key}  ({label})  {pdf.name}\n{'='*78}")
        truth = load_ground_truth(xlsx, label)

        pred, cached = predict(pdf, out_dir / "predictions" / provider_tag / f"{key}.json", not args.no_cache)
        if pred is None:
            print("  extraction failed - no fields returned")
            report["periods"][key] = {"error": "extraction_failed"}
            continue
        if cached:
            print("  (cached prediction; --no-cache to re-extract)")

        fx = extract_fx_rate(str(pdf))
        rate = fx.idr_per_usd if fx else None
        converted = to_idr(pred, pdf_path=str(pdf))["values"]

        if pred.period_end_date != expected_date:
            print(f"  ⚠ period_end_date {pred.period_end_date!r}, expected {expected_date!r}")
        if rate:
            print(f"  kurs {rate:,.2f} IDR/USD  (hal. {fx.page}, {fx.source})")

        print(f"\n  {'field':28}{'as printed':>16}{'truth (USD)':>16}{'IDR err':>10}  status")
        rows = {}
        for field in EXCEL_ROWS:
            truth_idr = truth[field]
            pred_idr = converted.get(field)
            status, err = compare(pred_idr, truth_idr, args.tolerance)
            tally[status] += 1

            raw = getattr(pred, field, None)
            truth_usd = (truth_idr / rate) if (truth_idr and rate and field != "total_share") else truth_idr
            rows[field] = {"status": status, "rel_error": err,
                           "pred_idr": pred_idr, "truth_idr": truth_idr, "pred_raw": raw}

            mark = {"correct": "OK", "wrong": "<<< WRONG", "missed": "-- missed",
                    "no_truth": "(no truth)", "both_absent": "(both empty)"}[status]
            print(f"  {field:28}"
                  f"{raw if raw is not None else '-':>16}"
                  f"{f'{truth_usd:,.0f}' if truth_usd else '-':>16}"
                  f"{f'{err:.2%}' if err is not None else '-':>10}  {mark}")

        report["periods"][key] = {"fx_rate": rate, "fields": rows}

    total_scored = tally["correct"] + tally["wrong"] + tally["missed"]
    print(f"\n{'='*78}\nSUMMARY")
    print(f"  correct      {tally['correct']:>3}")
    print(f"  wrong        {tally['wrong']:>3}")
    print(f"  missed       {tally['missed']:>3}   (truth exists, model returned nothing)")
    print(f"  no truth     {tally['no_truth']:>3}   (not scored)")
    if total_scored:
        print(f"\n  accuracy     {tally['correct']/total_scored:.1%}  ({tally['correct']}/{total_scored})")

    report["summary"] = tally
    report["provider"] = provider_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"scorecard_{provider_tag}.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\n  written to {out_dir/f'scorecard_{provider_tag}.json'}")

    return 1 if tally["wrong"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
