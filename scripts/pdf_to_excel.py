#!/usr/bin/env python3
"""
PDF to Excel, end to end: downloaded filings in, the issuer's ratio workbook out.

Four steps, each already a script of its own; this one only runs them in order and
lays the result out in the sheet the work was being done in by hand:

    1. FILE      new downloads -> ~/FinancialReport/<TICKER>/<Q>_<YYYY>_<TICKER>.pdf
                 (organize_filings: the PDF's content decides the period, duplicates
                 are caught by hash). Only with --inbox.
    2. EXTRACT   every filed PDF -> one row of <ticker>.csv (pdf_to_csv.extract_row:
                 page selection, extraction, validation, abstention, conversion to
                 full Rupiah). Incremental: a filing already in the CSV is not sent to
                 the model again unless asked, so a rerun costs nothing.
    3. PRICE     the closing price that prices each period (fetch_share_prices:
                 17 Jun / 17 Aug / 17 Nov / 17 May of the next year).
    4. EXCEL     ~/FinancialReport/<TICKER>/<TICKER>.xlsx in the layout of the ratio
                 workbooks -- rows 4-13 the filing's figures, row 14 the price, rows
                 15-22 the ratio formulas -- plus a "Catatan" sheet with every row's
                 status, abstentions and notes.

**It never writes data/ground_truth.** Those workbooks are the labels the extractor is
scored against; filling them from the extractor would make the scorecard measure the
model agreeing with itself. The output workbook has the same layout, so a column can
be compared with or copied into a label sheet by a person who has checked it.

**A value someone typed is not overwritten.** The workbook keeps a hidden sheet of what
the pipeline last wrote. A cell still holding that value is the pipeline's and follows
the new run; a cell holding anything else was edited by hand and is kept -- the
disagreement is printed, coloured and noted in the cell -- unless --overwrite is given.

**A blank is never filled with a guess.** A field the system abstained on stays empty,
coloured, with the reason in a cell comment, exactly as it is blank in the CSV.

Usage:
    # everything already in ~/FinancialReport/AKRA -> akra.csv -> AKRA.xlsx
    python scripts/pdf_to_excel.py --ticker AKRA

    # file new downloads first, then the same
    python scripts/pdf_to_excel.py --ticker TRUK --inbox ~/Downloads/idx

    # what would be filed and extracted, without filing, calling the model or writing
    python scripts/pdf_to_excel.py --ticker TRUK --inbox ~/Downloads/idx --dry-run

    # also re-ask the filings whose row is partial or failed
    python scripts/pdf_to_excel.py --ticker AKRA --retry-partial

    # re-extract named periods (after a code fix), or everything
    python scripts/pdf_to_excel.py --ticker AKRA --refresh Q1_2023 Q2_2023
    python scripts/pdf_to_excel.py --ticker AKRA --force

    # rebuild the workbook from the CSV only: no model, no network
    python scripts/pdf_to_excel.py --ticker AKRA --excel-only --no-prices

    # and list where it disagrees with the label workbook, if there is one (read-only)
    python scripts/pdf_to_excel.py --ticker AKRA --excel-only --no-prices --compare-gt
"""

import argparse
import csv
import importlib.util
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from periods import parse_period  # noqa: E402
from schema import EXCEL_ROWS  # noqa: E402

DEFAULT_ARCHIVE = Path.home() / "FinancialReport"


def variant() -> str:
    """PIPELINE_VARIANT (e.g. "claude"): a second extractor's CSV and workbook live beside
    the main ones (<t>_claude.csv, <T>_claude.xlsx) instead of replacing them."""
    return os.getenv("PIPELINE_VARIANT", "").strip().lower()
GROUND_TRUTH = ROOT / "data" / "ground_truth"


