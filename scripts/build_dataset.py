#!/usr/bin/env python3
"""
The whole sheet, as one CSV: filings in, analysable rows out.

Three things have to meet before a filing becomes a row an analyst can use, and until
now they lived in three places:

    the ten figures        scripts/pdf_to_csv.py     read out of the PDF
    the share price        scripts/fetch_share_prices.py   the one input not in the PDF
    the eight ratios       data/ground_truth/*.xlsx  as spreadsheet formulas

This script joins them. One filing becomes one row carrying all three, so the output is
the thing the manual workflow was actually producing by hand -- not an intermediate that
still needs a spreadsheet wrapped around it.

**No extraction or pricing logic lives here.** `extract_row` and `collect` are imported
from the two scripts that own them; the ratios are the only arithmetic this file does,
and they are transcribed from the workbook rather than reinvented:

    Book Value per share  = ekuitas / total_share          (row 15 = B9/B13)
    P1                    = total_aset_lancar - liabilitas (row 16 = B5-B7)
    ROA                   = laba_bersih / aset             (row 17 = B10/B4)
    ROE                   = laba_bersih / ekuitas          (row 18 = B10/B9)
    PBV                   = harga_saham / BVPS             (row 19 = B14/B15)
    PE                    = harga_saham / EPS              (row 20 = B14/B21)
    EPS                   = laba_bersih / total_share      (row 21 = B10/B13)
    DER                   = liabilitas / ekuitas           (row 22 = B7/B9)

Four decisions worth stating, because a ratio hides its own inputs:

**A ratio is blank unless every input is present.** A field the extractor abstained on
is not zero, so a ratio built on it is not a number -- it is a guess wearing a decimal
point. `ratios_blank` names each ratio that could not be computed and why, so a blank
cell can be traced to the field that caused it rather than looking like a bug.

**Interim quarters are not annualised.** ROA, ROE, EPS and PE all divide a
period-to-date profit, exactly as the workbook does. A Q1 ROE is therefore roughly a
quarter of the annual figure, and comparing it against a Q4 one compares different
things. Annualising would be a modelling decision, and this file does not make those.

**The price is not re-derived.** It comes from `fetch_share_prices.py`, which prices a
quarter on the date its report is public (Q1 -> 17 June, Q2 -> 17 August, Q3 -> 17
November, Q4 -> 17 May of the following year) and reports the trading day actually used.

**Extraction is the expensive half.** `--from-csv` reads an existing `pdf_to_csv.py`
output and only fetches prices and computes ratios, so re-running the cheap half costs
no API calls.

Usage:
    # end to end: extract, price, compute
    python scripts/build_dataset.py --dir data/raw --ticker ARCI -o output/arci_full.csv

    # reuse an extraction you already paid for
    python scripts/build_dataset.py --from-csv output/arci.csv -o output/arci_full.csv

    # skip the network; leave price and its ratios blank
    python scripts/build_dataset.py --dir data/raw --ticker GTRA --no-prices
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from pdf_to_csv import FIELD_COLUMNS, extract_row, ticker_of  # noqa: E402
import fetch_share_prices as prices                                # noqa: E402

# The ratio columns, in the order the workbook lists them. Kept as a list rather than
# derived from the function below so the CSV's column order is stated once and cannot
# drift with a dict's insertion order.
RATIO_COLUMNS = ["bvps", "p1", "roa", "roe", "pbv", "pe", "eps", "der"]

# Of those, the ones denominated in rupiah rather than being pure ratios. They are
# printed in full: rounding a balance-sheet amount to fit a ratio's precision loses
# real money. BVPS and EPS are rupiah PER SHARE and small, so significant figures suit
# them; P1 is an amount in the trillions.
MONEY_COLUMNS = {"p1"}

COLUMNS = (
    ["file", "ticker", "period", "period_end_date", "currency", "reporting_scale", "unit"]
    + FIELD_COLUMNS
    + ["harga_saham", "price_date"]
    + RATIO_COLUMNS
    + ["status", "fields_filled", "abstained", "issues", "notes", "model",
       "price_note", "ratios_blank"]
)


def _number(value):
    """A figure, or None. CSV cells arrive as strings; a blank must stay a blank."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ratios(values: dict, price):
    """The eight derived rows, and the reason for every one that is blank.

    Returns ({name: value_or_None}, {name: reason}). Nothing is defaulted to zero: a
    missing denominator makes the ratio unknowable, not infinite, and a missing
    numerator makes it unknowable too.
    """
    out, why = {}, {}

    def div(name, numerator, denominator, num_label, den_label):
        if numerator is None:
            why[name] = f"{num_label} missing"
        elif denominator is None:
            why[name] = f"{den_label} missing"
        elif denominator == 0:
            # A real filing can print a zero -- an issuer with no equity at all, or a
            # loss-making quarter whose EPS is zero. The ratio genuinely does not exist.
            why[name] = f"{den_label} is zero"
        else:
            out[name] = numerator / denominator
            return
        out[name] = None

    aset = values.get("aset")
    lancar = values.get("total_aset_lancar")
    liabilitas = values.get("liabilitas")
    ekuitas = values.get("ekuitas")
    laba = values.get("laba_bersih")
    shares = values.get("total_share")

    div("bvps", ekuitas, shares, "ekuitas", "total_share")
    div("eps", laba, shares, "laba_bersih", "total_share")
    div("roa", laba, aset, "laba_bersih", "aset")
    div("roe", laba, ekuitas, "laba_bersih", "ekuitas")
    div("der", liabilitas, ekuitas, "liabilitas", "ekuitas")

    if lancar is None or liabilitas is None:
        out["p1"] = None
        why["p1"] = ("total_aset_lancar missing" if lancar is None
                     else "liabilitas missing")
    else:
        out["p1"] = lancar - liabilitas

    # PBV and PE stand on the two ratios above them, so a blank BVPS or EPS makes them
    # blank in turn -- the same rule that stops a derived field outliving an abstained
    # component inside the extractor.
    div("pbv", price, out.get("bvps"), "harga_saham", "bvps")
    div("pe", price, out.get("eps"), "harga_saham", "eps")

    return out, why


