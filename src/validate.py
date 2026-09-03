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
_SECTIONS = [
    ("short_term", re.compile(r"Liabilitas Jangka Pendek", re.I)),
    ("current_maturity", re.compile(r"Bagian lancar atas", re.I)),
    ("long_term", re.compile(r"Liabilitas jangka panjang, setelah", re.I)),
]
_BANK_ROW = re.compile(r"^\s*Utang bank[^\d]*?([\d.]{6,})", re.I)


def _bank_rows_by_section(document_text: str) -> dict:
    """Map each section to the 'Utang bank' amount printed under it.

    Reads the page the way a person does -- downwards from the nearest heading --
    which is the one piece of context a flattened text layer destroys.
    """
    found, current = {}, None
    for line in document_text.split("\n"):
        for name, pattern in _SECTIONS:
            if pattern.search(line):
                current = name
                break
        match = _BANK_ROW.match(line)
        if match and current and current not in found:
            try:
                found[current] = float(match.group(1).replace(".", ""))
            except ValueError:
                pass
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
    long_term = rows.get("long_term")

    checks = [
        ("utang_bank_jangka_pendek", "short_term"),
        ("utang_bank_bagian_lancar", "current_maturity"),
    ]
    for field, section in checks:
        value = getattr(e, field, None)
        if value is None:
            continue
        if long_term is not None and abs(value - long_term) < 1:
            issues.append(ValidationIssue(
                "wrong_section", ERROR,
                f"{field} equals the NON-CURRENT bank loan ({long_term:,.0f}); "
                f"that row must be excluded",
                (field, "utang_bank")))
            continue
        expected = rows.get(section)
        if expected is not None and abs(value - expected) > 1:
            issues.append(ValidationIssue(
                "wrong_section", ERROR,
                f"{field} is {value:,.0f} but the row under its section reads "
                f"{expected:,.0f}",
                (field, "utang_bank")))
    return issues
