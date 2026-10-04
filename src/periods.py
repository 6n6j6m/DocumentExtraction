#!/usr/bin/env python3
"""
One place that understands what a reporting period is.

A period travels through this repo in three different spellings, and every pair of them
has silently disagreed at least once:

    a filing      Q1_2022_ARCI.pdf        quarter and year in a filename
    a sheet       "Q1 2022" / "TAHUNAN 2022"   a column header, two spellings for Q4
    a cache key   ARCI_Q1                 which lost the year entirely

The rule here is that nothing compares period *strings*. A header is parsed into a
`(quarter, year)` tuple and matched on the tuple, so "TAHUNAN 2024" and "Q4 2025" are
found by the same lookup -- the workbooks use the first spelling for 2020-2024 and the
second for 2025, and code that built a label to search for found no annual column at all
for whichever spelling it did not build.
"""

import re
from typing import Optional

# The balance-sheet date each quarter closes on. Q4 is the annual report.
QUARTER_END = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}

_PERIOD = re.compile(r"^(Q[1-4])[ _-]?(\d{4})$", re.I)
# The workbooks label the annual column "TAHUNAN 2024", not "Q4 2024" -- every sheet in
# data/ground_truth does, for every year except 2025. Read literally, a lookup found no
# Q4 column at all for 2020-2024 and silently scored three quarters a year instead of
# four. An annual column IS Q4: same balance-sheet date, same pricing date.
_ANNUAL = re.compile(r"^(?:tahunan|annual|fy)[ _-]?(\d{4})$", re.I)


def parse_period(text) -> Optional[tuple]:
    """A period header -> ("Q1", 2024). None if it is not one.

    Accepts "Q1_2024" / "Q1 2024" / "q1-2024", and "TAHUNAN 2024" as Q4 2024. Both
    spellings collapse to the same tuple on purpose: the sheet uses one for 2025 and the
    other for every earlier year, and a lookup that told them apart would write into, or
    read from, a column it had not found.
    """
    raw = str(text).strip()
    match = _PERIOD.match(raw)
    if match:
        return (match.group(1).upper(), int(match.group(2)))
    annual = _ANNUAL.match(raw)
    return ("Q4", int(annual.group(1))) if annual else None


def period_end_date(quarter: str, year: int) -> str:
    """ISO balance-sheet date for a period: ("Q1", 2022) -> "2022-03-31"."""
    return f"{year}-{QUARTER_END[quarter]}"


def parse_filing_stem(stem: str) -> Optional[tuple]:
    """"Q1_2022_ARCI" -> ("ARCI", "Q1", 2022). None if the name is not a filing.

    The repo's filing convention is <Quarter>_<Year>_<TICKER>.pdf. Tickers with an
    underscore would break this, and none exist on IDX.
    """
    parts = str(stem).split("_")
    if len(parts) < 3:
        return None
    quarter, year, ticker = parts[0].upper(), parts[1], "_".join(parts[2:]).upper()
    if quarter not in QUARTER_END or not year.isdigit() or not ticker:
        return None
    return (ticker, quarter, int(year))


def period_label(quarter: str, year: int, annual_spelling: bool = True) -> str:
    """The human label for a period, for printing only -- never for matching.

    Q4 is written "TAHUNAN <year>" by default because that is how most sheet columns and
    every scorecard to date spell it.
    """
    if quarter == "Q4" and annual_spelling:
        return f"TAHUNAN {year}"
    return f"{quarter} {year}"


def sort_key(quarter: str, year: int) -> tuple:
    """Chronological ordering for periods: oldest first."""
    return (year, int(quarter[1]))
