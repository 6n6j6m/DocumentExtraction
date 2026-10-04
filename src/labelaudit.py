#!/usr/bin/env python3
"""
Auditing the ground truth itself: the deterministic half.

The scorecard's 98.9% says the extractor agrees with the labels. It cannot say whether
the labels are right, and there is a specific reason to doubt them: 95-100% of labelled
cells are byte-identical to the output of the old `pdf_to_csv.py`, so a large part of
the corpus is the system agreeing with an earlier version of itself. Every label error
found so far -- GTRA shifted by two columns, GTRA `J8` counted twice, JPFA's stale
share count, ARCI's wrong equity subtotal -- was found by hand, one at a time.

`auditagent.py` is the agent that reads the filings to find the rest. This module is
everything around it that must NOT be left to a model:

  * **screen**     free checks over every labelled cell, before any token is spent --
                   duplicated columns, factor-of-two and factor-of-1000 jumps, subtotals
                   larger than their totals. They set priorities; they are not verdicts.
  * **verify**     whether a figure the agent cites is really printed on the page it
                   names, and whether it sits under THIS period's column header rather
                   than the comparative one. A citation that fails is never evidence.
  * **convert**    printed figure x scale x the filing's own FX rate, and the sum of
                   components. Arithmetic stays in code, as it does in the extractor.
  * **compare**    the auditor's reading against any version of the labels. The
                   reading does not depend on the labels, so it is paid for once and
                   compared against the working tree, HEAD, or a deliberately corrupted
                   copy for free.
  * **inject**     corrupting a copy of the labels with known kinds of error, so the
                   auditor itself can be scored rather than believed.

Nothing here writes a workbook. Proposals are a form for a person to check.
"""

import csv
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from numfmt import grouped_numbers, parse_grouped_number, repair_digit_gaps
from schema import EXCEL_ROWS

AUDIT_FIELDS = list(EXCEL_ROWS)
# Balance-sheet stocks. A flow (revenue, profit, operating cash) is cumulative through
# the year, so Q2 being twice Q1 is what a steady business looks like, not an error.
STOCK_FIELDS = ["aset", "total_aset_lancar", "kas", "liabilitas", "utang_bank", "ekuitas"]
COUNT_FIELDS = {"total_share"}          # a number of shares: never scaled, never converted
SCALE_MULTIPLIER = {"FULL": 1, "THOUSANDS": 1_000, "MILLIONS": 1_000_000,
                    "BILLIONS": 1_000_000_000}
DEFAULT_TOLERANCE = 1e-4                # the evaluator's own default

# --- dates in a column header ------------------------------------------------------

_MONTHS = {
    "jan": 1, "januari": 1, "january": 1, "feb": 2, "februari": 2, "february": 2,
    "mar": 3, "maret": 3, "march": 3, "apr": 4, "april": 4, "mei": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6, "jul": 7, "juli": 7, "july": 7,
    "agu": 8, "agt": 8, "agustus": 8, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "okt": 10, "oktober": 10, "oct": 10,
    "october": 10, "nov": 11, "nopember": 11, "november": 11,
    "des": 12, "desember": 12, "dec": 12, "december": 12,
}
_DAY_MONTH_YEAR = re.compile(r"(\d{1,2})\s*([A-Za-z]{3,9})\.?\s*,?\s*(\d{4})")
_MONTH_DAY_YEAR = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})\s*,?\s*(\d{4})")
_NUMERIC_DATE = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})|(\d{4})-(\d{2})-(\d{2})")
QUARTER_END_DAY_MONTH = {"Q1": (31, 3), "Q2": (30, 6), "Q3": (30, 9), "Q4": (31, 12)}


def header_dates(text: str) -> list:
    """Every (day, month, year) a column header names, in either language.

    "30 Juni 2024", "June 30, 2024", "31/12/2023" and "2024-06-30" all count. A header
    that names no date returns [], which is "cannot tell", never "wrong".
    """
    found = []
    for day, month, year in _DAY_MONTH_YEAR.findall(text or ""):
        number = _MONTHS.get(month.lower())
        if number:
            found.append((int(day), number, int(year)))
    for month, day, year in _MONTH_DAY_YEAR.findall(text or ""):
        number = _MONTHS.get(month.lower())
        if number:
            found.append((int(day), number, int(year)))
    for match in _NUMERIC_DATE.finditer(text or ""):
        if match.group(1):
            found.append((int(match.group(1)), int(match.group(2)), int(match.group(3))))
        else:
            found.append((int(match.group(6)), int(match.group(5)), int(match.group(4))))
    return found


