"""
Structural validation of an extraction, independent of any ground truth.

These are the checks a reader could make with only the filing in hand: the balance
sheet must balance, a part cannot exceed its whole, a share count cannot be a
fraction. They catch misread rows in production, where no labels exist -- which is
the only place it matters.

Each rule returns a ValidationIssue rather than raising, because several can fail at
once and the confidence layer weighs them together.
"""

import re
from dataclasses import dataclass

from numfmt import grouped_numbers

ERROR = "error"       # contradicts the document; something was misread
WARNING = "warning"   # suspicious but legitimately possible


@dataclass
class ValidationIssue:
    rule: str
    severity: str
    message: str
    fields: tuple          # fields implicated, so confidence can penalise precisely


def _present(*values) -> bool:
    return all(v is not None for v in values)


def validate(e) -> list:
    """Run every rule against an extraction. Returns a list of ValidationIssue."""
    issues = []

    def fail(rule, severity, message, fields):
        issues.append(ValidationIssue(rule, severity, message, tuple(fields)))

    # Assets = Liabilities + Equity. Uses TOTAL equity (including non-controlling
    # interest), not the parent-attributable figure -- the identity holds on the
    # printed total, and using the attributable one would fail by exactly the NCI.
    if _present(e.aset, e.liabilitas, e.total_ekuitas):
        gap = e.aset - (e.liabilitas + e.total_ekuitas)
        if abs(gap) > max(abs(e.aset) * 1e-6, 1):
            fail("balance_sheet_identity", ERROR,
                 f"aset - (liabilitas + total_ekuitas) = {gap:,.0f}",
                 ("aset", "liabilitas", "total_ekuitas"))

    # Containment: a subtotal cannot exceed its total.
    for part, whole in (("kas", "total_aset_lancar"),
                        ("total_aset_lancar", "aset"),
                        ("utang_bank", "liabilitas")):
        a, b = getattr(e, part), getattr(e, whole)
        if _present(a, b) and a > b:
            fail("containment", ERROR,
                 f"{part} ({a:,.0f}) exceeds {whole} ({b:,.0f})", (part, whole))

    # The two bank-debt components must sum to the derived total. A mismatch means
    # the model volunteered a total from a row it should have ignored.
    if _present(e.utang_bank, e.utang_bank_jangka_pendek, e.utang_bank_bagian_lancar):
        expected = e.utang_bank_jangka_pendek + e.utang_bank_bagian_lancar
        if abs(e.utang_bank - expected) > 1:
            fail("component_sum", ERROR,
                 f"utang_bank {e.utang_bank:,.0f} != components {expected:,.0f}",
                 ("utang_bank",))

    if _present(e.ekuitas, e.total_ekuitas, e.kepentingan_non_pengendali):
        expected = e.total_ekuitas - e.kepentingan_non_pengendali
        if abs(e.ekuitas - expected) > 1:
            fail("component_sum", ERROR,
                 f"ekuitas {e.ekuitas:,.0f} != total - NCI {expected:,.0f}", ("ekuitas",))

    # Signs. Only NCI and profit may legitimately be negative here.
    for field in ("aset", "total_aset_lancar", "kas", "liabilitas",
                  "utang_bank", "ekuitas", "pendapatan", "total_share"):
        value = getattr(e, field, None)
        if value is not None and value < 0:
            fail("negative_value", ERROR, f"{field} is negative ({value:,.0f})", (field,))

    if e.total_share is not None and e.total_share != int(e.total_share):
        fail("share_count", ERROR,
             f"total_share is not a whole number ({e.total_share})", ("total_share",))

    # Metadata needed downstream by normalisation.
    if e.currency not in ("USD", "IDR"):
        fail("currency", ERROR, f"unrecognised currency {e.currency!r}", ("currency",))
    if e.reporting_scale not in ("FULL", "THOUSANDS", "MILLIONS", "BILLIONS", None):
        fail("reporting_scale", ERROR,
             f"unrecognised scale {e.reporting_scale!r}", ("reporting_scale",))
    if e.statement_scope == "PARENT_ONLY":
        fail("statement_scope", WARNING,
             "parent-only statement; consolidated figures were expected",
             ("statement_scope",))

    # Profit exceeding revenue is possible (one-offs) but rare enough to flag.
    if _present(e.laba_bersih, e.pendapatan) and e.pendapatan > 0 \
            and e.laba_bersih > e.pendapatan:
        fail("margin", WARNING,
             f"laba_bersih ({e.laba_bersih:,.0f}) exceeds pendapatan "
             f"({e.pendapatan:,.0f})", ("laba_bersih", "pendapatan"))

    return issues


# Section headings that decide which "Utang bank" row is which.
# Wording varies by issuer, so each heading is matched on its distinguishing words
# rather than one filer's exact phrase.
# Heading classification is precedence logic, not pattern matching, because the
# phrases overlap: "Bagian lancar atas liabilitas jangka panjang" (a CURRENT heading)
# contains "liabilitas jangka panjang", and "Liabilitas jangka panjang, setelah
# dikurangi bagian lancar" (a NON-CURRENT heading) contains "bagian lancar". Whichever
# regex is tried first steals the other's line. Spelling the precedence out keeps it
# readable and makes the two exceptions explicit.
# "Bagian jangka pendek dari liabilitas jangka panjang" is PTBA's wording for the same
# heading others call "Bagian lancar" -- the current portion by another name.
_RE_BAGIAN = re.compile(
    r"bagian\s+lancar|bagian\s+jangka\s+pendek|jatuh\s+tempo|"
    r"(?<!non-)(?<!non )current\s+(?:portion|maturit)", re.I)
