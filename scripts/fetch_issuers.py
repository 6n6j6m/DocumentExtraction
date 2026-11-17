#!/usr/bin/env python3
"""
Build data/issuers.json: every company listed on the IDX, ticker -> legal name.

The list is the reference `organize_filings.py` uses to tell which issuer a PDF belongs
to when the PDF does not print its own trading code (AKR Corporindo's reports never say
"AKRA"; Elnusa's say 'kode perdagangan "ELSA"').

Two sources, merged:

  * **IDX's own "Daftar Saham"** (idx.co.id > Data Pasar > Data Saham > Daftar Saham,
    exported to Excel in a browser: the site answers scripts with a Cloudflare 403, and
    that check is not worked around). Current and authoritative, so it decides which
    tickers exist and their current names. It cuts names at 30 characters ("PP London
    Sumatra Indonesia Tb") and has no sector.
  * **Indonesian Wikipedia's** "Daftar perusahaan yang tercatat di Bursa Efek Indonesia",
    read through the MediaWiki API. Older (its revision and "as of" date are recorded),
    but it carries the sector, and a name it holds that IDX no longer uses is kept as an
    alias: filings from before a rename print the old name.

A ticker Wikipedia has and IDX no longer lists is kept with "in_idx_list": false, since
its old filings still need a name.

    python scripts/fetch_issuers.py --idx-excel "~/Downloads/Daftar Saham  - 20261101.xlsx"
    python scripts/fetch_issuers.py                 # Wikipedia only
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DEFAULT_OUT = ROOT / "data" / "issuers.json"
API = "https://id.wikipedia.org/w/api.php"
PAGE = "Daftar perusahaan yang tercatat di Bursa Efek Indonesia"
USER_AGENT = "ProjectDatasaur/0.1 (financial-statement research script)"

_CODE = re.compile(r"\{\{\s*BEI\s*\|\s*([A-Z0-9]{4})\s*\}\}")
_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]")
_DATE = re.compile(r"\{\{\s*tanggal mulai\s*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})")
_IDX_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6,
               "jul": 7, "agu": 8, "agt": 8, "aug": 8, "sep": 9, "okt": 10, "oct": 10,
               "nov": 11, "des": 12, "dec": 12}
_FILE_DATE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
_AS_OF = re.compile(r"Per\s+\{\{\s*tanggal mulai\s*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})")


def fetch_wikitext(page: str = PAGE) -> tuple:
    """(wikitext, revision id) of the page's current revision."""
    query = urllib.parse.urlencode({"action": "parse", "page": page, "prop": "wikitext|revid",
                                    "format": "json", "formatversion": 2})
    request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        parsed = json.load(response)["parse"]
    return parsed["wikitext"], parsed["revid"]


def _plain(cell: str) -> str:
    """A wikitext cell as text: links reduced to their label, markup and sort keys dropped."""
    cell = cell.split("|", 1)[1] if cell.startswith("data-sort-value") else cell
    cell = _LINK.sub(r"\1", cell)
    cell = re.sub(r"'{2,}", "", cell)
    return " ".join(cell.split())


def parse_rows(wikitext: str) -> list:
    """One dict per table row that carries a {{BEI|CODE}} cell."""
    issuers = []
    for block in wikitext.split("\n|-"):
        match = _CODE.search(block)
        if not match:
            continue
        cells = [c[1:].strip() for c in block.split("\n") if c.startswith("|")
                 and not c.startswith("|}")]
        at = next(i for i, c in enumerate(cells) if _CODE.search(c))
        rest = cells[at + 1:] + [""] * 5
        listed = _DATE.search(rest[1])
        issuers.append({
            "ticker": match.group(1),
            "name": _plain(rest[0]),
            "listed": date(*map(int, listed.groups())).isoformat() if listed else None,
            "board": _plain(rest[3]) or None,
            "sector": _plain(rest[4]) or None,
        })
    return issuers