def header_matches_period(header: str, quarter: str, year: int) -> Optional[bool]:
    """True: the header names this period's end. False: it names only other dates.
    None: it names no date at all, so the header cannot decide."""
    dates = header_dates(header)
    if not dates:
        return None
    day, month = QUARTER_END_DAY_MONTH[quarter]
    return (day, month, year) in dates


# --- is the figure really on that page, and in which column ------------------------

def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def value_on_page(printed: str, page_text: str) -> bool:
    """Is this figure printed on this page?

    Two readings, because a text layer breaks figures in two different ways. Per line,
    the grouped amounts are read in column order (which a split leading digit would
    otherwise corrupt); and as a fallback the bare digit run is searched in the
    gap-repaired page, which survives a layer that tore the number apart but can also
    run two columns together -- acceptable for "is it there", which is all this asks.
    """
    value = parse_grouped_number(printed)
    if value is None:
        return False
    target = abs(value)
    if target == 0:
        return bool(re.search(r"(^|\s)[-–—]($|\s)|(^|\s)0($|\s)", page_text or "", re.M))
    for line in (page_text or "").split("\n"):
        if any(abs(abs(v) - target) < 0.5 for v in grouped_numbers(line)):
            return True
    digits = _digits(printed)
    return len(digits) >= 4 and digits in _digits(repair_digit_gaps(page_text or ""))


def column_of_value(printed: str, headers: list, rows: list) -> Optional[str]:
    """The column header a figure sits under on a rebuilt page table, or None.

    Uses `pagemd.page_table`'s geometry, not the agent's say-so: the agent reports which
    column it read, and this checks it against where the ink actually is. That is the
    deterministic answer to the most common error in the archive -- the comparative
    column taken for the current one.
    """
    value = parse_grouped_number(printed)
    if value is None or not headers:
        return None
    for row in rows:
        for index, cell in enumerate(row[1:-1], start=1):
            for token in (cell or "").split():
                parsed = parse_grouped_number(token)
                if parsed is not None and abs(abs(parsed) - abs(value)) < 0.5:
                    return headers[index] if index < len(headers) else None
    return None


# --- one reported figure -----------------------------------------------------------

@dataclass
class Part:
    """One printed figure the agent cites: a whole field, or one component of it."""
    printed_value: str
    page: int                                   # 1-indexed, as the agent sees it
    row_label: str = ""
    column_header: str = ""
    sign: int = 1
    name: str = ""
    # filled in by verify_part
    on_page: Optional[bool] = None              # None: page has no readable text layer
    column_found: Optional[str] = None          # header geometry puts the figure under
    column_check: str = "unknown"               # current | other_period | unknown
    claimed_header_check: str = "unknown"       # current | other_period | unknown
    problems: list = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return (self.on_page is not False and self.column_check != "other_period"
                and self.claimed_header_check != "other_period")


@dataclass
class Evidence:
    """What the agent says one field is, and whether that survives checking."""
    field: str
    parts: list                                 # [Part]; one part = printed directly
    scale: str = "FULL"
    currency: str = "IDR"
    note: str = ""
    value: Optional[float] = None               # full Rupiah (or a share count)
    scale_applied: Optional[int] = None
    fx_rate: Optional[float] = None
    visual_only: bool = False
    problems: list = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return bool(self.parts) and all(p.verified for p in self.parts) \
            and self.value is not None

    def to_dict(self) -> dict:
        out = asdict(self)
        out["verified"] = self.verified
        for part, raw in zip(self.parts, out["parts"]):
            raw["verified"] = part.verified
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "Evidence":
        parts = [Part(**{k: v for k, v in p.items() if k != "verified"})
                 for p in raw.get("parts") or []]
        kept = {k: v for k, v in raw.items() if k not in ("parts", "verified")}
        return cls(parts=parts, **kept)