_RE_NETTING = re.compile(r"dikurangi|setelah|net\s+of", re.I)
_RE_PANJANG = re.compile(
    r"(liabilitas|kewajiban)\s+jangka\s+panjang|long[\s-]+term\s+liabilities", re.I)
_RE_PENDEK = re.compile(
    r"(liabilitas|kewajiban)\s+jangka\s+pendek|(?<!non-)(?<!non )current\s+liabilities", re.I)


def _section_of(line: str):
    """Which bank-debt section a heading line opens, or None if it is not a heading."""
    mentions_current_portion = _RE_BAGIAN.search(line)
    is_netted_off = _RE_NETTING.search(line)

    # "Bagian lancar atas liabilitas jangka panjang:" -- the current portion.
    if mentions_current_portion and not is_netted_off:
        return "current_maturity"
    # "Liabilitas jangka panjang, setelah dikurangi bagian lancar:" -- what remains.
    if _RE_PANJANG.search(line) or (is_netted_off and mentions_current_portion):
        return "long_term"
    if _RE_PENDEK.search(line):
        return "short_term"
    return None


# The row itself, by concept rather than by one issuer's wording. A bank borrowing is
# labelled "Utang bank" by ARCI and JPFA, "Pinjaman bank" by GTRA, "Hutang bank" by
# older filings and "Bank loans" in the English column -- all the same line. Matching
# only the first of those silently disarmed this whole check for GTRA: the position
# map came back empty on every one of its fifteen filings, and the warning that says
# so fired every time without anyone reading it. The prompt was rewritten to describe
# this row by meaning; a validator that still matches one label makes the prompt's
# generalisation moot, because the check behind it only works for the issuer it was
# written against.
# Only the label. The amounts are read separately, by column, because a row's note
# reference sits between the two and is itself digits -- "Utang bank 2c,4
# 1.092.421.914.566". A pattern that tries to skip from the label to the first amount
# with [^\d]*? cannot get past that reference, so it matched nothing on any row that
# carries one, and the position check quietly did not run.
_BANK_ROW = re.compile(
    r"^\s*(?:(?:utang|hutang|pinjaman|liabilitas|kewajiban)\s+bank\b|"
    r"bank\s+loans?\b)", re.I)


def _bank_rows_by_section(document_text: str) -> dict:
    """Map each section to the 'Utang bank' amount printed under it.

    Reads the page the way a person does -- downwards from the nearest heading --
    which is the one piece of context a flattened text layer destroys.
    """
    found = {}
    for section, amounts in _bank_row_amounts(document_text):
        found.setdefault(section, [])
        found[section].extend(amounts)
    return found


def _bank_row_amounts(document_text: str, with_text: bool = False) -> list:
    """[(section, [amounts in column order])] -- one entry per bank row, plus an empty
    entry for each section heading seen, so a section with no rows is still known.
    With `with_text`, each entry also carries the row's text ("" for a heading)."""
    out = []
    found, current = {}, None
    lines = document_text.splitlines()
    for i, line in enumerate(lines):
        # PDF text extraction often wraps one section heading over two or three lines
        # and puts the amount on a continuation line after the lender label. Use a
        # short rolling window to recover that layout without joining separate rows.
        if line.startswith("--- PAGE "):
            current = None
            continue
        # A heading carries no figures. Only a run of figure-free lines -- a heading
        # wrapped over two or three lines -- is read as one, and a line with figures
        # never changes the section. The old window took any four lines, so on ADMR
        # Q1 2024 "Pinjaman dari pihak berelasi - current portion 5,235,602" (a ROW)
        # sat in the window of "LIABILITAS JANGKA PANJANG", current maturity won, and
        # the long-term "Utang bank 23 98,466,244" was mapped as current maturity.
        section = None
        if not grouped_numbers(line):
            start = i
            while start > 0 and i - start < 4 and not grouped_numbers(lines[start - 1]) \
                    and not lines[start - 1].startswith("--- PAGE "):
                start -= 1
            section = _section_of(" ".join(lines[start:i + 1]))
        if section:
            current = section
            if current not in found:
                out.append((current, [], "") if with_text else (current, []))
            found.setdefault(current, [])
        if current and _BANK_ROW.match(line):
            row_lines = [line]
            amounts = grouped_numbers(" ".join(row_lines))
            # Labels like "Utang bank dan / lembaga keuangan / non-bank 24 590.740.287"
            # need the next two text runs before a grouped amount becomes visible. A
            # row that already prints its figures takes nothing from the next line: it
            # used to, and ADMR's "Utang bank 23 98,466,244 98,725,070" absorbed the
            # post-employment benefits row below it.
            for next_line in ([] if amounts else lines[i + 1:i + 4]):
                if next_line.startswith("--- PAGE ") or _BANK_ROW.match(next_line):
                    break
                if _section_of(" ".join(row_lines + [next_line])):
                    break
                row_lines.append(next_line)
                amounts = grouped_numbers(" ".join(row_lines))
                if amounts:
                    break
            if amounts:
                # Every bank/finance-institution row, not just the first. Every
                # printed period on a row is retained; section position is what this
                # guard can prove, while choosing the current column is the extractor's
                # responsibility.
                found.setdefault(current, []).extend(amounts)
                row_text = " ".join(row_lines)
                out.append((current, list(amounts), row_text) if with_text
                           else (current, list(amounts)))
    return out


