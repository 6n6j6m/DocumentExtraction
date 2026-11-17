#!/usr/bin/env python3
"""
Bank Indonesia's middle rate (kurs tengah) for the US dollar at every quarter end.

A dollar filer converts to Rupiah with the rate its own notes disclose -- that is the
rate it used, and `normalize.extract_fx_rate` reads it. Some never print one: ESSA
and APEX state no period-end rate in any of their 36 filings, so every row failed
conversion. Their notes say what they would have used: "kurs tengah Bank
Indonesia" on the reporting date. This script records exactly that, from BI itself, so
the conversion uses a published rate rather than a guessed one, and the row says where
it came from.

**Source.** BI's public web service for its transaction rates (Kurs Transaksi BI),
the same figures as bi.go.id > Statistik > Informasi Kurs > Transaksi BI:

    https://www.bi.go.id/biwebservice/wskursbi.asmx/getSubKursLokal3

It gives a buying and a selling rate per day; the middle rate is their mean. For
31 March 2025 that is the 27 March fixing, (16,505.06 + 16,670.94) / 2 = 16,588.00.

**The quarter end is often not a fixing day.** 31 March 2025 fell in the Lebaran
holiday and 31 December is usually closed, so the rate is BI's last fixing ON OR BEFORE
the quarter end -- never a later one, which would describe a day after the balance
sheet -- and the date actually used is kept on every row.

**The service refuses scripts after the first request** (connection reset, even 90 s
apart), so the usual route is BI's own Excel export of the same page -- currency USD,
the date range wanted -- read with --bi-excel. Its columns are found by header (Nilai,
Kurs Jual, Kurs Beli, Tanggal), not by position.

    python scripts/fetch_fx_rates.py --bi-excel "~/Downloads/Kurs Transaksi USD.xlsx"
    python scripts/fetch_fx_rates.py                   # web service, 2021-12-31 onwards
    python scripts/fetch_fx_rates.py --since 2019-12-31
"""

import argparse
import csv
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "fx_rates_bi.csv"
SERVICE = "https://www.bi.go.id/biwebservice/wskursbi.asmx/getSubKursLokal3"
USER_AGENT = "ProjectDatasaur/0.1 (financial-statement research script)"
LOOKBACK_DAYS = 21        # long enough to cross the longest Lebaran closure
RETRIES, PAUSE_S = 3, 90    # BI resets requests that follow each other within a minute
COLUMNS = ["period_end", "rate_date", "idr_per_usd", "buy", "sell", "source"]

_ROW = re.compile(r"<nil_subkurslokal>([\d.]+)</nil_subkurslokal>\s*"
                  r"<beli_subkurslokal>([\d.]+)</beli_subkurslokal>\s*"
                  r"<jual_subkurslokal>([\d.]+)</jual_subkurslokal>\s*"
                  r"<tgl_subkurslokal>(\d{4}-\d{2}-\d{2})")


def quarter_ends(since: date, until: date) -> list:
    """Every quarter end from `since` to `until`, inclusive."""
    ends = []
    for year in range(since.year, until.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            end = date(year, month, day)
            if since <= end <= until:
                ends.append(end)
    return ends


def fetch_fixings(start: date, end: date) -> dict:
    """BI's USD fixings between two dates: {date: (buy, sell)} per one dollar.

    The service resets connections that come in quick succession, so a failed request
    waits and is tried again a few times; it is not hammered."""
    query = urllib.parse.urlencode({"mts": "USD", "startdate": start.isoformat(),
                                    "enddate": end.isoformat()})
    request = urllib.request.Request(f"{SERVICE}?{query}", headers={"User-Agent": USER_AGENT})
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8")
            break
        except OSError:
            if attempt == RETRIES - 1:
                raise
            time.sleep(PAUSE_S * (attempt + 1))
    fixings = {}
    for unit, buy, sell, day in _ROW.findall(body):
        # Quoted per `unit` dollars; USD is quoted per one, but a unit is never assumed.
        fixings[date.fromisoformat(day)] = (float(buy) / float(unit), float(sell) / float(unit))
    return fixings


def _bi_number(cell) -> float:
    """'14.391,60' (BI's export writes numbers as Indonesian-formatted text) -> 14391.6."""
    if isinstance(cell, (int, float)):
        return float(cell)
    return float(str(cell).strip().replace(".", "").replace(",", "."))


def _bi_date(cell) -> date:
    """'12/1/2021 12:00:00 AM' (month first) or a real Excel date -> date."""
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    return datetime.strptime(str(cell).strip().split()[0], "%m/%d/%Y").date()


def fixings_from_excel(path: Path) -> dict:
    """BI's USD fixings from its Kurs Transaksi Excel export: {date: (buy, sell)}."""
    import openpyxl

    sheet = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = sheet.iter_rows(values_only=True)
    for header in rows:
        names = [str(c).strip().lower() if c is not None else "" for c in header]
        if {"nilai", "kurs jual", "kurs beli", "tanggal"} <= set(names):
            break
    else:
        raise ValueError(f"{path}: no header row with Nilai, Kurs Jual, Kurs Beli, Tanggal")
    col = {name: names.index(name) for name in ("nilai", "kurs jual", "kurs beli", "tanggal")}
    fixings = {}
    for row in rows:
        if row[col["tanggal"]] in (None, ""):
            continue
        unit = _bi_number(row[col["nilai"]])
        fixings[_bi_date(row[col["tanggal"]])] = (_bi_number(row[col["kurs beli"]]) / unit,
                                                  _bi_number(row[col["kurs jual"]]) / unit)
    return fixings


def middle_rate_at(period_end: date, fixings: dict):
    """The row for one quarter end, from BI's last fixing on or before it; None if BI
    published none in the lookback window."""
    days = [d for d in fixings if period_end - timedelta(days=LOOKBACK_DAYS) <= d <= period_end]
    if not days:
        return None
    day = max(days)
    buy, sell = fixings[day]
    return {"period_end": period_end.isoformat(), "rate_date": day.isoformat(),
            "idr_per_usd": round((buy + sell) / 2, 2), "buy": buy, "sell": sell,
            "source": "Bank Indonesia Kurs Transaksi (kurs tengah = (beli+jual)/2)"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", type=date.fromisoformat, default=date(2021, 12, 31))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bi-excel", type=Path,
                        help="BI's Kurs Transaksi USD Excel export, instead of the web service")
    args = parser.parse_args()

    ends = quarter_ends(args.since, date.today())
    fixings = {}
    if args.bi_excel:
        fixings = fixings_from_excel(args.bi_excel.expanduser())
        # A quarter end after the export's last fixing would silently take a stale rate.
        ends = [e for e in ends if e <= max(fixings)]
    else:
        # One request per year (about 245 fixings), not one per quarter.
        for year in range(ends[0].year, ends[-1].year + 1):
            start = max(date(year, 1, 1), ends[0] - timedelta(days=LOOKBACK_DAYS))
            fixings.update(fetch_fixings(start, min(date(year, 12, 31), ends[-1])))
            time.sleep(PAUSE_S)

    rows, missing = [], []
    for period_end in ends:
        row = middle_rate_at(period_end, fixings)
        if row is None:
            missing.append(period_end.isoformat())
            continue
        rows.append(row)
        print(f"{row['period_end']}  {row['idr_per_usd']:>10,.2f}  (fixing {row['rate_date']})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    if missing:
        print(f"no BI fixing within {LOOKBACK_DAYS} days before: {', '.join(missing)}",
              file=sys.stderr)
    print(f"{len(rows)} quarter ends -> {args.out}")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