def evidence_from_args(args: dict) -> Evidence:
    """One `report_evidence` item from the model, into an Evidence. Never raises."""
    name = str(args.get("field") or "").strip()
    components = args.get("components") or []
    parts = []
    if components:
        for c in components:
            if not isinstance(c, dict):
                continue
            sign = -1 if str(c.get("sign", "+")).strip() in ("-", "minus", "-1") else 1
            parts.append(Part(printed_value=str(c.get("printed_value") or ""),
                              page=_as_int(c.get("page", args.get("page"))),
                              row_label=str(c.get("row_label") or ""),
                              column_header=str(c.get("column_header")
                                                or args.get("column_header") or ""),
                              sign=sign, name=str(c.get("name") or "")))
    elif args.get("printed_value") not in (None, ""):
        parts.append(Part(printed_value=str(args.get("printed_value")),
                          page=_as_int(args.get("page")),
                          row_label=str(args.get("row_label") or ""),
                          column_header=str(args.get("column_header") or "")))
    return Evidence(field=name, parts=parts,
                    scale=str(args.get("scale") or "FULL").upper(),
                    currency=str(args.get("currency") or "IDR").upper(),
                    note=str(args.get("note") or ""))


def _as_int(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


class PageSource:
    """Page text and rebuilt page tables for one filing, each read once.

    Injected rather than read inside `verify_part`, so the checks can be tested with a
    dict of strings and no PDF.
    """

    def __init__(self, pdf_path: Optional[str] = None, texts: Optional[dict] = None,
                 tables: Optional[dict] = None):
        self.pdf_path = pdf_path
        self._texts = dict(texts or {})              # 0-indexed -> raw text layer
        self._tables = dict(tables or {})            # 0-indexed -> (headers, rows)

    def text(self, index: int) -> str:
        if index not in self._texts and self.pdf_path:
            from pdftext import page_texts
            self._texts.update(page_texts(self.pdf_path, [index], use_ocr=False))
        return self._texts.get(index, "") or ""

    def usable(self, index: int) -> bool:
        from pdftext import text_layer_usable
        return text_layer_usable(self.text(index))

    def table(self, index: int) -> tuple:
        if index not in self._tables:
            if not self.pdf_path:
                return [], []
            import pdfplumber
            from pagemd import page_table
            try:
                with pdfplumber.open(self.pdf_path) as pdf:
                    self._tables[index] = page_table(pdf.pages[index])
            except Exception:
                self._tables[index] = ([], [])
        return self._tables[index]


def verify_part(part: Part, source: PageSource, quarter: str, year: int,
                is_count: bool = False) -> Part:
    """Check one cited figure against its page. Records problems; never raises."""
    part.problems = []
    index = part.page - 1
    if part.page < 1:
        part.on_page = False
        part.problems.append("no page named")
        return part
    if not source.usable(index):
        # A glyph-id or scanned page: there is nothing in the text layer to check the
        # figure against. It was read from pixels, and is kept -- labelled as such.
        part.on_page = None
        part.problems.append("page has no readable text layer; figure read from the image")
    else:
        part.on_page = value_on_page(part.printed_value, source.text(index))
        if not part.on_page:
            part.problems.append(f"{part.printed_value!r} is not printed on page {part.page}")

    claimed = header_matches_period(part.column_header, quarter, year)
    part.claimed_header_check = {True: "current", False: "other_period",
                                 None: "unknown"}[claimed]
    if claimed is False:
        part.problems.append(f"the column named, {part.column_header!r}, is not the "
                             f"{quarter} {year} period")

    if part.on_page:
        headers, rows = source.table(index)
        found = column_of_value(part.printed_value, headers, rows)
        part.column_found = found
        verdict = header_matches_period(found or "", quarter, year)
        # A share count's table often carries no period header at all; "unknown" there is
        # the normal case, not a warning.
        part.column_check = {True: "current", False: "other_period",
                             None: "unknown"}[verdict]
        if verdict is False:
            part.problems.append(f"on page {part.page} that figure sits under "
                                 f"{found!r}, not the {quarter} {year} column")
    return part


def convert(evidence: Evidence, fx=None, detected_scale: Optional[str] = None) -> Evidence:
    """Printed figures -> one full-Rupiah value (or a share count). Code, not the model.

    The header's own scale wins over the agent's, for the reason `normalize.to_idr`
    gives: a scale is a word, grounding cannot check it, and it multiplies everything.
    """
    values = [parse_grouped_number(p.printed_value) for p in evidence.parts]
    if not evidence.parts or any(v is None for v in values):
        evidence.value = None
        evidence.problems.append("a cited figure could not be read as a number")
        return evidence
    printed = sum(p.sign * v for p, v in zip(evidence.parts, values))
    if evidence.field in COUNT_FIELDS:
        evidence.value, evidence.scale_applied = printed, 1
        return evidence

    scale = evidence.scale if evidence.scale in SCALE_MULTIPLIER else "FULL"
    if detected_scale and detected_scale != scale:
        evidence.problems.append(f"agent said {scale}, the page header says "
                                 f"{detected_scale}; using {detected_scale}")
        scale = detected_scale
    multiplier = SCALE_MULTIPLIER[scale]
    rate = 1.0
    if evidence.currency == "USD":
        if fx is None:
            evidence.value = None
            evidence.problems.append("USD figure but the filing discloses no rate")
            return evidence
        rate = fx.idr_per_usd
        evidence.fx_rate = rate
    evidence.scale_applied = multiplier
    evidence.value = round(printed * multiplier * rate)
    return evidence


def verify_evidence(evidence: Evidence, source: PageSource, quarter: str, year: int,
                    fx=None) -> Evidence:
    """Every check, in order. The Evidence is returned with its verdicts filled in."""
    from normalize import detect_scale
    evidence.problems = []
    if evidence.field not in AUDIT_FIELDS:
        evidence.problems.append(f"unknown field {evidence.field!r}")
        return evidence
    for part in evidence.parts:
        verify_part(part, source, quarter, year, is_count=evidence.field in COUNT_FIELDS)
    evidence.visual_only = bool(evidence.parts) and all(p.on_page is None
                                                        for p in evidence.parts)
    pages_text = "\n".join(source.text(p.page - 1) for p in evidence.parts if p.page > 0)
    detected = detect_scale(pages_text) if evidence.field not in COUNT_FIELDS else None
    return convert(evidence, fx=fx, detected_scale=detected)


def feedback(evidence: Evidence) -> dict:
    """What the agent is told after reporting, so it can correct itself.

    Nothing here comes from the labels. It says only what the FILING says about the
    citation -- not on that page, wrong column -- which is the same thing a careful
    human checker would say, and it lets the agent fix a slip on its next turn rather
    than leave it for adjudication.
    """
    problems = list(evidence.problems)
    for part in evidence.parts:
        problems.extend(part.problems)
    return {"field": evidence.field, "verified": evidence.verified,
            "value_full": evidence.value, "problems": problems or None}


# --- comparing a reading with labels ------------------------------------------------

def rel_error(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1.0)


def tolerance_for(evidence: Optional[Evidence], base: float = DEFAULT_TOLERANCE) -> float:
    """A USD figure inherits the rounding of the rate it was converted with."""
    if evidence is not None and evidence.currency == "USD":
        return max(base, 2e-3)
    return base


def cell_status(label: Optional[float], evidence: Optional[Evidence],
                base_tol: float = DEFAULT_TOLERANCE) -> str:
    """Phase-one status of one cell, from the reading alone.

      confirmed     verified reading agrees with the label
      disputed      verified reading disagrees -> adjudication
      unverifiable  the reading's citation failed the checks
      not_found     the auditor reported nothing for this field
      unlabelled    no label to check (empty means not yet labelled)
    """
    if label is None:
        return "unlabelled"
    if evidence is None or not evidence.parts:
        return "not_found"
    if not evidence.verified:
        return "unverifiable"
    if rel_error(evidence.value, label) <= tolerance_for(evidence, base_tol):
        return "confirmed"
    return "disputed"


# --- the free screen -----------------------------------------------------------------

@dataclass
class Flag:
    ticker: str
    quarter: str
    year: int
    field: Optional[str]
    kind: str
    detail: str
    severity: int = 1                    # 3 strong signal, 2 suspicious, 1 context

    def to_dict(self) -> dict:
        return asdict(self)


def _near(ratio: float, target: float, slack: float = 0.02) -> bool:
    return abs(ratio - target) <= slack * target


def screen_columns(ticker: str, columns: dict, predictions: Optional[dict] = None,
                   old_csv: Optional[dict] = None, problem: Optional[str] = None,
                   base_tol: float = DEFAULT_TOLERANCE) -> list:
    """Every free check over one workbook's labels. Signals, not verdicts.

    `columns` is `{(quarter, year): {field: value}}`, as `evalkit.load_truth_sheet`
    returns it. `predictions` is the same shape from the cached pipeline run and
    `old_csv` from the old pdf_to_csv output; both optional.
    """
    flags = []
    if problem:
        flags.append(Flag(ticker, "", 0, None, "workbook_problem", problem, 3))
    periods = sorted(columns, key=lambda p: (p[1], int(p[0][1])))

    # 1. A column equal to another column: the signature of a shifted or copied block.
    #    GTRA's Q3 2022 column equalled its Q1 2023 column in every field.
    for i, a in enumerate(periods):
        for b in periods[i + 1:]:
            same = [f for f in AUDIT_FIELDS if f not in COUNT_FIELDS
                    and columns[a].get(f) is not None and columns[a].get(f) == columns[b].get(f)]
            if len(same) >= 3:
                for period in (a, b):
                    other = b if period == a else a
                    flags.append(Flag(ticker, period[0], period[1], None, "duplicate_column",
                                      f"{len(same)} fields identical to {other[0]} {other[1]}: "
                                      f"{', '.join(same)}", 3))

    # 2. Jumps between neighbouring periods that look like arithmetic, not business.
    for f in AUDIT_FIELDS:
        series = [(p, columns[p].get(f)) for p in periods if columns[p].get(f)]
        for (p0, v0), (p1, v1) in zip(series, series[1:]):
            ratio = abs(v1 / v0) if v0 else 0
            for target, name in ((1000, "x1000"), (0.001, "/1000")):
                if _near(ratio, target, 0.2):
                    flags.append(Flag(ticker, p1[0], p1[1], f, "scale_jump",
                                      f"{name} against {p0[0]} {p0[1]}", 3))
            if f in STOCK_FIELDS:
                for target, name in ((2, "x2"), (0.5, "/2")):
                    if _near(ratio, target, 0.01):
                        flags.append(Flag(ticker, p1[0], p1[1], f, "double_jump",
                                          f"{name} against {p0[0]} {p0[1]} (within 1%)", 2))

    # 3. A part larger than its whole.
    for p in periods:
        c = columns[p]
        for part, whole in (("kas", "total_aset_lancar"), ("total_aset_lancar", "aset"),
                            ("utang_bank", "liabilitas")):
            if c.get(part) is not None and c.get(whole) is not None and c[part] > c[whole]:
                flags.append(Flag(ticker, p[0], p[1], part, "part_exceeds_total",
                                  f"{part} {c[part]:,.0f} > {whole} {c[whole]:,.0f}", 3))

    # 4. Disagreement with today's extractor, and agreement with yesterday's.
    for p in periods:
        for f in AUDIT_FIELDS:
            label = columns[p].get(f)
            if label is None:
                continue
            predicted = (predictions or {}).get(p, {}).get(f)
            if predicted is not None and rel_error(predicted, label) > base_tol:
                flags.append(Flag(ticker, p[0], p[1], f, "extractor_disagrees",
                                  f"label {label:,.0f}, current extractor {predicted:,.0f}", 2))
            old = (old_csv or {}).get(p, {}).get(f)
            if old is not None and rel_error(old, label) <= base_tol:
                flags.append(Flag(ticker, p[0], p[1], f, "equals_old_pipeline",
                                  "label is identical to the old pdf_to_csv output", 1))
    return flags


def load_old_csv(folder: Path) -> dict:
    """`{(quarter, year): {field: value}}` from every old pdf_to_csv CSV in a folder.

    Several CSVs may exist (gtra.csv, gtra2.csv); a value from any of them counts, since
    the question is only whether a label could have been copied from one.
    """
    from periods import parse_filing_stem
    out = {}
    for path in sorted(Path(folder).glob("*.csv")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        delimiter = ";" if text.split("\n", 1)[0].count(";") > text.split("\n", 1)[0].count(",") else ","
        for row in csv.DictReader(text.splitlines(), delimiter=delimiter):
            parsed = parse_filing_stem(Path(row.get("file") or "").stem)
            if not parsed:
                continue
            _, quarter, year = parsed
            for f in AUDIT_FIELDS:
                try:
                    value = float(row.get(f) or "")
                except ValueError:
                    continue
                out.setdefault((quarter, year), {}).setdefault(f, value)
    return out


# --- corrupting a copy, to score the auditor ----------------------------------------

INJECTION_KINDS = ["previous_period", "times_1000", "times_2", "swap_columns",
                   "share_from_other_period"]


def inject_errors(columns: dict, per_kind: int = 2, seed: int = 0,
                  kinds: Optional[list] = None) -> tuple:
    """(corrupted copy, answer key) -- errors of known kinds planted in known cells.

    The answer key maps `(quarter, year, field) -> kind`. The original is not touched.
    Every planted value differs from the original by more than the tolerance, or it is
    not planted: an "error" equal to the truth would count as a miss the auditor could
    never have avoided.
    """
    rng = random.Random(seed)
    corrupted = {p: dict(v) for p, v in columns.items()}
    key = {}
    periods = sorted(columns, key=lambda p: (p[1], int(p[0][1])))

    def free(p, f):
        return (p[0], p[1], f) not in key and columns[p].get(f) is not None

    def plant(p, f, value, kind):
        original = columns[p][f]
        if value is None or rel_error(value, original) <= 1e-3:
            return False
        corrupted[p][f] = value
        key[(p[0], p[1], f)] = kind
        return True

    for kind in kinds or INJECTION_KINDS:
        planted, attempts = 0, 0
        while planted < per_kind and attempts < 200:
            attempts += 1
            if kind == "swap_columns":
                if len(periods) < 2:
                    break
                i = rng.randrange(len(periods) - 1)
                a, b = periods[i], periods[i + 1]
                fields = [f for f in AUDIT_FIELDS if free(a, f) and free(b, f)]
                if not fields:
                    continue
                for f in fields:
                    plant(a, f, columns[b][f], kind)
                    plant(b, f, columns[a][f], kind)
                planted += 1
                continue
            if kind == "share_from_other_period":
                candidates = [(p, q) for p in periods for q in periods
                              if p != q and free(p, "total_share")
                              and columns[q].get("total_share") is not None]
                rng.shuffle(candidates)
                for p, q in candidates:
                    if plant(p, "total_share", columns[q]["total_share"], kind):
                        planted += 1
                        break
                else:
                    break
                continue
            p = rng.choice(periods)
            f = rng.choice(STOCK_FIELDS if kind == "times_2" else
                           [x for x in AUDIT_FIELDS if x not in COUNT_FIELDS])
            if not free(p, f):
                continue
            if kind == "times_1000":
                ok = plant(p, f, columns[p][f] * 1000, kind)
            elif kind == "times_2":
                ok = plant(p, f, columns[p][f] * 2, kind)
            else:                                   # previous_period
                index = periods.index(p)
                if index == 0 or columns[periods[index - 1]].get(f) is None:
                    continue
                ok = plant(p, f, columns[periods[index - 1]][f], kind)
            planted += int(ok)
    return corrupted, key


def diff_columns(wrong: dict, right: dict) -> dict:
    """`(quarter, year, field) -> (wrong value, right value)` for every cell a later
    version corrected. A cell emptied in the correction counts: the old value was wrong
    even when the right one could not be filled in."""
    out = {}
    for period, fields in wrong.items():
        for f, value in fields.items():
            if value is None:
                continue
            fixed = right.get(period, {}).get(f)
            if fixed is None or rel_error(value, fixed) > DEFAULT_TOLERANCE:
                out[(period[0], period[1], f)] = (value, fixed)
    return out


# --- uncertainty on a rate -----------------------------------------------------------

def bootstrap_rate(outcomes: dict, iters: int = 5000, seed: int = 0) -> dict:
    """A proportion with a cluster bootstrap interval.

    `outcomes` is `{cluster: [0/1, ...]}` -- a filing's cells share a reading and a
    scale, so they are resampled together, for the reason `evalmetrics.bootstrap_delta`
    gives.
    """
    names = sorted(k for k, v in outcomes.items() if v)
    total = sum(len(outcomes[n]) for n in names)
    if not total:
        return {"rate": None, "lo": None, "hi": None, "n": 0, "clusters": 0}
    rate = sum(sum(outcomes[n]) for n in names) / total
    rng = random.Random(seed)
    samples = []
    for _ in range(iters):
        chosen = [rng.choice(names) for _ in names]
        n = sum(len(outcomes[c]) for c in chosen)
        samples.append(sum(sum(outcomes[c]) for c in chosen) / n if n else 0.0)
    samples.sort()
    return {"rate": rate, "lo": samples[int(0.025 * (iters - 1))],
            "hi": samples[int(0.975 * (iters - 1))], "n": total, "clusters": len(names)}


# --- labels, from the working tree or from git ----------------------------------------

def read_columns(xlsx_path: Path) -> tuple:
    """(`{(quarter, year): {field: value}}`, `{(quarter, year): column letter}`).

    Unlike `evalkit.load_truth_sheet` this does not refuse a workbook whose `D1` names
    another issuer: the audit wants to read exactly such a workbook -- the HEAD versions
    of ADMR and PTBA are the case -- and reports the D1 problem as a flag instead.
    """
    import openpyxl
    from evalkit import HEADER_ROW
    from periods import parse_period
    workbook = openpyxl.load_workbook(xlsx_path, data_only=True)
    if "Sheet1" not in workbook.sheetnames:
        return {}, {}
    sheet = workbook["Sheet1"]
    columns, letters = {}, {}
    for cell in sheet[HEADER_ROW]:
        period = parse_period(cell.value) if isinstance(cell.value, str) else None
        if not period:
            continue
        letters[period] = cell.column_letter
        columns[period] = {
            name: (float(sheet[f"{cell.column_letter}{row}"].value)
                   if isinstance(sheet[f"{cell.column_letter}{row}"].value, (int, float))
                   and not isinstance(sheet[f"{cell.column_letter}{row}"].value, bool)
                   else None)
            for name, (row, _label) in EXCEL_ROWS.items()}
    return columns, letters


def workbook_at(ticker: str, version: str, gt_dir: Path, scratch: Path) -> Optional[Path]:
    """The workbook as it is on disk ("worktree"), or as git has it at a revision.

    A revision is written to a scratch file and read from there; the workbook in
    data/ground_truth is never opened for writing.
    """
    path = Path(gt_dir) / f"{ticker}.xlsx"
    if version == "worktree":
        return path if path.exists() else None
    import subprocess
    repo = Path(gt_dir).resolve()
    while not (repo / ".git").exists() and repo != repo.parent:
        repo = repo.parent
    relative = path.resolve().relative_to(repo)
    out = Path(scratch) / version.replace("/", "_") / f"{ticker}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["git", "-C", str(repo), "show", f"{version}:{relative.as_posix()}"],
                          capture_output=True)
    if done.returncode != 0:
        return None
    out.write_bytes(done.stdout)
    return out


# --- what each cell comes to --------------------------------------------------------------

FINAL_STATUSES = ["confirmed", "label_wrong", "label_confirmed_on_review", "needs_human",
                  "unadjudicated", "unverifiable", "not_found", "unlabelled"]


def adjudication_key(field_name: str, label: float) -> str:
    """Verdicts are keyed by the label they judged, so HEAD's and the working tree's
    disagreements -- and a planted error -- never borrow each other's verdict."""
    return f"{field_name}|{label:.0f}"


def final_status(label: Optional[float], evidence: Optional[Evidence],
                 adjudications: Optional[dict]) -> tuple:
    """(status, verdict or None) for one cell, after adjudication where there was one."""
    status = cell_status(label, evidence)
    if status != "disputed":
        return status, None
    verdict = (adjudications or {}).get(adjudication_key(evidence.field, label))
    if not verdict:
        return "unadjudicated", None
    return verdict.get("status", "needs_human"), verdict


# Which derived figures a wrong label would bias, for the proposal's consequence line.
CONSEQUENCE = {
    "aset": "ROA and every asset-based ratio",
    "total_aset_lancar": "the current ratio",
    "kas": "the cash ratio and net debt",
    "liabilitas": "DER and every leverage ratio",
    "utang_bank": "net debt and interest-bearing leverage",
    "ekuitas": "BVPS, ROE, PBV and DER",
    "laba_bersih": "EPS, ROE and PER",
    "pendapatan": "every margin",
    "kas_dari_aktivitas_operasi": "cash conversion",
    "total_share": "EPS, BVPS and market capitalisation",
}