def _period_of(filename: str):
    """("Q1", 2024) from Q1_2024_ARCI.pdf, using the repo's own naming convention."""
    stem = Path(filename).stem
    return prices.parse_period("_".join(stem.split("_")[:2]))


def rows_from_csv(path: Path) -> list:
    """Read a pdf_to_csv output back in, whatever delimiter it was saved with.

    A workbook round-trip turns the file semicolon-separated on an Indonesian locale,
    and a reader pinned to the comma sees one column and no data.
    """
    text = path.read_text(encoding="utf-8-sig")
    sample = text.split("\n", 1)[0]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return list(csv.DictReader(text.splitlines(), delimiter=delimiter))


def price_lookup(ticker: str, periods: list, q4_same_year: bool = False) -> dict:
    """{(quarter, year): row} from fetch_share_prices, one issuer at a time."""
    if not periods:
        return {}
    found = {}
    for row in prices.collect(ticker, sorted(set(periods), reverse=True), q4_same_year):
        parsed = prices.parse_period(row["period"])
        if parsed:
            found[parsed] = row
    return found


def build(extractions: list, fetch: bool = True, q4_same_year: bool = False) -> list:
    """Join extraction rows to prices and compute the ratios. One row in, one row out."""
    quoted = {}
    if fetch:
        wanted = {}
        for source in extractions:
            ticker = source.get("ticker") or ticker_of(Path(source["file"]))
            period = _period_of(source["file"])
            if ticker and period:
                wanted.setdefault(ticker, []).append(period)
        for ticker, periods in wanted.items():
            quoted[ticker] = price_lookup(ticker, periods, q4_same_year)

    built = []
    for source in extractions:
        ticker = source.get("ticker") or ticker_of(Path(source["file"]))
        period = _period_of(source["file"])
        row = {column: "" for column in COLUMNS}

        for column in COLUMNS:
            if column in source:
                row[column] = source[column]
        row["file"] = source.get("file", "")
        row["ticker"] = ticker or ""
        row["period"] = f"{period[0]} {period[1]}" if period else ""

        values = {field: _number(source.get(field)) for field in FIELD_COLUMNS}

        price = None
        if period and ticker in quoted:
            quote = quoted[ticker].get(period)
            if quote:
                price = _number(quote["price"])
                row["harga_saham"] = quote["price"]
                row["price_date"] = quote["price_date"]
                row["price_note"] = quote["note"]
        elif not fetch:
            row["price_note"] = "prices not fetched (--no-prices)"

        computed, why = ratios(values, price)
        for name in RATIO_COLUMNS:
            value = computed.get(name)
            if value is None:
                row[name] = ""
            elif name in MONEY_COLUMNS:
                # A rupiah amount, printed whole. Six significant figures turned a
                # working capital of -5,439,896,183,644 into -5,439,900,000,000 --
                # rounding away eight million rupiah to make a ratio look tidy.
                row[name] = round(value)
            else:
                # Six significant figures: ROA and ROE are small fractions and DER is
                # not, so a fixed number of decimal places would either round one away
                # or pad the other with noise.
                row[name] = f"{value:.6g}"
        row["ratios_blank"] = "; ".join(f"{k}: {why[k]}" for k in RATIO_COLUMNS
                                        if k in why)
        built.append(row)
    return built


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Filings + share price + ratios -> one CSV row per filing.")
    ap.add_argument("pdfs", nargs="*", help="one or more PDFs to extract")
    ap.add_argument("--dir", help="take every PDF in this directory as well")
    ap.add_argument("--ticker", help="with --dir, only files named *_<TICKER>.pdf")
    ap.add_argument("--from-csv", metavar="CSV",
                    help="reuse an existing pdf_to_csv.py output instead of extracting")
    ap.add_argument("--no-prices", action="store_true",
                    help="skip the network; price and its two ratios stay blank")
    ap.add_argument("--q4-same-year", action="store_true",
                    help="price Q4 on 17 May of the SAME year (default: the next one)")
    ap.add_argument("--as-printed", action="store_true",
                    help="keep the filing's own currency and scale (no IDR conversion)")
    ap.add_argument("-o", "--out", default="output/dataset.csv")
    args = ap.parse_args()

    if args.from_csv:
        source_path = Path(args.from_csv)
        if not source_path.exists():
            print(f"not found: {source_path}")
            return 2
        extractions = rows_from_csv(source_path)
        print(f"{len(extractions)} row(s) from {source_path}")
        if args.as_printed:
            # The figures in that CSV were already converted or not; re-deciding here
            # would relabel them without touching the numbers.
            print("  (--as-printed ignored: the CSV's figures are already in one form)")
    else:
        from pdf_to_csv import collect as collect_pdfs
        files = collect_pdfs(args.pdfs, args.dir, args.ticker)
        if not files:
            print("no PDFs given (pass paths, --dir, or --from-csv)")
            return 2
        missing = [f for f in files if not f.exists()]
        if missing:
            print(f"not found: {', '.join(str(f) for f in missing)}")
            return 2
        extractions = []
        for index, pdf in enumerate(files, 1):
            print(f"\n[{index}/{len(files)}] {pdf.name}")
            extracted = extract_row(pdf, as_printed=args.as_printed)
            note = extracted["error"] or f"{extracted['fields_filled']} fields"
            print(f"  -> {extracted['status']}: {note}")
            extractions.append(extracted)

    if not extractions:
        print("nothing to build")
        return 2

    print()
    rows = build(extractions, fetch=not args.no_prices, q4_same_year=args.q4_same_year)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  {'period':10} {'harga':>8} {'BVPS':>10} {'EPS':>9} {'PBV':>7} "
          f"{'PE':>7} {'ROE':>8}  blank")
    for row in rows:
        print(f"  {row['period']:10} {str(row['harga_saham'] or '-'):>8} "
              f"{row['bvps'] or '-':>10} {row['eps'] or '-':>9} "
              f"{row['pbv'] or '-':>7} {row['pe'] or '-':>7} {row['roe'] or '-':>8}  "
              f"{row['ratios_blank'][:44]}")

    complete = sum(1 for r in rows if not r["ratios_blank"])
    print(f"\n{len(rows)} row(s) -> {out}")
    print(f"  every ratio computed: {complete} | some blank: {len(rows) - complete}")
    # 0 every row fully computed, 1 something is blank. A blank is a fact, not a crash,
    # but a caller scripting this should not have to parse the CSV to find out.
    return 0 if complete == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