# A dash right before a row's first figure is the current column printing nil:
#     Utang bank          15     -      42.216.691      Bank loans      (ESSA Q3 2025)
# grouped_numbers skips the dash, so the comparative 42.216.691 read as the row's only
# amount. Only a dash followed directly by the figure counts; "Utang bank - neto 15
# 1.000" is a label hyphen.
_NIL_BEFORE_FIGURE = re.compile(r"(?:^|\s)[-–—](?=\s+\(?\d{1,3}(?:[.,]\d{3})+)")


def _current_column_amount(row_text: str, amounts: list) -> float:
    """The row's current-period figure: 0 when the current column prints a dash."""
    first = _NIL_BEFORE_FIGURE.search(row_text)
    if first and amounts:
        figure = grouped_numbers(row_text[first.end():])
        if figure and figure[0] == amounts[0]:
            return 0.0
    return amounts[0] if amounts else 0.0


def repair_current_maturity_from_long_term(extraction, document_text: str) -> str | None:
    """Move a current-maturity component the model read off the NON-current row.

    TRIN prints two rows labelled "Utang Bank dan Lembaga Keuangan Non-Bank": one under
    "Bagian Liabilitas Jangka Panjang Jatuh Tempo dalam Satu Tahun", one under
    "Dikurangi Bagian Jatuh Tempo dalam Satu Tahun". The headings differ by one word,
    and on Q1 2025 and Q1 2026 the model took the second. The validator proved it --
    the figure is printed only under long-term -- and withheld it, which threw away a
    field whose right answer was printed one row up.

    Repaired only when nothing is ambiguous: the reported figure sits in ONE column of
    the long-term rows and nowhere under current maturity, and the current-maturity
    section holds exactly one distinct row. The figure taken is that row's value in the
    same column, so a comparative read stays comparative and is caught elsewhere.
    """
    value = extraction.utang_bank_bagian_lancar
    if value in (None, 0):
        return None
    rows = _bank_row_amounts(document_text)
    current = {tuple(a) for section, a in rows if section == "current_maturity" and a}
    long_rows = [a for section, a in rows if section == "long_term" and a]
    if any(abs(value - x) < 1 for row in current for x in row):
        return None
    hits = [row for row in long_rows if any(abs(value - x) < 1 for x in row)]
    columns = {i for row in hits for i, x in enumerate(row) if abs(value - x) < 1}
    if len(columns) > 1 and all(all(abs(value - x) < 1 for x in row) for row in hits):
        # The row prints the same figure in every column (TRIN Q1 2026: 10.065.837 and
        # 10.065.837), so the figure alone cannot say which column was read. The model
        # was asked for the current period, and the statement prints it first.
        columns = {0}
    if len(columns) != 1 or len(current) != 1:
        return None
    column = columns.pop()
    row = next(iter(current))
    if column >= len(row):
        return None
    fixed = row[column]
    extraction.utang_bank_bagian_lancar = fixed
    extraction.utang_bank = (extraction.utang_bank_jangka_pendek or 0) + fixed
    extraction._utang_bank_current_maturity_repaired = True
    return (f"utang_bank_bagian_lancar={value:,.0f} is printed only on the non-current "
            f"row; replaced by {fixed:,.0f}, the same column of the current-maturity row")


def repair_misclassified_short_term_debt(extraction, document_text: str) -> str | None:
    """Remove a reported short-term component that is only printed elsewhere.

    Some TRIN periods have no separate short-term lender row: the loan is reported
    once under current maturity and again as its non-current remainder. A model can
    duplicate the former or mistake the latter for short-term debt. When the full
    balance-sheet section map proves there is no short-term loan row, convert that
    misplaced component to zero and rebuild the total from the current-maturity row.
    """
    rows = _bank_rows_by_section(document_text)
    short = extraction.utang_bank_jangka_pendek
    if short in (None, 0) or rows.get("short_term"):
        return None
    if not rows.get("current_maturity") or not rows.get("long_term"):
        return None
    elsewhere = [section for section in ("current_maturity", "long_term")
                 if any(abs(short - value) < 1 for value in rows[section])]
    if not elsewhere:
        return None

    extraction.utang_bank_jangka_pendek = 0
    extraction.utang_bank = extraction.utang_bank_bagian_lancar or 0
    extraction._utang_bank_short_term_repaired = True
    return (f"utang_bank_jangka_pendek={short:,.0f} appears only under "
            f"{', '.join(elsewhere)}; no short-term lender row is present, so set it "
            "to zero and use the printed current-maturity component")


