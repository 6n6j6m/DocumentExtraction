#!/usr/bin/env python3
"""
The pipeline the manual work actually needed: unstructured PDF in, structured CSV out.

One filing becomes one row. A batch becomes one row per filing, in the order given, in
the same file. That shape is not incidental -- it is the shape of the spreadsheet this
project exists to stop filling in by hand, so the output can be pasted straight into a
column of it.

Everything here is arrangement. Page selection, extraction, validation, confidence,
abstention and the currency conversion all happen in `src/`, unchanged; this script
calls them and lays the answer out flat. Nothing in this file decides what a number
means, which is what keeps it from becoming a second, divergent extractor.

Three decisions worth stating, because a CSV hides its own assumptions:

**Figures are in full Rupiah, not as printed.** The filings arrive in whatever currency
and scale the issuer chose -- ARCI in US Dollars at full units, JPFA in Rupiah at
millions -- and a column mixing those is worse than useless. `--as-printed` turns the
conversion off when you want to see what the page actually said.

**An empty cell means "not asserted", never zero.** A field can be blank because the
filing does not report it, or because the system read something and did not trust it.
Those are different facts, so `abstained` names the fields withdrawn on purpose, and
`status` distinguishes a clean row from a partial one. Anyone reading only the numeric
columns still gets a blank rather than a fabricated figure.

**A failed document still gets a row.** Fifty filings with one unreadable PDF should
produce forty-nine rows of figures and one row saying what went wrong -- not a traceback
and no file.

Usage:
    python scripts/pdf_to_csv.py data/raw/Q1_2022_ARCI.pdf
    python scripts/pdf_to_csv.py data/raw/*_JPFA.pdf -o output/jpfa.csv
    python scripts/pdf_to_csv.py --dir data/raw --ticker ARCI -o output/arci.csv
    python scripts/pdf_to_csv.py data/raw/Q3_2025_EMAS.pdf --as-printed
"""

import argparse
import csv
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from extract import (build_document_text, extract_from_pdf,  # noqa: E402
                     read_page_texts)
from llm import LLMError  # noqa: E402
from normalize import detect_scale, to_idr  # noqa: E402
from page_select import select_statement_pages  # noqa: E402
from schema import EXCEL_ROWS  # noqa: E402
from usage import Usage  # noqa: E402

# The ten scored fields, in the order they appear in the ground-truth workbook. Taking
# the order from EXCEL_ROWS rather than restating it means a column cannot drift out of
# step with the sheet it is meant to be pasted into.
FIELD_COLUMNS = list(EXCEL_ROWS)

# Identity and context first, then the figures, then everything needed to judge them.
# A reader who trusts the row can stop after the figures; a reader who does not has the
# grounds for their doubt in the same line.
COLUMNS = (
    ["file", "ticker", "period_end_date", "currency", "reporting_scale", "unit"]
    + FIELD_COLUMNS
    # total_share above is OUTSTANDING; the issued count and treasury shares it was
    # derived from are kept beside it so the adjustment can be seen, not just trusted.
    + ["saham_ditempatkan", "saham_treasuri"]
    + ["status", "fields_filled", "abstained", "issues", "notes",
       "fx_rate", "fx_source", "fx_page",
       "pages_selected", "model", "llm_calls", "tokens_in", "tokens_out", "seconds",
       "error"]
)

# <Quarter>_<Year>_<TICKER>.pdf, the convention the rest of the repo already discovers
# periods from. Anything else simply has no ticker, which is better than guessing one.
_STEM = re.compile(r"^(Q[1-4])_(\d{4})_([A-Z]{3,5})$")


def ticker_of(pdf: Path) -> str:
    match = _STEM.match(pdf.stem)
    return match.group(3) if match else ""


def _blank_row(pdf: Path) -> dict:
    row = {column: "" for column in COLUMNS}
    row["file"] = pdf.name
    row["ticker"] = ticker_of(pdf)
    return row


