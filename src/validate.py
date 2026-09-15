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
_RE_BAGIAN = re.compile(r"bagian\s+lancar|bagian\s+jangka\s+pendek|jatuh\s+tempo", re.I)
_RE_NETTING = re.compile(r"dikurangi|setelah", re.I)
_RE_PANJANG = re.compile(r"(liabilitas|kewajiban)\s+jangka\s+panjang", re.I)
_RE_PENDEK = re.compile(r"(liabilitas|kewajiban)\s+jangka\s+pendek", re.I)


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
    r"^\s*(?:utang|hutang|pinjaman|liabilitas|kewajiban)\s+bank\b", re.I)


def _bank_rows_by_section(document_text: str) -> dict:
    """Map each section to the 'Utang bank' amount printed under it.

    Reads the page the way a person does -- downwards from the nearest heading --
    which is the one piece of context a flattened text layer destroys.
    """
    found, current = {}, None
    for line in document_text.split("\n"):
        section = _section_of(line)
        if section:
            current = section
        if current and _BANK_ROW.match(line):
            # Every bank row under the heading, not just the first. Issuers split
            # bank debt across several rows, and JPFA files the current portion of
            # its long-term loans under the CURRENT-liabilities heading while still
            # labelling the row "Utang bank jangka panjang" -- keeping only the
            # first row there would lose it.
            #
            # Every COLUMN of the row too. The rule this feeds is named wrong_section
            # and that is exactly what it can prove: that a figure was taken from a
            # row filed under a different heading. Which of a row's two periods a
            # figure came from is a different question, and one a flattened text
            # layer cannot answer reliably -- claiming to answer it here would turn a
            # column mis-read into an ERROR against whichever value happened to be
            # printed leftmost.
            amounts = grouped_numbers(line)
            if amounts:
                found.setdefault(current, []).extend(amounts)
    return found


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
        if any(abs(value - lt) < 1 for lt in long_term):
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