# A filing can print a balance sheet that does not balance. ENRG Q1 2023 prints TOTAL
# ASET 1.201.620.447 and TOTAL LIABILITAS DAN EKUITAS 1.200.439.171 -- 1.181.276 apart,
# while the comparative column balances at 1.194.330.408 -- and all three figures the
# model read were the right ones. The identity is then a fact about the filing, not a
# misread, and the user chose to report the printed figures with a warning.
#
# It is accepted only when the reading is placed in the current column: the printed
# L+E total must equal liabilitas + total_ekuitas and lead its line, and the assets
# figure must never trail another figure. A model that took liabilities and equity
# from the comparative column lands on the comparative L+E total, which never leads.
def filing_prints_unbalanced(e, document_text: str) -> str | None:
    if not document_text or not _present(e.aset, e.liabilitas, e.total_ekuitas):
        return None
    total = e.liabilitas + e.total_ekuitas
    if abs(e.aset - total) <= max(abs(e.aset) * 1e-6, 1):
        return None
    rows = [grouped_numbers(line) for line in document_text.splitlines()]
    leads = any(len(r) >= 2 and abs(r[0] - total) < 0.5 for r in rows)
    printed = any(abs(v - e.aset) < 0.5 for r in rows for v in r)
    trails = any(abs(v - e.aset) < 0.5 for r in rows for v in r[1:])
    if not (leads and printed and not trails):
        return None
    return (f"the filing itself does not balance: it prints total assets "
            f"{e.aset:,.0f} and total liabilities and equity {total:,.0f} "
            f"(gap {e.aset - total:,.0f}); the printed figures are reported")


def validate_against_document(e, document_text: str) -> list:
    """Checks that need the filing text, not just the extracted values.

    Grounding alone cannot catch a value copied from the WRONG row: the number is
    genuinely printed, so it verifies. Only its position distinguishes it. This is
    the known failure mode for bank debt -- three identically labelled rows -- so it
    is checked directly rather than hoped about.
    """
    issues = []
    if not document_text:
        return issues

    rows = _bank_rows_by_section(document_text)

    # Say so when the guard could not run. If an issuer words its headings in a way
    # these patterns miss, the map comes back empty and every check below is skipped
    # -- the guard would stop working while confidence stayed high. A warning makes
    # that visible instead of silent.
    for field in ("utang_bank_jangka_pendek", "utang_bank_bagian_lancar"):
        if len(rows) < 2 and _non_bank_only(document_text, getattr(e, field, None)):
            issues.append(ValidationIssue(
                "non_bank_row", ERROR,
                f"{field}={getattr(e, field):,.0f} is printed only on a non-bank "
                f"liability row (lease, tax, benefits ...), not on a loan",
                (field, "utang_bank")))
    if (e.utang_bank_jangka_pendek is not None or e.utang_bank_bagian_lancar is not None) \
            and len(rows) < 2:
        issues.append(ValidationIssue(
            "section_map_incomplete", WARNING,
            f"could only locate {sorted(rows) or 'no'} bank-debt section(s) in the text; "
            f"the wrong-row check did not run for this filing",
            ("utang_bank", "utang_bank_jangka_pendek", "utang_bank_bagian_lancar")))
        return issues

    # May be absent: an issuer's non-current section can fall outside the selected
    # pages. Absent means "nothing to exclude", not "crash".
    long_term = rows.get("long_term") or []

    # The current portion of long-term bank debt sits under the CURRENT-liabilities
    # heading whatever the row is called, so it is looked for there as well as under
    # an explicit "Bagian lancar" sub-heading.
    checks = [
        ("utang_bank_jangka_pendek", "short_term"),
        ("utang_bank_bagian_lancar", "current_maturity"),
    ]
    # A nil answer where the current-maturity section prints a bank row: TRIN Q4 2024
    # reported 0 for both components against a printed 695.981.931. Withheld, not
    # repaired -- which column is current is not this check's to decide. (Tried once
    # before the section map was fixed and withdrawn: the leaking map put ADMR's
    # long-term loan under current maturity and seven correct nils were withheld.)
    # Only the CURRENT column counts: ESSA Q3 2025 prints "Utang bank 15 - 42.216.691",
    # a nil this period against last year's 42.216.691, and its correct 0 was withheld.
    current_column = [_current_column_amount(text, amounts)
                      for section, amounts, text in _bank_row_amounts(document_text, True)
                      if section == "current_maturity" and amounts]
    if (e.utang_bank_bagian_lancar == 0 and e.utang_bank_jangka_pendek in (None, 0)
            and any(abs(v) >= 1 for v in current_column)):
        issues.append(ValidationIssue(
            "bank_row_ignored", ERROR,
            f"utang_bank_bagian_lancar is 0, but the current-maturity section prints "
            f"{', '.join(f'{v:,.0f}' for v in rows['current_maturity'][:4])}",
            ("utang_bank_bagian_lancar", "utang_bank")))
    # Still a non-bank row after repair (nothing genuine to keep): withhold.
    for field in ("utang_bank_jangka_pendek", "utang_bank_bagian_lancar"):
        if _non_bank_only(document_text, getattr(e, field, None)):
            issues.append(ValidationIssue(
                "non_bank_row", ERROR,
                f"{field}={getattr(e, field):,.0f} is printed only on a non-bank "
                f"liability row (lease, tax, benefits ...), not on a loan",
                (field, "utang_bank")))
    if "current_maturity" not in rows and "short_term" in rows:
        rows["current_maturity"] = rows["short_term"]
    for field, section in checks:
        value = getattr(e, field, None)
        if value is None:
            continue
        if value == 0:
            # An explicit nil says "this row does not exist in this filing" -- CPIN
            # reports short-term bank loans and long-term bank loans with no separate
            # current-portion row at all. Asking which printed row a zero came from is
            # a category error, and answering it wrongly cost two correct extractions:
            # the JPFA fallback below mapped the current-portion check onto the
            # short-term row and then flagged the zero as contradicting it.
            continue
        # A figure that is ALSO printed under this field's own section proves nothing
        # about position. TRIN's loan note repeats the current-maturity amount inside
        # its long-term table, so 178.961.211 sat in both lists and a correct Q2 2025
        # answer was withdrawn as "non-current".
        own = rows.get(section) or []
        if any(abs(value - lt) < 1 for lt in long_term) \
                and not any(abs(value - c) < 1 for c in own):
            issues.append(ValidationIssue(
                "wrong_section", ERROR,
                f"{field} equals a NON-CURRENT bank loan ({value:,.0f}); "
                f"that row must be excluded",
                (field, "utang_bank")))
            continue

        candidates = rows.get(section)
        if not candidates:
            # The heading this field belongs under was not found. Skipping quietly
            # would disable the check for this issuer while confidence stayed high.
            issues.append(ValidationIssue(
                "section_map_incomplete", WARNING,
                f"no '{section}' bank-debt section found; {field} could not be "
                f"position-checked (issuer wording may differ)",
                (field, "utang_bank")))
            continue

        if not any(abs(value - c) < 1 for c in candidates):
            # An ERROR here claims the figure was copied from the WRONG row, and that is
            # only proven when the figure actually sits under another heading. A figure
            # found under no heading at all proves nothing about position: PTBA prints
            # its current portion as "Pinjaman bank 100", which has no thousands
            # separator and so never enters the section map. The model read 100
            # correctly and the old rule withdrew it as wrong_section anyway.
            elsewhere = [section_name for section_name, amounts in rows.items()
                         if section_name != section
                         and any(abs(value - c) < 1 for c in amounts)]
            if elsewhere:
                issues.append(ValidationIssue(
                    "wrong_section", ERROR,
                    f"{field} is {value:,.0f}, which is printed under the "
                    f"{', '.join(elsewhere)} section, not {section}; the rows under "
                    f"{section} read {', '.join(f'{c:,.0f}' for c in candidates)}",
                    (field, "utang_bank")))
            else:
                issues.append(ValidationIssue(
                    "section_map_incomplete", WARNING,
                    f"{field} is {value:,.0f}, found under no bank-debt heading in the "
                    f"text (rows under {section} read "
                    f"{', '.join(f'{c:,.0f}' for c in candidates)}); its position could "
                    f"not be checked",
                    (field, "utang_bank")))
    return issues


