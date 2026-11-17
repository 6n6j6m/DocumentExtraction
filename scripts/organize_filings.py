#!/usr/bin/env python3
"""
File downloaded IDX financial statements under the name their CONTENT earns.

IDX serves its filings behind a Cloudflare bot check (both the report-list API and the
static PDF paths answer a scripted request with 403 "Just a moment..."), so they are
downloaded in a browser. This script does the part that goes wrong by hand: deciding
which file is which quarter, and noticing when two files are the same document.

**Neither the file name nor the size decides.** A name is a claim -- the archive once
held a `Q2_2023_TRUK.pdf` that was byte-identical to `Q1_2023_TRUK.pdf`, a Q1 report
under a Q2 name -- and a size says nothing about the period. The PDF says both:

  * what it IS: a financial statement prints its statement titles ("LAPORAN POSISI
    KEUANGAN", "STATEMENT OF FINANCIAL POSITION") in its first pages; an annual report
    or an auditor's letter does not;
  * which PERIOD: the latest quarter-end date in those statement headers. A balance sheet
    always names two dates ("30 Juni 2024 dan 31 Desember 2023") and the current period
    is always the later one;
  * whether it is a DUPLICATE: its SHA-1, compared with every file already filed.

The name is used only as a hint for the ticker, and the size only to report.

    # what would happen (nothing is written)
    python scripts/organize_filings.py ~/Downloads/idx --ticker TRUK

    # copy into ~/FinancialReport/TRUK/ as <Q>_<YYYY>_TRUK.pdf
    python scripts/organize_filings.py ~/Downloads/idx --ticker TRUK --apply

A manifest CSV records every decision and its reason.
"""

import argparse
import csv
import hashlib
import re
import shutil
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_ARCHIVE = Path.home() / "FinancialReport"
ISSUERS = ROOT / "data" / "issuers.json"            # scripts/fetch_issuers.py writes it
ISSUERS_EXTRA = ROOT / "data" / "issuers_extra.json"  # by hand: newer listings, old names
SCAN_PAGES = 25            # statements sit in the first pages of every IDX filing

# Spaces are optional: some PDFs extract with every word glued ("LAPORANPOSISIKEUANGAN",
# "TANGGAL31DESEMBER2023" in PGN's 2023 annual statements).
_STATEMENT_TITLE = re.compile(
    r"laporan\s*posisi\s*keuangan|statements?\s*of\s*financial\s*position|\bneraca\b|"
    r"laporan\s*laba\s*rugi|statements?\s*of\s*(?:profit|comprehensive)|"
    r"laporan\s*arus\s*kas|statements?\s*of\s*cash\s*flows?", re.I)
_ANNUAL_REPORT = re.compile(r"laporan\s+tahunan|annual\s+report", re.I)
_MONTHS = {
    "januari": 1, "january": 1, "februari": 2, "february": 2, "maret": 3, "march": 3,
    "april": 4, "mei": 5, "may": 5, "juni": 6, "june": 6, "juli": 7, "july": 7,
    "agustus": 8, "august": 8, "september": 9, "oktober": 10, "october": 10,
    "november": 11, "nopember": 11, "desember": 12, "december": 12,
}
# A date never spans a line break. Two-column headers print "December 31," over a line
# whose first figure is the OTHER column's year ("2022 Notes 2021"); reading across the
# break filed Elnusa's June 2022 report as Q4 2022. The month is one of _MONTHS, not any
# run of letters, so a glued "ASOFDECEMBER31,2023" still yields December.
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATE_DMY = re.compile(rf"(?<!\d)(\d{{1,2}})[ \t]*({_MONTH})(?![a-z])[ \t]*,?[ \t]*(20\d{{2}})",
                       re.I)