def _script(name: str):
    """A sibling script as a module. They are scripts, not a package, by design."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- workbook layout -------------------------------------------------------------------
# The ratio workbooks in data/ground_truth, row for row. D1 names the issuer: run_eval
# refuses to score a workbook whose D1 disagrees with --ticker, and a copy of this sheet
# should carry the same guard.
PRICE_ROW = 14
PRICE_LABEL = "Harga saham rupiah"
FIRST_DATA_COLUMN = 2
NUMBER = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"_);_(@_)'
RATIO_NUMBER = '_(* #,##0_);_(* \\(#,##0\\);_(* "-"??_);_(@_)'
RATIO_DECIMAL = '_(* #,##0.00_);_(* \\(#,##0.00\\);_(* "-"??_);_(@_)'
# label, formula on column letter L, number format. Copied from the workbooks as they
# are -- EPS and PE use the year-to-date profit, unannualised, because that is the
# convention of the sheet this replaces.
RATIOS = [
    (15, "Book Value per share", "={L}9/{L}13", RATIO_NUMBER),
    (16, "P1", "={L}5-{L}7", RATIO_NUMBER),
    (17, "ROA", "={L}10/{L}4", "0%"),
    (18, "ROE", "={L}10/{L}9", "0%"),
    (19, "PBV", "={L}14/{L}15", RATIO_DECIMAL),
    (20, "PE (Harga/EPS)", "={L}14/{L}21", RATIO_DECIMAL),
    (21, "EPS (Earning per Share)", "={L}10/{L}13", RATIO_NUMBER),
    (22, "DER", "={L}7/{L}9", "0%"),
]
# What the pipeline fills: the ten figures and the price.
VALUE_ROWS = {field: row for field, (row, _label) in EXCEL_ROWS.items()}
VALUE_ROWS["harga_saham"] = PRICE_ROW
LABELS = {field: label for field, (_row, label) in EXCEL_ROWS.items()}
LABELS["harga_saham"] = PRICE_LABEL
CATATAN_COLUMNS = ["periode", "file", "status", "terisi", "abstain", "issues",
                   "catatan_pipeline", "kurs", "sumber_kurs", "tanggal_harga", "harga",
                   "catatan_harga", "model"]
MISSING_FILL = "FFF4CCCC"      # blank: abstained or not found
KEPT_FILL = "FFFFE0B2"         # a hand-entered value kept against the pipeline's


def period_label(period: tuple) -> str:
    """The header the workbooks use: "Q1 2024", and "TAHUNAN 2024" for the annual report."""
    quarter, year = period
    return f"TAHUNAN {year}" if quarter == "Q4" else f"{quarter} {year}"


def period_key(period: tuple) -> str:
    return f"{period[0]}_{period[1]}"


def period_of_file(name: str):
    return parse_period("_".join(Path(name).stem.split("_")[:2]))


def _number(text):
    """A CSV cell -> int (or float), None for blank."""
    if text in (None, ""):
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) < 0.5
    except (TypeError, ValueError):
        return False


# --- step 1: file new downloads --------------------------------------------------------

def file_inbox(inbox: Path, ticker: str, archive: Path, dry_run: bool) -> tuple:
    """Copy the inbox's filings for `ticker` into the archive. Never moves, never replaces.

    -> (counts by action, targets copied -- or, in a dry run, that would be).

    A conflict (a target already holding another document) is reported and left for
    organize_filings --overwrite, which is a decision about which file is right.
    """
    org = _script("organize_filings")
    inputs = sorted(inbox.glob("*.pdf")) if inbox.is_dir() else [inbox]
    if not inputs:
        print(f"  no PDF in {inbox}")
        return {}, []
    rows = org.plan(inputs, ticker, archive)
    counts, targets = {}, []
    for row in rows:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
        if row["action"] == "skip" and row["ticker"] not in ("", ticker):
            continue                    # another issuer's file: not this run's business
        target = Path(row["target"]).name if row.get("target") else "-"
        print(f"  {row['action']:8s} {Path(row['file']).name:45s} -> {target:22s} "
              f"{row['reason']}")
        if row["action"] == "copy":
            targets.append(Path(row["target"]))
        if row["action"] == "copy" and not dry_run:
            destination = Path(row["target"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(row["file"], destination)
    if rows and not dry_run:
        manifest = archive / ticker / f"organize_manifest_{date.today().isoformat()}.csv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return counts, targets


# --- step 2: extract -------------------------------------------------------------------

def csv_path_for(folder: Path, ticker: str) -> Path:
    """<ticker>.csv, or the existing file under another case (AADI.csv, PURA.csv)."""
    if variant():
        return folder / f"{ticker.lower()}_{variant()}.csv"
    for name in (f"{ticker.lower()}.csv", f"{ticker.upper()}.csv"):
        if (folder / name).exists():
            return folder / name
    return folder / f"{ticker.lower()}.csv"


def read_csv(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        # Some archive CSVs were re-saved by Excel with ";" between fields (ARCI); the
        # rewrite after an extraction puts them back to ",".
        delimiter = ";" if handle.readline().count(";") > 3 else ","
        handle.seek(0)
        return {row["file"]: row for row in csv.DictReader(handle, delimiter=delimiter)}


def write_csv(path: Path, rows: dict, columns: list) -> None:
    """The whole table, replaced atomically: a crash mid-write leaves the old file."""
    temp = path.with_suffix(".tmp.csv")
    with open(temp, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for name in sorted(rows):
            writer.writerow({column: rows[name].get(column, "") for column in columns})
    os.replace(temp, path)


def choose(pdfs: list, existing: dict, *, force: bool, retry_partial: bool,
           refresh: set) -> list:
    """The filings to send to the model this run, and nothing it already answered."""
    chosen = []
    for pdf in pdfs:
        row = existing.get(pdf.name)
        period = period_of_file(pdf.name)
        if (force or row is None
                or (retry_partial and row.get("status") != "ok")
                or (period and period_key(period) in refresh)):
            chosen.append(pdf)
    return chosen


# An LLM error that more calls will not cure. Stopping is the rule here (CLAUDE.md: quotas
# are not worked around), and every later filing would only fail the same way.
_QUOTA_WORDS = ("quota", "resource_exhausted", "resource exhausted", "429", "rate limit")


def extract_missing(pdfs: list, csv_path: Path, existing: dict,
                    pending: list = None) -> tuple:
    """Run the extractor on `pdfs`, saving the CSV after every filing. -> (rows, stopped).

    With the Claude Code provider a filing may wait for answers; it is appended to
    `pending` and keeps its previous row, if it had one."""
    p2c = _script("pdf_to_csv")
    from claudecode import AnswerPending
    rows = dict(existing)
    if existing and pdfs:
        shutil.copy2(csv_path, csv_path.with_suffix(".csv.bak"))
    for index, pdf in enumerate(pdfs, 1):
        print(f"\n  [{index}/{len(pdfs)}] {pdf.name}")
        try:
            row = p2c.extract_row(pdf)
        except AnswerPending as exc:
            print(f"  … waiting: {exc}")
            if pending is not None:
                pending.append((pdf.name, exc.keys))
            continue
        error = str(row.get("error") or "")
        if row.get("status") == "error" and any(w in error.lower() for w in _QUOTA_WORDS):
            print(f"  ✗ stopped: {error}")
            # The old row, if any, is better than an error row about the quota.
            if pdf.name not in rows:
                rows[pdf.name] = row
                write_csv(csv_path, rows, p2c.COLUMNS)
            return rows, f"{pdf.name}: {error}"
        rows[pdf.name] = row
        write_csv(csv_path, rows, p2c.COLUMNS)
        note = error or (f"{row['fields_filled']} fields"
                         + (f", abstained: {row['abstained']}" if row["abstained"] else ""))
        print(f"  -> {row['status']}: {note}")
    return rows, None


# --- step 3: price ---------------------------------------------------------------------

def fetch_prices(ticker: str, periods: list) -> dict:
    """{period: price row}. A network failure leaves the prices out, it does not stop."""
    fsp = _script("fetch_share_prices")
    try:
        rows = fsp.collect(ticker, periods)
    except Exception as exc:                      # noqa: BLE001 - reported, not fatal
        print(f"  ✗ prices not fetched: {type(exc).__name__}: {exc}")
        return {}
    return {parse_period(row["period"]): row for row in rows}


# --- step 4: workbook ------------------------------------------------------------------

def read_workbook(path: Path) -> tuple:
    """(values, pipeline) from an earlier run of this script.

    values:   {(period, field): value} as the sheet holds it now, edits included
    pipeline: {(period, field): value} as this script last wrote it (hidden sheet)
    """
    values, pipeline = {}, {}
    if not path.exists():
        return values, pipeline
    import openpyxl
    book = openpyxl.load_workbook(path)
    sheet = book["Sheet1"] if "Sheet1" in book.sheetnames else book.active
    # Rows by label, columns by header: an inserted row or column still lands right.
    wanted = {label.strip().lower(): field for field, label in LABELS.items()}
    rows = {}
    columns = {}
    for row in sheet.iter_rows(min_row=1, max_row=40):
        for cell in row:
            if not isinstance(cell.value, str):
                continue
            text = cell.value.strip().lower()
            if cell.column == 1 and text in wanted:
                rows[wanted[text]] = cell.row
            period = parse_period(cell.value)
            if period:
                columns[period] = cell.column
    for field, row in rows.items():
        for period, column in columns.items():
            value = sheet.cell(row=row, column=column).value
            if value not in (None, ""):
                values[(period, field)] = value
    if "_pipeline" in book.sheetnames:
        for key, field, value in book["_pipeline"].iter_rows(min_row=2, values_only=True):
            period = parse_period(key)
            if period and field:
                pipeline[(period, field)] = value
    return values, pipeline


def merge(new: dict, values: dict, pipeline: dict, overwrite: bool) -> tuple:
    """Decide every cell. -> (final, last_pipeline, kept)

    final:          {(period, field): value} to write
    last_pipeline:  what the pipeline has produced, for the hidden sheet
    kept:           {(period, field): pipeline value} where a hand edit was kept
    """
    final, last, kept = {}, dict(pipeline), {}
    for key in set(new) | set(values):
        produced = new.get(key)
        current = values.get(key)
        if produced is not None:
            last[key] = produced
        if current is None:
            final[key] = produced
        elif produced is None or _same(current, produced):
            final[key] = current            # this run abstained, or it agrees
        elif key in pipeline and _same(current, pipeline[key]):
            final[key] = produced           # the pipeline's own cell: follow the new run
        elif overwrite:
            final[key] = produced
        else:
            final[key] = current            # typed by someone: theirs
            kept[key] = produced
    return final, last, kept


def _abstention_reason(row: dict, field: str) -> str:
    try:
        details = json.loads(row.get("abstention_details") or "{}")
    except ValueError:
        details = {}
    reasons = (details.get(field) or {}).get("reasons") or []
    if reasons:
        return "Abstain: " + "; ".join(str(r) for r in reasons)[:400]
    if row.get("status") == "error":
        return f"Ekstraksi gagal: {row.get('error', '')}"[:400]
    return "Tidak ditemukan di halaman yang dibaca."


def write_workbook(path: Path, ticker: str, csv_rows: dict, prices: dict,
                   overwrite: bool = False) -> dict:
    """Build the workbook. -> summary {"periods", "blank", "kept"}."""
    import openpyxl
    from openpyxl.comments import Comment
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    lock = path.with_name("~$" + path.name)
    if lock.exists():
        raise RuntimeError(f"{path.name} is open in Excel ({lock.name} exists); close it "
                           f"first -- Excel would overwrite this run when it saves")

    by_period = {}
    for name, row in csv_rows.items():
        period = period_of_file(name)
        if period:
            by_period[period] = row
    new = {}
    for period, row in by_period.items():
        for field in EXCEL_ROWS:
            new[(period, field)] = _number(row.get(field))
    for period, price in prices.items():
        new[(period, "harga_saham")] = _number(price.get("price"))

    values, pipeline = read_workbook(path)
    final, last, kept = merge(new, values, pipeline, overwrite)
    periods = sorted({key[0] for key in final} | set(by_period),
                     key=lambda p: (p[1], p[0]), reverse=True)

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet["A1"] = "(HANYA YANG BISA DIATRIBUSIKAN KE ENTITAS INDUK SAJA)"
    sheet["D1"] = ticker
    sheet["A2"] = "DINYATAKAN DALAM RUPIAH"
    sheet["G2"] = "kecuali nilai nominal dan data saham"
    sheet.column_dimensions["A"].width = 59.66
    for field, row in VALUE_ROWS.items():
        sheet.cell(row=row, column=1, value=LABELS[field])
    yellow = PatternFill("solid", fgColor="FFFFFF00")
    for row, label, _formula, _fmt in RATIOS:
        sheet.cell(row=row, column=1, value=label).fill = yellow
    missing_fill = PatternFill("solid", fgColor=MISSING_FILL)
    kept_fill = PatternFill("solid", fgColor=KEPT_FILL)

    blank = []
    for offset, period in enumerate(periods):
        column = FIRST_DATA_COLUMN + offset
        letter = get_column_letter(column)
        sheet.column_dimensions[letter].width = 20.5
        header = sheet.cell(row=3, column=column, value=period_label(period))
        header.font = Font(bold=True)
        row_data = by_period.get(period)
        for field, row in VALUE_ROWS.items():
            cell = sheet.cell(row=row, column=column, value=final.get((period, field)))
            cell.number_format = NUMBER if field != "harga_saham" else "General"
            if (period, field) in kept:
                cell.fill = kept_fill
                cell.comment = Comment(f"Nilai ini diisi manual dan dipertahankan. Pipeline "
                                       f"membaca {kept[(period, field)]:,}. Jalankan dengan "
                                       f"--overwrite untuk mengganti.", "pdf_to_excel")
            elif cell.value is None:
                cell.fill = missing_fill
                if field == "harga_saham":
                    note = (prices.get(period) or {}).get("note") or "Harga tidak diambil."
                    cell.comment = Comment(note[:400], "pdf_to_excel")
                elif row_data is not None:
                    cell.comment = Comment(_abstention_reason(row_data, field),
                                           "pdf_to_excel")
                else:
                    cell.comment = Comment("Tidak ada filing PDF untuk periode ini.",
                                           "pdf_to_excel")
                blank.append(f"{period_label(period)} {field}")
            elif field == "harga_saham" and "PROVISIONAL" in \
                    str((prices.get(period) or {}).get("note", "")):
                cell.comment = Comment(prices[period]["note"][:400], "pdf_to_excel")
        for row, _label, formula, number_format in RATIOS:
            cell = sheet.cell(row=row, column=column, value=formula.format(L=letter))
            cell.number_format = number_format
    sheet.freeze_panes = "B4"

    notes = book.create_sheet("Catatan")
    notes.append(CATATAN_COLUMNS)
    for cell in notes[1]:
        cell.font = Font(bold=True)
    for period in periods:
        row = by_period.get(period, {})
        price = prices.get(period, {})
        notes.append([period_label(period), row.get("file", ""), row.get("status", ""),
                      row.get("fields_filled", ""), row.get("abstained", ""),
                      row.get("issues", ""), row.get("notes", "") or row.get("error", ""),
                      _number(row.get("fx_rate")), row.get("fx_source", ""),
                      price.get("price_date", ""), _number(price.get("price")),
                      price.get("note", ""), row.get("model", "")])
    for letter, width in zip("ABCDEFGHIJKLM", (14, 22, 9, 8, 30, 36, 60, 10, 16, 13, 10, 60, 30)):
        notes.column_dimensions[letter].width = width

    hidden = book.create_sheet("_pipeline")
    hidden.append(["periode", "field", "nilai"])
    for (period, field), value in sorted(last.items(), key=lambda kv: (kv[0][0][1],
                                                                       kv[0][0][0], kv[0][1])):
        if value is not None:
            hidden.append([period_key(period), field, value])
    hidden.sheet_state = "hidden"

    if path.exists():
        shutil.copy2(path, path.with_suffix(".xlsx.bak"))
    temp = path.with_suffix(".tmp.xlsx")
    book.save(temp)
    os.replace(temp, path)
    return {"periods": periods, "blank": blank, "kept": kept}


def compare_with_ground_truth(workbook: Path, ticker: str) -> None:
    """Read-only: every labelled cell of data/ground_truth/<TICKER>.xlsx against the output.

    A disagreement is either an extraction error or a label error; this only lists them.
    Which one it is gets decided against the PDF (the label-groundtruth skill), never by
    copying one side onto the other.
    """
    label_path = GROUND_TRUTH / f"{ticker}.xlsx"
    if not label_path.exists():
        print(f"  no ground-truth workbook for {ticker}")
        return
    ours, _ = read_workbook(workbook)
    labels, _ = read_workbook(label_path)
    compared, differ = 0, []
    for key, label in labels.items():
        if key not in ours and key[0] not in {k[0] for k in ours}:
            continue                    # a period with no filing here
        compared += 1
        if not _same(ours.get(key), label):
            differ.append((key, ours.get(key), label))
    print(f"  vs ground truth: {compared} labelled cell(s), {len(differ)} differ")
    for (period, field), mine, label in sorted(differ):
        print(f"    {period_label(period):13s} {field:28s} output {mine!s:>20}  "
              f"label {label!s:>20}")


# --- driver ----------------------------------------------------------------------------

def run(ticker: str, args) -> int:
    archive = Path(args.archive).expanduser()
    folder = archive / ticker
    if folder.resolve().is_relative_to(GROUND_TRUTH.resolve()):
        raise SystemExit("refusing to write into data/ground_truth (see the docstring)")
    print(f"\n=== {ticker} ===")

    incoming = []
    if args.inbox:
        print(f"[1/4] filing {args.inbox}")
        counts, incoming = file_inbox(Path(args.inbox).expanduser(), ticker, archive,
                                      args.dry_run)
        print(f"  {counts}" + ("  (dry run: nothing copied)" if args.dry_run else ""))
    else:
        print("[1/4] filing: skipped (no --inbox)")

    pdfs = sorted(set(folder.glob(f"*_{ticker}.pdf")) | set(incoming))
    csv_path = csv_path_for(folder, ticker)
    existing = read_csv(csv_path)
    if not pdfs and not existing:
        print(f"  no filings in {folder}")
        return 2

    refresh = {r.upper().replace(" ", "_") for r in (args.refresh or [])}
    todo = [] if args.excel_only else choose(pdfs, existing, force=args.force,
                                             retry_partial=args.retry_partial,
                                             refresh=refresh)
    if args.only:
        only = {o.upper().replace(" ", "_") for o in args.only}
        todo = [pdf for pdf in todo
                if (p := period_of_file(pdf.name)) and period_key(p) in only]
    print(f"[2/4] extract: {len(pdfs)} PDF(s), {len(existing)} already in {csv_path.name}, "
          f"{len(todo)} to send to the model")
    for pdf in todo:
        print(f"    {pdf.name}")
    if args.dry_run:
        print("  dry run: nothing extracted, nothing written")
        return 0
    pending = []
    rows, stopped = (extract_missing(todo, csv_path, existing, pending) if todo
                     else (existing, None))
    if pending:
        # Claude Code provider: prices and the workbook wait for the last round, so a
        # half-answered batch is not written out (and Yahoo is not asked every round).
        total = sum(len(keys) for _, keys in pending)
        print(f"\n… {len(pending)} filing(s) wait for {total} answer(s) from Claude: "
              f"python scripts/claude_extract.py pending --ticker {ticker}")
        for name, keys in pending:
            print(f"    {name}: {len(keys)} request(s)")
        print("  answer them, then run the same command again")
        return 3

    periods = sorted({p for p in (period_of_file(n) for n in rows) if p},
                     key=lambda p: (p[1], p[0]), reverse=True)
    if args.no_prices:
        print("[3/4] prices: skipped (--no-prices); the workbook keeps the ones it has")
        prices = {}
    else:
        print(f"[3/4] prices for {len(periods)} period(s)")
        prices = fetch_prices(ticker, periods)
        for period in periods:
            price = prices.get(period, {})
            if price.get("note"):
                print(f"    {period_label(period)}: {price.get('price') or '-'}  "
                      f"{price['note']}")

    workbook = folder / (f"{ticker}_{variant()}.xlsx" if variant() else f"{ticker}.xlsx")
    print(f"[4/4] workbook {workbook}")
    summary = write_workbook(workbook, ticker, rows, prices, overwrite=args.overwrite)
    for (period, field), produced in sorted(summary["kept"].items()):
        print(f"    ≠ {period_label(period)} {field}: kept the hand-entered value; the "
              f"pipeline read {produced:,} (--overwrite to replace)")
    print(f"  {len(summary['periods'])} period(s), {len(summary['blank'])} blank cell(s)")
    for item in summary["blank"]:
        print(f"    blank: {item}")
    if args.compare_gt:
        compare_with_ground_truth(workbook, ticker)
    if stopped:
        print(f"\n✗ extraction stopped early ({stopped}); the workbook holds what was "
              f"extracted so far. Rerun later -- filings already done are not re-sent.")
        return 1
    statuses = [rows[n].get("status") for n in rows]
    return 0 if all(s == "ok" for s in statuses) and not summary["blank"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ticker", nargs="+", required=True, help="one or more IDX tickers")
    ap.add_argument("--inbox", help="a folder (or PDF) of new downloads to file first")
    ap.add_argument("--archive", default=str(DEFAULT_ARCHIVE),
                    help=f"one folder per ticker (default {DEFAULT_ARCHIVE})")
    ap.add_argument("--retry-partial", action="store_true",
                    help="also re-extract filings whose row is partial or failed")
    ap.add_argument("--refresh", nargs="+", metavar="Q1_2023",
                    help="re-extract these periods")
    ap.add_argument("--force", action="store_true", help="re-extract every filing")
    ap.add_argument("--only", nargs="+", metavar="Q1_2023",
                    help="extract only these periods this run (others stay as they are)")
    ap.add_argument("--excel-only", action="store_true",
                    help="no extraction: rebuild the workbook from the CSV")
    ap.add_argument("--no-prices", action="store_true", help="do not fetch share prices")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace hand-entered workbook values with the pipeline's")
    ap.add_argument("--compare-gt", action="store_true",
                    help="list where the workbook disagrees with data/ground_truth (read-only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be filed and extracted; write nothing")
    args = ap.parse_args()
    worst = 0
    for ticker in args.ticker:
        worst = max(worst, run(ticker.upper(), args))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