def read_idx_excel(path: Path) -> list:
    """Rows of IDX's Daftar Saham export: No, Kode, Nama Perusahaan, Tanggal Pencatatan,
    Saham, Papan Pencatatan. Columns are found by header, not position."""
    import openpyxl
    sheet = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    rows = sheet.iter_rows(values_only=True)
    header = [str(h or "").strip().lower() for h in next(rows)]
    col = {name: header.index(name) for name in
           ("kode", "nama perusahaan", "tanggal pencatatan", "papan pencatatan")}
    issuers = []
    for row in rows:
        code = str(row[col["kode"]] or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{4}", code):
            continue
        listed = None
        match = re.match(r"(\d{1,2})\s+([A-Za-z]{3})\w*\s+(\d{4})",
                         str(row[col["tanggal pencatatan"]] or ""))
        if match and match.group(2).lower() in _IDX_MONTHS:
            listed = date(int(match.group(3)), _IDX_MONTHS[match.group(2).lower()],
                          int(match.group(1))).isoformat()
        issuers.append({"ticker": code,
                        "name": " ".join(str(row[col["nama perusahaan"]] or "").split()),
                        "listed": listed,
                        "board": str(row[col["papan pencatatan"]] or "").strip() or None})
    return issuers


def merge(idx_rows: list, wiki_rows: list) -> tuple:
    """IDX decides the tickers and current names; Wikipedia adds sectors, old names as
    aliases, and the tickers IDX has dropped. Returns (issuers, report lines)."""
    from organize_filings import _company_key
    wiki = {w["ticker"]: w for w in wiki_rows}
    merged, renamed, new = [], [], []
    for row in idx_rows:
        entry = dict(row, in_idx_list=True)
        old = wiki.get(row["ticker"])
        if old is None:
            new.append(f"{row['ticker']} {row['name']}")
        else:
            entry["sector"] = old.get("sector")
            old_key, new_key = _company_key(old["name"]), _company_key(row["name"])
            # A cut-off name is a prefix of the full one, not a rename.
            if old_key != new_key and not (old_key.startswith(new_key) or
                                           new_key.startswith(old_key)):
                entry["aliases"] = [old["name"]]
                renamed.append(f"{row['ticker']} {old['name']} -> {row['name']}")
            elif len(old["name"]) > len(row["name"]):
                entry["aliases"] = [old["name"]]      # the uncut spelling
        merged.append(entry)
    listed = {r["ticker"] for r in idx_rows}
    dropped = [dict(w, in_idx_list=False) for t, w in wiki.items() if t not in listed]
    report = [f"{len(new)} on IDX but not on Wikipedia (listed after its snapshot)",
              *[f"  + {line}" for line in new],
              f"{len(renamed)} renamed since the Wikipedia snapshot (old name kept as alias)",
              *[f"  ~ {line}" for line in renamed],
              f"{len(dropped)} on Wikipedia but no longer on IDX (kept, in_idx_list=false)",
              *[f"  - {w['ticker']} {w['name']}" for w in dropped]]
    return merged + dropped, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--idx-excel", type=Path,
                        help="IDX's Daftar Saham export (.xlsx), downloaded in a browser")
    args = parser.parse_args()

    wikitext, revid = fetch_wikitext()
    issuers = parse_rows(wikitext)
    wiki_count = len(issuers)
    sources = {"wikipedia": {"url": f"https://id.wikipedia.org/wiki/{PAGE.replace(' ', '_')}",
                             "revision": revid}}
    if args.idx_excel:
        excel = args.idx_excel.expanduser()
        idx_rows = read_idx_excel(excel)
        stamp = _FILE_DATE.search(excel.name)
        sources["idx"] = {"file": excel.name, "rows": len(idx_rows),
                          "as_of": date(*map(int, stamp.groups())).isoformat() if stamp else None}
        issuers, report = merge(idx_rows, issuers)
        print("\n".join(report))
    as_of = _AS_OF.search(wikitext)
    stated = int(m.group(1).replace(".", "")) if (m := re.search(r"'''([\d.]+)'''", wikitext)) else None
    tickers = [i["ticker"] for i in issuers]
    duplicates = sorted({t for t in tickers if tickers.count(t) > 1})
    if duplicates:
        print(f"warning: tickers listed twice: {', '.join(duplicates)}", file=sys.stderr)

    sources["wikipedia"]["as_of"] = date(*map(int, as_of.groups())).isoformat() if as_of else None
    payload = {
        "sources": sources,
        "fetched": date.today().isoformat(),
        "count": len(issuers),
        "issuers": sorted(issuers, key=lambda i: i["ticker"]),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    print(f"Wikipedia: {wiki_count} issuers (the page states {stated}) as of "
          f"{sources['wikipedia']['as_of']}, revision {revid}")
    if "idx" in sources:
        print(f"IDX: {sources['idx']['rows']} issuers as of {sources['idx']['as_of']}")
    print(f"{len(issuers)} entries -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