def extract_row(pdf: Path, as_printed: bool = False) -> dict:
    """One filing -> one row. Never raises; a failure becomes a row that says so."""
    row = _blank_row(pdf)
    started = time.time()
    usage = Usage()

    try:
        result = extract_from_pdf(str(pdf), usage=usage)
        if result is None:
            row.update(status="error", error="extraction returned no fields")
            return row
    except Exception as exc:                      # noqa: BLE001 - the row IS the report
        row.update(status="error", error=f"{type(exc).__name__}: {exc}",
                   seconds=round(time.time() - started, 1))
        return row

    confidence = getattr(result, "field_confidence", {}) or {}
    abstained = [name for name, score in confidence.items() if score.get("abstained")]
    issues = getattr(result, "issues", []) or []
    notes = []

    values = result.to_dict()
    unit = f"{result.currency or '?'} as printed"

    document_text = build_document_text(
        read_page_texts(str(pdf), select_statement_pages(str(pdf)).pages))

    # The scale the figures in this row are actually expressed in, which is not always
    # the one the model reported. The header is authoritative and normalise applies it;
    # a column that printed the model's answer instead would label a converted row with
    # a multiplier that was never used -- and this is the field where being wrong costs
    # a factor of a thousand, so the label has to describe what happened.
    scale = detect_scale(document_text) or result.reporting_scale or ""

    if not as_printed:
        # Conversion needs the filing's own disclosed rate, and refuses rather than
        # guessing one. A refusal is a fact about the document, so it lands in the row
        # instead of stopping the batch.
        try:
            converted = to_idr(result, pdf_path=str(pdf), document_text=document_text)
            values = converted["values"]
            unit = "IDR full"
            notes += converted["warnings"]
            if converted["fx"]:
                fx = converted["fx"]
                row.update(fx_rate=round(fx.idr_per_usd, 4), fx_source=fx.source,
                           fx_page=fx.page)
        except ValueError as exc:
            row.update(status="error", error=f"could not convert to IDR: {exc}",
                       seconds=round(time.time() - started, 1))
            return row
    elif scale and result.reporting_scale and scale != result.reporting_scale:
        notes.append(f"model said scale {result.reporting_scale}, header says {scale}")

    for field in FIELD_COLUMNS:
        value = values.get(field)
        # Blank, never 0: a zero here would be read as "the filing reports nothing owed".
        row[field] = "" if value is None else value

    filled = sum(1 for field in FIELD_COLUMNS if row[field] != "")
    row.update(
        period_end_date=result.period_end_date or "",
        currency=result.currency or "",
        reporting_scale=scale,
        unit=unit,
        status="ok" if filled == len(FIELD_COLUMNS) else "partial",
        fields_filled=f"{filled}/{len(FIELD_COLUMNS)}",
        abstained=" ".join(sorted(abstained)),
        issues=" ".join(sorted({i["rule"] for i in issues})),
        # Verbatim, not a rule name. These are the sentences that say the header
        # disagreed with the model, or that no header could be read at all -- the
        # reasons a reader needs to judge the row, and previously the pipeline
        # computed them and then dropped them on the floor.
        notes="; ".join(notes),
        pages_selected=" ".join(str(p) for p in getattr(result, "pages_selected", [])),
        # Which model answered. With a fallback chain, rows in one CSV can come from
        # different models; a column that does not say so makes them look like one run.
        model=getattr(result, "model", ""),
        saham_ditempatkan="" if getattr(result, "saham_ditempatkan", None) is None else result.saham_ditempatkan,
        saham_treasuri="" if getattr(result, "saham_treasuri", None) is None else result.saham_treasuri,
        llm_calls=usage.llm_calls,
        tokens_in=usage.input_tokens if usage.input_tokens is not None else "",
        tokens_out=usage.output_tokens if usage.output_tokens is not None else "",
        seconds=round(time.time() - started, 1),
    )
    return row


def collect(paths, directory, ticker):
    """The PDFs to process, in a stable order."""
    files = [Path(p) for p in paths]
    if directory:
        pattern = f"*_{ticker}.pdf" if ticker else "*.pdf"
        files += sorted(Path(directory).glob(pattern))
    return [f for f in files if f.suffix.lower() == ".pdf"]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Turn IDX filings into one CSV row each.")
    ap.add_argument("pdfs", nargs="*", help="one or more PDFs")
    ap.add_argument("--dir", help="take every PDF in this directory as well")
    ap.add_argument("--ticker", help="with --dir, only files named *_<TICKER>.pdf")
    ap.add_argument("-o", "--out", default="output/extractions.csv")
    ap.add_argument("--as-printed", action="store_true",
                    help="keep the filing's own currency and scale (no conversion)")
    ap.add_argument("--append", action="store_true",
                    help="add to an existing CSV instead of replacing it")
    args = ap.parse_args()

    files = collect(args.pdfs, args.dir, args.ticker)
    if not files:
        print("no PDFs given (pass paths, or --dir)")
        return 2

    missing = [f for f in files if not f.exists()]
    if missing:
        print(f"not found: {', '.join(str(f) for f in missing)}")
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Append only writes a header when starting a new file, so a batch split across
    # several invocations still reads as one table.
    write_header = not (args.append and out.exists())

    rows = []
    with out.open("a" if args.append else "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        if write_header:
            writer.writeheader()
        for index, pdf in enumerate(files, 1):
            print(f"\n[{index}/{len(files)}] {pdf.name}")
            row = extract_row(pdf, as_printed=args.as_printed)
            writer.writerow(row)
            handle.flush()          # a long batch is readable while it is still running
            rows.append(row)
            note = row["error"] or (f"{row['fields_filled']} fields"
                                    + (f", abstained: {row['abstained']}"
                                       if row["abstained"] else ""))
            print(f"  -> {row['status']}: {note}")

    ok = sum(1 for r in rows if r["status"] == "ok")
    partial = sum(1 for r in rows if r["status"] == "partial")
    failed = sum(1 for r in rows if r["status"] == "error")
    print(f"\n{len(rows)} row(s) -> {out}")
    print(f"  ok {ok} | partial {partial} | error {failed}")

    # 0 every row complete, 1 something is missing or failed. A partial row is not a
    # crash, but it is not a finished job either, and a caller scripting this needs to
    # be able to tell without parsing the CSV.
    return 0 if failed == 0 and partial == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