_DATE_MDY = re.compile(rf"({_MONTH})[ \t]*(\d{{1,2}})[ \t]*,[ \t]*(20\d{{2}})", re.I)
QUARTER_OF = {(3, 31): "Q1", (6, 30): "Q2", (9, 30): "Q3", (12, 31): "Q4"}
# A ticker in a file name is four capitals standing alone, matched on the name as
# written: upper-casing first turned "Sept", "Juni" and random download ids
# ("DhCX8z...") into tickers and threw away genuine filings.
_TICKER_IN_NAME = re.compile(r"(?<![A-Za-z])([A-Z]{4})(?![A-Za-z])")
# The notes' general-information section often prints the listing itself: Elnusa writes
# 'dengan kode perdagangan "ELSA"'. Not every issuer does (AKR Corporindo's first 40 pages
# never say "AKRA"), so a missing code proves nothing; a printed one is the best evidence.
_TRADING_CODE = re.compile(
    r"(?:kode\s+(?:perdagangan|saham|efek|emiten|bursa)|"
    r"(?:ticker|stock|trading)\s+(?:code|symbol))"
    r"\s*[:\-]?\s*[\"\u201c\u201d'\u2018\u2019(]?\s*([A-Z]{4})(?![A-Za-z])", re.I)


def sha1_of(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quarter_end_dates(text: str) -> list:
    """Every quarter-end date written in `text`, as date objects."""
    found = []
    for day, month, year in _DATE_DMY.findall(text):
        number = _MONTHS.get(month.lower())
        if number and (number, int(day)) in QUARTER_OF:
            found.append(date(int(year), number, int(day)))
    for month, day, year in _DATE_MDY.findall(text):
        number = _MONTHS.get(month.lower())
        if number and (number, int(day)) in QUARTER_OF:
            found.append(date(int(year), number, int(day)))
    return found


def read_head(path: Path) -> dict:
    """{page: text} for the first pages, OCR'd where the text layer is unreadable."""
    import io
    import contextlib
    import pdfplumber
    from pdftext import page_texts
    with pdfplumber.open(path) as pdf:
        total = len(pdf.pages)
    with contextlib.redirect_stdout(io.StringIO()):
        return page_texts(str(path), list(range(min(SCAN_PAGES, total)))), total


HEAD_LINES = 8               # a statement's title sits in its first lines
# A name never runs into a second "PT": Elnusa's text layer glues "PT ELNUSATBKDAN ENTITAS
# ANAKNYA PT ELNUSA TBK" together, and the name is the second one.
_COMPANY = re.compile(r"\bPT\.?\s+[A-Z](?:(?!\bPT\b)[A-Za-z0-9 .&-]){2,60}?\s+(?i:Tbk)\b")


def _head(text, lines: int) -> str:
    return "\n".join((text or "").split("\n")[:lines])


def identify(path: Path) -> dict:
    """What a PDF is and which period it reports, read from its own pages."""
    texts, total = read_head(path)
    statement_pages = [n for n, t in sorted(texts.items()) if _STATEMENT_TITLE.search(t or "")]
    # Only a page HEADED by a statement title dates the report. A notes page that mentions
    # "laporan posisi keuangan" in its body heads itself with the period and then quotes
    # the comparative ("31 Desember 2024") line after line: PURA's Q3 2025 notes outvoted
    # its statements and filed it as Q4 2024.
    headed = [n for n in statement_pages if _STATEMENT_TITLE.search(_head(texts[n], HEAD_LINES))]
    if not statement_pages:
        kind = "annual_report" if any(_ANNUAL_REPORT.search(t or "") for t in texts.values()) \
            else "not_a_financial_statement"
        return {"kind": kind, "pages": total, "period": None, "company": None,
                "reason": "no statement title in the first pages"}
    # The header block of each statement page names the period and its comparative. The
    # current period is the date printed MOST often there: it heads every page in the
    # title and again over the first column, while the comparative only heads a column.
    # The latest date is not safe -- TRUK's 2022 interims misprint the audited
    # comparative as "December 31, 2022" -- and neither is a "per/as of" title line:
    # PURA's titles carry no such word, and a notes sentence ("tahun yang berakhir 31
    # Desember 2024 dan 2023") does.
    counts = Counter()
    for n in headed or statement_pages:
        counts.update(quarter_end_dates(_head(texts[n], 12)))
    if not counts:
        return {"kind": "financial_statement", "pages": total, "period": None,
                "company": None, "reason": "statement pages found but no period date "
                                           "in their headers"}
    latest = max(counts, key=lambda d: (counts[d], d))
    codes = {m.group(1).upper() for t in texts.values() for m in _TRADING_CODE.finditer(t or "")}
    code = codes.pop() if len(codes) == 1 else None
    # The issuer's name heads each statement page; the first "PT ... Tbk" anywhere may be
    # its parent ("Entitas Induk: PT Salim Ivomas Pratama Tbk" in LSIP's notes).
    heads = Counter(" ".join(m.group(0).split()) for n in (headed or statement_pages)
                    for m in _COMPANY.finditer(_head(texts[n], 4)))
    company = max(heads, key=heads.get) if heads else None
    for t in ([] if company else texts.values()):
        match = _COMPANY.search(t or "")
        if match:
            company = " ".join(match.group(0).split())
            break
    return {"kind": "financial_statement", "pages": total,
            "period": (QUARTER_OF[(latest.month, latest.day)], latest.year),
            "company": company, "code": code,
            "reason": f"most frequent statement-header date {latest.isoformat()} "
                      f"({counts[latest]} of {sum(counts.values())})"}


def tickers_in_name(path: Path, known=None) -> set:
    """Standalone four-capital tokens in a file name -- what an IDX download carries
    ("FinancialStatement-2024-I-ELSA.pdf"). Matched case-sensitively, so "Sept" or a
    random download id never qualifies."""
    return set(_TICKER_IN_NAME.findall(path.stem))


def ticker_from_name(path: Path, known: set) -> str | None:
    """Guess the ticker only from a name carrying exactly one KNOWN issuer."""
    hits = sorted(t for t in tickers_in_name(path) if t in known)
    return hits[0] if len(hits) == 1 else None


def _company_key(name: str) -> str:
    """"PT Elnusa Tbk.", "PT ELNUSA TBK" and "Bukit Asam (Persero) Tbk" vs "Bukit Asam
    Tbk." are one company each. A trailing "Tb" is Wikipedia's cut-off "Tbk"."""
    key = re.sub(r"\b(PT|TBK|PERSERO)\b\.?|\bTB\.?\s*$", " ", (name or "").upper())
    return re.sub(r"[^A-Z0-9]", "", key)


IDX_NAME_WIDTH = 30          # IDX's Daftar Saham cuts names here: "PP London Sumatra Indonesia Tb"


def load_issuers(paths=(ISSUERS, ISSUERS_EXTRA)) -> dict:
    """company key -> ticker, from the IDX listing and the hand-kept supplement (whose
    entries may add "aliases": the names a company filed under before a rename). A name
    cut at IDX's width is also kept under "<key>*", matched as a prefix by
    `issuer_of`. A name claimed by two tickers is dropped rather than guessed."""
    import json
    claims = {}
    for path in paths:
        if not Path(path).exists():
            continue
        for entry in json.loads(Path(path).read_text()).get("issuers", []):
            for name in [entry.get("name"), *entry.get("aliases", [])]:
                key = _company_key(name)
                if not key:
                    continue
                claims.setdefault(key, set()).add(entry["ticker"])
                if len(name) >= IDX_NAME_WIDTH and not re.search(r"\bTbk\.?$", name):
                    # The cut may fall inside "Tbk" ("...International T"): drop the stub.
                    stem = _company_key(re.sub(r"\s+T(?:b|bk)?\.?$", "", name))
                    claims.setdefault(stem + "*", set()).add(entry["ticker"])
    return {key: tickers.pop() for key, tickers in claims.items() if len(tickers) == 1}


def issuer_of(company: str, issuers: dict) -> str:
    """The ticker the listing gives a company name, or "" when it has none or several."""
    key = _company_key(company)
    if not key:
        return ""
    if key in issuers:
        return issuers[key]
    hits = {t for k, t in issuers.items() if k.endswith("*") and key.startswith(k[:-1])}
    return hits.pop() if len(hits) == 1 else ""


def plan(inputs: list, ticker: str | None, archive: Path, issuers: dict | None = None) -> list:
    issuers = load_issuers() if issuers is None else issuers
    known = {p.name for p in archive.iterdir() if p.is_dir()} if archive.exists() else set()
    known |= set(issuers.values())
    filed = {}                                   # sha1 -> existing path, across the archive
    if archive.exists():
        for existing in archive.glob("*/*.pdf"):
            filed.setdefault(sha1_of(existing), existing)

    # Pass 1: read every file. Nothing is decided until all of them are known, because
    # whether a file belongs to the ticker depends on what the OTHER files say.
    staged = []
    for path in inputs:
        row = {"file": str(path), "size_kb": round(path.stat().st_size / 1024),
               "sha1": sha1_of(path)}
        info = identify(path)
        row.update(kind=info["kind"], pages=info["pages"], company=info["company"] or "",
                   code=info.get("code") or "",
                   listed_as=issuer_of(info["company"] or "", issuers),
                   period=" ".join(map(str, info["period"])) if info["period"] else "",
                   replaces="")
        who = ticker or row["code"] or row["listed_as"] or ticker_from_name(path, known)
        row["ticker"] = who or ""
        staged.append((path, row, info, who))

    # One ticker, one company. The reference company comes from the strongest evidence
    # present: files that PRINT the ticker as their trading code, then files whose company
    # the IDX listing (data/issuers.json) gives that ticker, then files whose NAME
    # carries it (IDX names its downloads FinancialStatement-2024-I-ELSA.pdf), and only
    # then the most common company. A majority alone is a coin toss: ~/Downloads/idx held
    # 19 Elnusa and 19 AKR Corporindo reports, and the tie picked AKR for ELSA.
    votes = {}                           # who -> {"printed"|"named"|"all": [company keys]}
    for path, row, info, who in staged:
        named_for = tickers_in_name(path, known | ({ticker} if ticker else set()))
        if ticker and named_for and ticker not in named_for:
            continue                     # another issuer's download: it does not vote
        if ticker and (row["code"] or row["listed_as"] or ticker) != ticker:
            continue
        if who and info["kind"] == "financial_statement" and row["company"]:
            key = _company_key(row["company"])
            tiers = votes.setdefault(who, {"printed": [], "listed": [], "named": [], "all": []})
            tiers["all"].append(key)
            if row["code"] == who:
                tiers["printed"].append(key)
            if row["listed_as"] == who:
                tiers["listed"].append(key)
            if who in tickers_in_name(path, known | {who}):
                tiers["named"].append(key)
    majority, evidence, ambiguous = {}, {}, set()
    for who, tiers in votes.items():
        tier = next(t for t in ("printed", "listed", "named", "all") if tiers[t] or t == "all")
        counts = sorted(((tiers[tier].count(k), k) for k in set(tiers[tier])), reverse=True)
        if len(counts) > 1 and counts[0][0] == counts[1][0]:
            ambiguous.add(who)           # a tie names no company; refuse to guess
            continue
        majority[who], evidence[who] = counts[0][1], tier
    label = {who: next(r["company"] for _, r, _, w in staged
                       if w == who and _company_key(r["company"]) == key)
             for who, key in majority.items()}
    because = {"printed": "the files that print it as their trading code",
               "listed": "the IDX listing", "named": "the files named for it",
               "all": "most of its files"}

    rows, targets = [], {}
    for path, row, info, who in staged:
        # --ticker says which issuer is WANTED, not that every file is that issuer's: a
        # file whose name carries another ticker is someone else's download.
        named = tickers_in_name(path, known | ({ticker} if ticker else set()))
        if ticker and named and ticker not in named:
            row.update(action="skip", target="",
                       reason=f"file name names another issuer ({', '.join(sorted(named))})")
        elif ticker and row["code"] and row["code"] != ticker:
            row.update(action="skip", target="",
                       reason=f"the PDF prints trading code {row['code']}, not {ticker}")
        elif ticker and row["listed_as"] and row["listed_as"] != ticker and row["code"] != ticker:
            row.update(action="skip", target="",
                       reason=f"the PDF names {row['company']}, listed on IDX as "
                              f"{row['listed_as']}, not {ticker}")
        elif info["kind"] != "financial_statement" or not info["period"]:
            row.update(action="skip", target="", reason=info["reason"])
        elif not who:
            row.update(action="skip", target="",
                       reason="ticker unknown: pass --ticker"
                              + (f" (the PDF names {info['company']})" if info["company"] else ""))
        elif who in ambiguous and who not in (row["code"], row["listed_as"]):
            row.update(action="conflict", target="",
                       reason=f"the {who} files name different companies in equal numbers "
                              f"and none prints its trading code; cannot tell which is {who}")
        elif (row["company"] and who in majority and who not in (row["code"], row["listed_as"])
              and _company_key(row["company"]) != majority[who]):
            row.update(action="conflict", target="",
                       reason=f"the PDF names {row['company']}, but {who} is {label[who]} "
                              f"by {because[evidence[who]]}; not filed")
        else:
            quarter, year = info["period"]
            target = archive / who / f"{quarter}_{year}_{who}.pdf"
            row["target"] = str(target)
            if row["sha1"] in filed:
                origin = filed[row["sha1"]]
                where = "already filed" if Path(origin).exists() else "earlier in this batch"
                row.update(action="skip", reason=f"duplicate (same SHA-1) of {Path(origin).name}, "
                                                 f"{where}")
            elif target.exists():
                # Same report from another source (IDX's copy vs the issuer's "Released"
                # PDF) is not a conflict; a target holding ANOTHER company or period is.
                held = identify(target)
                same = (held["period"] == info["period"] and
                        _company_key(held["company"] or "") == _company_key(row["company"]))
                if same:
                    row.update(action="skip", reason=f"{target.name} already holds this "
                                                     f"company's {quarter} {year} report "
                                                     f"(different file)")
                else:
                    row.update(action="conflict", replaces=str(target),
                               reason=f"{target.name} already exists but holds "
                                      f"{held['company'] or 'an unidentified document'} "
                                      f"{' '.join(map(str, held['period'])) if held['period'] else ''}"
                                      f"; pass --overwrite to replace it")
            elif str(target) in targets:
                row.update(action="conflict", reason=f"same period as {targets[str(target)]} "
                                                     f"in this batch; check both")
            else:
                row.update(action="copy", reason=info["reason"])
                targets[str(target)] = str(path)
                filed[row["sha1"]] = target
        rows.append(row)
    return rows


def _check_dependencies() -> bool:
    missing = []
    for module in ("pdfplumber", "pdf2image", "pytesseract"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        print(f"✗ this Python ({sys.executable}) lacks {', '.join(missing)}.\n"
              f"  Install the project's requirements into it:\n"
              f"    {sys.executable} -m pip install -r {ROOT / 'requirements.txt'}\n"
              f"  or run the script with the environment that already has them.")
        return False
    return True


def main() -> int:
    if not _check_dependencies():
        return 2
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="PDF files or folders of PDFs")
    ap.add_argument("--ticker", help="the issuer to file. Files whose name carries another "
                         "ticker are skipped, and files naming a different company than "
                         "the rest are held back as conflicts")
    ap.add_argument("--archive", default=str(DEFAULT_ARCHIVE),
                    help=f"where filings are kept, one folder per ticker (default "
                         f"{DEFAULT_ARCHIVE})")
    ap.add_argument("--apply", action="store_true", help="copy the files (default: dry run)")
    ap.add_argument("--move", action="store_true", help="with --apply, move instead of copy")
    ap.add_argument("--overwrite", action="store_true",
                    help="with --apply, replace a target whose content differs")
    ap.add_argument("--manifest", help="manifest CSV path (default: next to the first input)")
    args = ap.parse_args()
    # Without --apply nothing is filed, so a lone --move or --overwrite would read as done.
    for flag in ("move", "overwrite"):
        if getattr(args, flag) and not args.apply:
            ap.error(f"--{flag} only takes effect with --apply (add --apply, or drop "
                     f"--{flag} for a dry run)")

    inputs = []
    for item in args.inputs:
        p = Path(item).expanduser()
        inputs += sorted(p.glob("*.pdf")) if p.is_dir() else [p]
    if not inputs:
        print("no PDF found")
        return 2
    archive = Path(args.archive).expanduser()
    rows = plan(inputs, args.ticker.upper() if args.ticker else None, archive)

    for row in rows:
        # Only a target holding a different document can be replaced; a company conflict
        # or two downloads of one period has nothing --overwrite could rightly do.
        if row["action"] == "conflict" and args.overwrite and row["replaces"]:
            row["action"] = "copy"
            row["reason"] += " (overwrite requested)"
        line = f"{row['action']:8s} {Path(row['file']).name:45s} -> " \
               f"{Path(row['target']).name if row['target'] else '-':22s} {row['reason']}"
        print(line)
        if args.apply and row["action"] == "copy":
            target = Path(row["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            (shutil.move if args.move else shutil.copy2)(row["file"], target)

    manifest = Path(args.manifest).expanduser() if args.manifest else \
        (inputs[0].parent / f"organize_manifest_{date.today().isoformat()}.csv")
    with open(manifest, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts = {}
    for row in rows:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
    print(f"\n{counts} -- manifest: {manifest}"
          + ("" if args.apply else "\nDry run: nothing copied. Add --apply to file them."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