# --- the comparative column --------------------------------------------------------
#
# The most common wrong answer left after the fixes of 17 October: a figure read from
# the COMPARATIVE column. It is printed, so grounding confirms it; it sits on the right
# row, so the section checks confirm it; and confidence came out at 1.0 on both TRIN
# Q3 2025 cells (revenue 194.277.418 for a printed 181.607.666, parent profit
# (45.211.769) for 28.483.202). Only the column says it is wrong, and the column is in
# the page header: TRIN prints "Notes 2024 2023" or "... 30 September 2025 dan 2024",
# so the position of the period's year among the header years names the current column.

_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
COMPARATIVE_FIELDS = ("aset", "total_aset_lancar", "kas", "liabilitas", "ekuitas",
                      "total_ekuitas", "kepentingan_non_pengendali", "pendapatan",
                      "laba_bersih", "kas_dari_aktivitas_operasi",
                      "utang_bank_jangka_pendek", "utang_bank_bagian_lancar")
HEADER_SCAN_LINES = 15
MIN_REPAIRABLE = 10_000    # below this, matching digits are too often a coincidence


_YEAR_HEADER = re.compile(
    r"^\s*(?:(?:catatan|notes?|/)\s*)*((?:20\d{2}[\s/]*){2,})$", re.I)


def header_years(page_text: str) -> list:
    """The column years from the page's column-header row, in column order, or [].

    Only a row that is nothing but years ("Notes 2022 2021", "2025 2024") counts. The
    title above it cannot be trusted for ORDER: bilingual titles wrap, and PTBA Q3 2022
    prints "31 DESEMBER 2021 30 SEPTEMBER 2022 AND ..." on one line while its columns
    run 2022, 2021. Reading that line moved two correct PTBA figures and TOTL's correct
    cash into the wrong column on the first replay. A page with no such row returns []
    and nothing is decided from it.
    """
    for line in (page_text or "").split("\n")[:HEADER_SCAN_LINES]:
        match = _YEAR_HEADER.match(line.strip())
        if not match:
            continue
        years = []
        for year in _YEAR.findall(match.group(1)):
            if int(year) not in years:
                years.append(int(year))
        if len(years) >= 2:
            return years
    return []


def repair_comparative_columns(extraction, page_texts: dict, period_year: int) -> list:
    """Move figures read from the comparative column to the current one. Returns messages.

    Repaired only when the evidence is one-sided. EVERY place the figure is printed must
    be a row whose column can be named -- a page with a year-only header row, a row
    printing one amount per header year -- and every one of them must put it at the same
    non-current position and offer the same current-column amount. A figure printed
    anywhere the column cannot be named proves nothing: LSIP Q2 2024's non-controlling
    interest (1.683) sits on a balance sheet without a year row, and the same digits
    turned up in the cash flow's comparative column on another line; repairing on that
    replaced a correct figure. Small figures are left alone for the same reason.
    """
    if not period_year or not page_texts:
        return []
    eligible, anywhere = [], []
    for text in page_texts.values():
        years = header_years(text)
        current = years.index(period_year) if period_year in years else None
        for line in (text or "").split("\n"):
            # "( 230.537.354)" is a negative figure; the space would drop its sign.
            line = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", line))
            amounts = grouped_numbers(line)
            if not amounts:
                continue
            ok = current is not None and len(amounts) == len(years)
            if not ok and current is None and len(amounts) >= 4:
                # A wide row on a page without a year header -- the statement of
                # changes in equity, whose columns are components, not periods -- says
                # nothing about which period a figure belongs to. TRIN Q3 2025's
                # comparative profit appears there too, and that blocked the repair.
                continue
            anywhere.append((amounts, current if ok else None))
    messages = []
    for name in COMPARATIVE_FIELDS:
        value = getattr(extraction, name, None)
        if value in (None, 0) or abs(float(value)) < MIN_REPAIRABLE:
            continue
        target = abs(float(value))
        positions = [(i, amounts, current) for amounts, current in anywhere
                     for i, amount in enumerate(amounts) if abs(abs(amount) - target) < 1]
        if not positions or any(current is None or i == current
                                for i, _, current in positions):
            continue
        fixes = {amounts[current] for _, amounts, current in positions}
        if len(fixes) != 1:
            continue
        fixed = fixes.pop()
        setattr(extraction, name, fixed)
        messages.append(f"{name}={value:,.0f} is printed only in the comparative column; "
                        f"replaced by {fixed:,.0f}, the {period_year} column of the same row")
    return messages


# The revenue convention, chosen by the user for MEDC: a statement that opens with a
# block of revenue lines closed by a printed total reports that total as pendapatan.
# MEDC prints "Pendapatan dari kontrak dengan pelanggan / Pendapatan keuangan / JUMLAH
# PENDAPATAN"; told so in the prompt, the model still took the first line on Q2 and Q3
# 2024 (1.141.062.168 against JUMLAH 1.165.368.521). AKRA's "Total Pendapatan" over
# contract and rental revenue is the same shape, and its labels already use the total.
# The total is taken only when the lines between it and the model's figure add up to
# the difference, so a total that is not this block's cannot be borrowed.
_REVENUE_TOTAL = re.compile(
    r"^\s*(?:jumlah|total)\s*(?:pendapatan|revenues?)\b"
    r"(?!\s*(?:\(|dan\b|and\b|lain|other|usaha\s+lain|komprehensif|comprehensive))", re.I)
_REVENUE_BLOCK_END = re.compile(r"\b(?:beban|biaya|cost|laba|rugi|profit|loss)\b", re.I)
REVENUE_BLOCK_LINES = 8


def repair_revenue_block_total(extraction, page_texts: dict) -> list:
    value = getattr(extraction, "pendapatan", None)
    if value is None:
        return []
    for page in page_texts.values():
        lines = str(page).splitlines()
        for i, line in enumerate(lines):
            figures = grouped_numbers(line)
            if not figures or abs(figures[0] - value) >= 0.5:
                continue
            between = 0.0
            for later in lines[i + 1:i + 1 + REVENUE_BLOCK_LINES]:
                amounts = grouped_numbers(later)
                if _REVENUE_TOTAL.search(later):
                    if amounts and amounts[0] > value and \
                            abs(amounts[0] - value - between) < 1:
                        extraction.pendapatan = amounts[0]
                        return [f"pendapatan={amounts[0]:,.0f}: the revenue block's printed "
                                f"total, not its first line {value:,.0f}"]
                    break
                if _REVENUE_BLOCK_END.search(later):
                    break
                if amounts:
                    between += amounts[0]
    return []


SIGN_FIELDS = ("laba_bersih", "kas_dari_aktivitas_operasi", "kepentingan_non_pengendali")
_PAREN_AMOUNT = re.compile(r"\(\s*\d{1,3}(?:[.,]\d{3})+\s*\)")


def repair_printed_signs(extraction, page_texts: dict, period_year: int) -> list:
    """Give a figure the sign its row prints, when the row leaves no doubt about it.

    TRIN Q1 2025 prints operating cash as "32.613.471 ( 16.186.590)": positive this
    quarter, negative the last. The model answered -32.613.471, and grounding compares
    magnitudes, so nothing caught it. Flipped only when every place the figure is
    printed is this period's column on a year-headed page, all of them print it with
    the other sign, and each such row uses parentheses for a negative -- so a filer
    that writes outflows unsigned under "digunakan untuk" is never touched.
    """
    if not period_year or not page_texts:
        return []
    found = {name: [] for name in SIGN_FIELDS}
    for text in page_texts.values():
        years = header_years(text)
        current = years.index(period_year) if period_year in years else None
        for line in (text or "").split("\n"):
            line = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", line))
            amounts = grouped_numbers(line)
            if not amounts:
                continue
            resolved = current is not None and len(amounts) == len(years)
            for name in SIGN_FIELDS:
                value = getattr(extraction, name, None)
                if value in (None, 0) or abs(float(value)) < MIN_REPAIRABLE:
                    continue
                for i, amount in enumerate(amounts):
                    if abs(abs(amount) - abs(float(value))) < 1:
                        found[name].append((resolved and i == current, amount,
                                            bool(_PAREN_AMOUNT.search(line))))
    messages = []
    for name, hits in found.items():
        value = getattr(extraction, name, None)
        if not hits or not all(at_current and parens for at_current, _, parens in hits):
            continue
        if all((amount > 0) != (float(value) > 0) for _, amount, _ in hits):
            setattr(extraction, name, -float(value))
            messages.append(f"{name}={value:,.0f} is printed with the other sign in the "
                            f"{period_year} column; sign corrected to {-float(value):,.0f}")
    return messages


def repair_components_across_columns(extraction, page_texts: dict, period_year: int) -> list:
    """Two "components" that are one row's two periods are not components.

    RCCC Q4 2022 prints "Kas dan bank 2.143.011.281 447.546.306" -- this year and last.
    The model reported both as kas_components and the sum, 2.590.557.587, is printed
    nowhere. When the components are exactly the amounts of one printed row with
    year-named columns, only the current column is the figure.
    """
    parts = getattr(extraction, "kas_components", None)
    if not parts or len(parts) < 2 or not period_year or not page_texts:
        return []
    want = [abs(float(p)) for p in parts]
    for text in page_texts.values():
        years = header_years(text)
        if period_year not in years or len(years) != len(want):
            continue
        current = years.index(period_year)
        for line in (text or "").split("\n"):
            line = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", line))
            amounts = grouped_numbers(line)
            if len(amounts) == len(want) and all(
                    abs(abs(a) - w) < 1 for a, w in zip(amounts, want)):
                fixed = amounts[current]
                extraction.kas_components = None
                extraction.kas = fixed
                return [f"kas_components {', '.join(f'{p:,.0f}' for p in parts)} are one "
                        f"row's {', '.join(map(str, years))} columns; kas is the "
                        f"{period_year} figure, {fixed:,.0f}"]
    return []


def repair_separated_lead_digits(extraction, page_texts: dict) -> list:
    """Undo a stray digit the model glued onto a figure.

    TRIN Q3 2022 prints "Kas dan Setara Kas 2,4,45,46 1  77.250.439": the "1" stands 35
    points from the figure (pdftext marks it with a double space). The model answered
    177.250.439. When a reported figure is printed nowhere, but the page prints exactly
    "<that digit>  <the rest>" as two separated tokens, the rest is the figure.
    """
    if not page_texts:
        return []
    printed, separated = set(), {}
    for text in page_texts.values():
        for line in (text or "").split("\n"):
            line = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", line))
            printed.update(abs(a) for a in grouped_numbers(line))
            for match in re.finditer(r"(?<![\d.,])(\d)  (\(?\d{1,3}(?:[.,]\d{3})+\)?)", line):
                rest = abs(grouped_numbers(match.group(2))[0])
                glued = float(match.group(1) + str(int(rest)))
                separated.setdefault(glued, set()).add(rest)
    messages = []
    for name in COMPARATIVE_FIELDS:
        value = getattr(extraction, name, None)
        if value in (None, 0) or abs(float(value)) in printed:
            continue
        options = separated.get(abs(float(value)))
        if not options or len(options) != 1:
            continue
        fixed = next(iter(options)) * (1 if float(value) > 0 else -1)
        setattr(extraction, name, fixed)
        messages.append(f"{name}={value:,.0f} glues a separate digit onto the printed "
                        f"{fixed:,.0f}; replaced by the printed figure")
    return messages


# --- a component read off a liability that is not a loan -------------------------------
#
# The two wrong utang_bank answers left in the 14 older issuers were not bank debt at
# all. ADMR Q2 2026 added "Liabilitas sewa - bagian jangka pendek 18 101,091" (a lease)
# to its bank loan; LSIP Q3 2025 reported "Utang pajak 177.362" (taxes payable) as the
# current maturity of a bank loan it does not have. Both figures are printed, so
# grounding passed, and neither sits on a bank row, so the section check had nothing
# to compare. The row a figure is printed on says what it is.

_NON_BANK_ROW = re.compile(
    r"sewa|lease|pajak|tax|imbalan|employee|benefit|royalti|royalt|usaha\b|trade\s+pay|"
    r"provisi|provision|pelanggan|customer|kontrak|contract|akrual|accru", re.I)


def _row_labels_for(document_text: str, value: float) -> list:
    """The label context of every line printing `value`: the line and the figure-free
    lines just above it, because a wrapped label puts its amount on the last line."""
    lines = document_text.splitlines()
    out = []
    for i, line in enumerate(lines):
        if any(abs(abs(a) - abs(value)) < 1 for a in grouped_numbers(line)):
            start = i
            while start > 0 and i - start < 2 and not grouped_numbers(lines[start - 1]) \
                    and not lines[start - 1].startswith("--- PAGE "):
                start -= 1
            out.append(" ".join(lines[start:i + 1]))
    return out


def _non_bank_only(document_text: str, value) -> bool:
    if value in (None, 0):
        return False
    labels = _row_labels_for(document_text, float(value))
    return bool(labels) and all(_NON_BANK_ROW.search(l) and not re.search(
        r"\bbank\b|lembaga\s+keuangan|financial\s+institution|pinjaman", l, re.I)
        for l in labels)


def repair_non_bank_component(extraction, document_text: str) -> list:
    """Drop a bank-debt component printed only on a non-bank liability row, when the
    other component is a genuine bank figure. Returns messages."""
    short, current = extraction.utang_bank_jangka_pendek, extraction.utang_bank_bagian_lancar
    messages = []
    for name, value, other in (("utang_bank_bagian_lancar", current, short),
                               ("utang_bank_jangka_pendek", short, current)):
        if not _non_bank_only(document_text, value) or other in (None, 0):
            continue
        if not any(re.search(r"\bbank\b|lembaga\s+keuangan|pinjaman", l, re.I)
                   for l in _row_labels_for(document_text, float(other))):
            continue
        setattr(extraction, name, 0)
        extraction.utang_bank = (extraction.utang_bank_jangka_pendek or 0) + \
            (extraction.utang_bank_bagian_lancar or 0)
        messages.append(f"{name}={value:,.0f} is printed only on a non-bank liability "
                        f"row (lease, tax, benefits ...); removed from utang_bank")
    return messages



# --- a share count read from the capital column ----------------------------------------
#
# A shareholder table prints, per row, the number of shares, the percentage of ownership
# and the paid-up amount in Rupiah: "Total 6.301.930.902 100% 315.096.545.100". PURA Q2
# 2025 read from its image answered 315.096.545.100 -- 6.301.930.902 shares at Rp 50 --
# and TRIN Q1/Q3 2022 answered their capital columns too. Both are printed, so grounding
# passed. The percentage sits between the two columns and says which one is the count.

_COUNT_PCT_AMOUNT = re.compile(
    r"(\d{1,3}(?:[.,]\d{3})+)\s+\d{1,3}(?:[.,]\d{1,2})?\s*%\s+(\d{1,3}(?:[.,]\d{3})+)")
SHARE_COUNT_FIELDS = ("total_share", "saham_ditempatkan", "saham_beredar", "saham_treasuri")


def repair_share_amount_column(extraction, page_texts: dict) -> list:
    """Replace a share figure taken from the paid-up amount with that row's count."""
    if not page_texts:
        return []
    pairs = {}                                    # amount -> {counts}
    for text in page_texts.values():
        for body in (str(text or ""), getattr(text, "alternate", "") or ""):
            for line in body.split("\n"):
                line = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", line))
                for match in _COUNT_PCT_AMOUNT.finditer(line):
                    count = grouped_numbers(match.group(1))
                    amount = grouped_numbers(match.group(2))
                    if count and amount and abs(amount[0]) > abs(count[0]):
                        pairs.setdefault(abs(amount[0]), set()).add(abs(count[0]))
    messages = []
    for name in SHARE_COUNT_FIELDS:
        value = getattr(extraction, name, None)
        if value in (None, 0):
            continue
        counts = pairs.get(abs(float(value)))
        if not counts or len(counts) != 1:
            continue
        fixed = next(iter(counts))
        setattr(extraction, name, fixed)
        messages.append(f"{name}={value:,.0f} is the paid-up AMOUNT column of the "
                        f"shareholder table; the share count on that row is {fixed:,.0f}")
    parts = getattr(extraction, "total_share_components", None)
    if parts:
        fixed_parts = []
        for part in parts:
            counts = pairs.get(abs(float(part)))
            fixed_parts.append(next(iter(counts)) if counts and len(counts) == 1 else part)
        if fixed_parts != list(parts):
            extraction.total_share_components = fixed_parts
            messages.append("total_share_components taken from the amount column; "
                            "replaced by the share counts on the same rows")
    return messages


def repair_share_count_scale(extraction, page_texts: dict) -> list:
    """Undo a share count multiplied by the page's "(dalam ribuan Rupiah)" scale.

    The header scale is for Rupiah; a share count is taken as printed (user's rule,
    CHECKPOINT). TRIN Q4 2025 prints "Sub-total 4.424.040 97,20% 442.404.118" under
    "(Disajikan dalam Ribuan Rupiah ...)", and on 2026-11-10 gemini-3.5-flash-lite
    answered 4.424.040.000 -- on that run only; four later samples of the same prompt
    answered 4.424.040. Grounding then withheld all three share fields. A count that is
    not printed, while exactly it / 1.000 or / 1.000.000 IS the count on one row of
    the shareholder table, is put back to the printed count.
    """
    if not page_texts:
        return []
    counts, printed = set(), set()
    for text in page_texts.values():
        for body in (str(text or ""), getattr(text, "alternate", "") or ""):
            for line in body.split("\n"):
                line = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", line))
                printed.update(abs(v) for v in grouped_numbers(line))
                for match in _COUNT_PCT_AMOUNT.finditer(line):
                    count = grouped_numbers(match.group(1))
                    if count:
                        counts.add(abs(count[0]))
    messages = []
    for name in SHARE_COUNT_FIELDS:
        value = getattr(extraction, name, None)
        if value in (None, 0) or abs(float(value)) in printed:
            continue
        for scale in (1_000, 1_000_000):
            scaled = abs(float(value)) / scale
            if scaled.is_integer() and scaled in counts:
                setattr(extraction, name, scaled)
                messages.append(f"{name}={value:,.0f} is the printed share count "
                                f"{scaled:,.0f} multiplied by {scale:,}; counts are "
                                f"taken as printed")
                break
    return messages
