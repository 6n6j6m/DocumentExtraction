"""
Core extraction pipeline for financial statements.

Uses Gemini REST API (via requests) instead of google-generativeai package
to avoid dependency issues. Works with GEMINI_API_KEY environment variable.
"""

import os
import json
import time
import base64
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import io
import re
import requests

# Load environment variables from .env
load_dotenv(Path(__file__).parent.parent / ".env")

from pdf2image import convert_from_path

from schema import FinancialStatementExtraction
from prompts import SYSTEM_PROMPT, EXTRACTION_PROMPT
from page_select import select_statement_pages, classify_pages
from normalize import to_idr
from llm import get_provider_chain, parse_json, LLMError, LLMUnavailable
from validate import validate, validate_against_document
from confidence import score_extraction, apply_abstention


class ExtractorConfig:
    """Pipeline settings that are not provider-specific.

    Deliberately does NOT require GEMINI_API_KEY. This object is built at the top of
    every extraction, including a fully local Ollama run, so demanding a hosted
    provider's key here made `LLM_PROVIDER=ollama` fail before a single page was
    read. Each provider validates its own credentials in `llm.py` and raises
    LLMUnavailable, which the caller already knows how to fall back from.
    """
    def __init__(self):
        self.max_pdf_pages = int(os.getenv("MAX_PDF_PAGES", "20"))


def render_pdf_page_to_image(pdf_path: str, page_num: int, dpi: int = 150) -> bytes:
    """Render PDF page to PNG bytes using pdf2image.
    
    Args:
        pdf_path: Path to PDF
        page_num: 0-indexed page number
        
    Returns:
        PNG bytes
    """
    images = convert_from_path(pdf_path, first_page=page_num+1, last_page=page_num+1, dpi=dpi)
    if not images:
        raise ValueError(f"Failed to render page {page_num}")
    
    img = images[0]
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()






from contextlib import nullcontext as _nullcontext

MIN_TEXT_CHARS = 200   # below this a page is treated as having no usable text layer


def read_page_texts(pdf_path: str, page_numbers: list) -> dict:
    """Return {page_number: text} for the selected pages.

    Pages whose text layer is unreadable -- a scan, or subset fonts with no
    ToUnicode CMap -- are OCR'd, so grounding and the section checks keep working on
    a filing whose characters are glyph ids. See src/pdftext.py.
    """
    from pdftext import page_texts

    return page_texts(pdf_path, page_numbers)


HEADER_LINES = 8          # title, scope, currency and scale live at the top of a page
GARBLED_MAX_MEDIAN_LEN = 15   # rotated pages extract as many tiny fragments
_GROUPED_FIGURE = re.compile(r"\d{1,3}(?:[.,]\d{3})+")


# What the check is actually looking for, stated positively. A rotated page carries
# no readable figures; that is the property, and short lines were only ever a proxy
# for it. The proxy alone throws away a page OCR returns in column order -- label
# column first, then the amounts, one per line -- which is precisely the page an
# unreadable text layer had to be OCR'd for. GTRA Q1 2026's balance sheet was
# discarded that way after being read correctly, and every figure on it then failed
# grounding for want of anywhere to check it against.
GARBLED_MIN_FIGURES = 5


def _is_garbled(lines: list) -> bool:
    """True for pages whose text layer came out as fragments (rotated pages).

    A rotated page extracts as hundreds of 2-3 character pieces. It is the single
    largest page in the set, so it is worth its own check rather than letting it eat
    a third of the context window -- but only when it really carries nothing.
    """
    if len(lines) < 60:
        return False
    figures = sum(1 for line in lines if _GROUPED_FIGURE.search(line))
    if figures >= GARBLED_MIN_FIGURES:
        return False
    lengths = sorted(len(l) for l in lines)
    return lengths[len(lengths) // 2] < GARBLED_MAX_MEDIAN_LEN


def condense_page_text(text: str) -> str:
    """Drop lines that cannot carry a figure, keeping enough context to read one.

    Statement labels wrap ("Ekuitas yang Dapat Diatribusikan" / "kepada Pemilik
    Entitas Induk") and the amount often sits on the line after the label, so a
    kept line brings its immediate neighbours with it. The page header is always
    kept: currency and reporting scale are stated there, never on a numbered row.
    """
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines or _is_garbled(lines):
        return ""

    # Either grouping convention, or four bare digits. Without the comma branch, a
    # filing that prints "80,322,232" has no four consecutive digits anywhere and
    # condensation throws away every line that carries a figure.
    has_number = re.compile(r"\d{1,3}(?:[.,]\d{3})+|\d{4}")
    keep = set(range(min(HEADER_LINES, len(lines))))
    for i, line in enumerate(lines):
        if has_number.search(line):
            keep.update((i - 1, i, i + 1))

    return "\n".join(lines[i] for i in sorted(keep) if 0 <= i < len(lines))


def build_document_text(page_texts: dict) -> str:
    """Concatenate pages with markers so the model can tell them apart.

    All the selected pages go in ONE request. With images that was too expensive,
    so pages were sent one at a time and the results merged; with text it costs
    little, and the model seeing the balance sheet, income statement and cash flow
    together is what lets it fill every field in a single pass.
    """
    condense = os.getenv("CONDENSE_TEXT", "true").lower() in ("1", "true", "yes")
    blocks = []
    for n in sorted(page_texts):
        text = page_texts[n]
        if len(text.strip()) < MIN_TEXT_CHARS:
            continue
        if condense:
            text = condense_page_text(text)
            if not text:
                continue
        blocks.append(f"--- PAGE {n + 1} ---\n{text}")
    return "\n\n".join(blocks)


# Grouping convention varies by issuer (694.671.337 vs 80,322,232), so parsing is
# decided per value in one place -- see src/numfmt.py.
from numfmt import parse_grouped_number as _parse_indonesian_number


def _coerce_numbers(data: dict) -> dict:
    """Turn numeric strings into floats; leave anything unparseable as None."""
    list_fields = ("total_share_components", "kas_components")
    numeric = [f for f in FIELDS if f not in
               ("period_end_date", "currency", "reporting_scale", "statement_scope")
               + list_fields]
    for list_field in list_fields:
        components = data.get(list_field)
        if isinstance(components, list):
            parsed = [_parse_indonesian_number(c) if isinstance(c, str) else c
                      for c in components]
            parsed = [float(c) for c in parsed if isinstance(c, (int, float))]
            data[list_field] = parsed or None
        elif components is not None:
            data[list_field] = None
    for key in numeric:
        value = data.get(key)
        if value in (None, ""):
            data[key] = None
            continue
        if isinstance(value, str):
            # The model was told to strip separators, but a filing's own formatting
            # leaks through often enough to be worth handling properly.
            data[key] = _parse_indonesian_number(value)
            continue
        try:
            data[key] = float(value)
        except (TypeError, ValueError):
            data[key] = None
    return data


# Which fields each statement can actually answer. A small model asked for 18
# fields across 7 pages answers the first few and quietly drops the rest; asked
# for 4 fields across 2 pages it answers all four. Splitting costs extra calls,
# which is the right trade when the local model is free and the hosted one is
# billed per request anyway.
GROUP_FIELDS = {
    "balance_sheet": ["aset", "total_aset_lancar", "kas", "kas_components", "liabilitas",
                      "utang_bank_jangka_pendek", "utang_bank_bagian_lancar",
                      "total_ekuitas", "kepentingan_non_pengendali"],
    "income":        ["pendapatan", "laba_bersih"],
    "cash_flow":     ["kas_dari_aktivitas_operasi"],
    # The statement of changes in equity answered only total_share, and the share count
    # is no longer read from any statement. Its pages stay selected; no call is made.
    "equity":        [],
    # The shareholder table located by page_select.find_shareholder_table_pages -- the
    # only source of the share counts.
    "share_capital": ["total_share", "total_share_components", "saham_beredar", "saham_treasuri"],
}
SHARE_FIELDS = ("total_share", "total_share_components", "saham_beredar", "saham_treasuri")
ALWAYS = ["period_end_date", "currency", "reporting_scale", "statement_scope"]


def group_pages(page_texts: dict, share_pages: list = None) -> dict:
    """Group the selected pages by the statement each one carries.

    A share-capital note is pulled out of whatever group it fell into and asked its
    own narrow question. It is not a statement, so letting it inherit the group of
    the page before it would put an unrelated note in front of the model alongside
    the balance sheet -- the opposite of what splitting by statement is for.
    """
    groups = classify_pages(page_texts)
    for page in share_pages or []:
        for name in list(groups):
            if page in groups[name]:
                groups[name] = [p for p in groups[name] if p != page]
                if not groups[name]:
                    del groups[name]
    if share_pages:
        groups["share_capital"] = sorted(share_pages)
    return groups


def _focus_prompt(fields: list) -> str:
    """Restrict one request to a named subset of fields."""
    wanted = ", ".join(fields + ALWAYS)
    return (f"{EXTRACTION_PROMPT}\n\n"
            f"=== THIS REQUEST ONLY ===\n"
            f"These pages contain ONLY part of the statements. Extract EXACTLY these "
            f"fields and nothing else: {wanted}.\n"
            f"Every one of them is present on these pages -- find all of them before "
            f"answering. Omit all other fields from your JSON.")


def derive_fields(extraction) -> list:
    """Compute the fields the model was deliberately not asked to compute.

    Returns a list of warnings. Deriving here rather than in the prompt means the
    arithmetic is exact, and a wrong answer points at ONE misread row instead of an
    opaque total. Where the model volunteered the combined value anyway, it is
    cross-checked and the computed value wins.
    """
    warnings = []

    short = extraction.utang_bank_jangka_pendek
    current = extraction.utang_bank_bagian_lancar
    if short is not None or current is not None:
        computed = (short or 0) + (current or 0)
        if short is None or current is None:
            warnings.append(
                f"utang_bank from one component only "
                f"(jangka_pendek={short}, bagian_lancar={current})")
        if extraction.utang_bank is not None and abs(extraction.utang_bank - computed) > 1:
            warnings.append(
                f"model said utang_bank={extraction.utang_bank:,.0f}, "
                f"components sum to {computed:,.0f} - using components")
        extraction.utang_bank = computed

    total = extraction.total_ekuitas
    nci = extraction.kepentingan_non_pengendali
    if total is not None:
        # Attributable to the parent = total less the non-controlling interest.
        # NCI is negative in these filings, so the parent share is LARGER than the
        # total -- the opposite of the usual intuition, and a common manual error.
        computed = total - (nci or 0)
        if nci is None:
            warnings.append("kepentingan_non_pengendali missing; ekuitas assumes NCI = 0")
        if extraction.ekuitas is not None and abs(extraction.ekuitas - computed) > 1:
            warnings.append(
                f"model said ekuitas={extraction.ekuitas:,.0f}, "
                f"computed {computed:,.0f} - using computed")
        extraction.ekuitas = computed

    # LSIP prints no cash total: "Kas dan setara kas" is a heading over two amounts, one
    # for related parties and one for third parties. Asked for kas, the model added them
    # in its head and missed by 2 to 128 (thousand rupiah) on six filings out of
    # eighteen -- a sum printed nowhere, so grounding withdrew every one. The sub-lines
    # are printed and checkable; the arithmetic belongs here.
    cash_parts = extraction.kas_components
    if cash_parts:
        computed = sum(cash_parts)
        if extraction.kas is not None and abs(extraction.kas - computed) > 1:
            warnings.append(
                f"model said kas={extraction.kas:,.0f}, {len(cash_parts)} cash "
                f"sub-line(s) sum to {computed:,.0f} - using sub-lines")
        extraction.kas = computed

    parts = extraction.total_share_components
    if parts:
        computed = sum(parts)
        if extraction.total_share is not None and abs(extraction.total_share - computed) > 1:
            # One class reported as if it were the whole, or the model added a
            # figure that is not a share class at all. The printed rows win.
            warnings.append(
                f"model said total_share={extraction.total_share:,.0f}, "
                f"{len(parts)} share class(es) sum to {computed:,.0f} - using classes")
        extraction.total_share = computed

    # total_share is the count OUTSTANDING. The model reports the issued count it can
    # read (total_share, or per-class components summed above) plus whatever the filing
    # prints about the rest: an outstanding total (JPFA, PTBA) or a treasury count (EMAS).
    # The subtraction happens here, once, and the issued figure is kept beside it.
    issued = extraction.total_share
    extraction.saham_ditempatkan = issued
    beredar, treasuri = extraction.saham_beredar, extraction.saham_treasuri
    if beredar is not None and issued is not None and beredar > issued + 1:
        warnings.append(f"saham_beredar {beredar:,.0f} is more than the {issued:,.0f} "
                        f"shares issued - ignored")
        extraction.saham_beredar = beredar = None
    if treasuri is not None and issued is not None and treasuri >= issued:
        warnings.append(f"saham_treasuri {treasuri:,.0f} is not less than the "
                        f"{issued:,.0f} shares issued - ignored")
        extraction.saham_treasuri = treasuri = None
    if beredar is not None:
        if issued is not None and treasuri is not None and abs(issued - treasuri - beredar) > 1:
            warnings.append(
                f"issued {issued:,.0f} less treasury {treasuri:,.0f} is "
                f"{issued - treasuri:,.0f}, but {beredar:,.0f} is printed as outstanding - "
                f"using the printed figure")
        extraction.total_share = beredar
    elif treasuri and issued is not None:
        extraction.total_share = issued - treasuri

    # The identity holds on TOTAL equity, so it can only be checked when the printed
    # total is present. Falling back to the parent-attributable figure would fail by
    # exactly the non-controlling interest and report a balanced sheet as broken.
    if extraction.aset and extraction.liabilitas and extraction.total_ekuitas:
        gap = extraction.aset - (extraction.liabilitas + extraction.total_ekuitas)
        if abs(gap) > max(abs(extraction.aset) * 0.001, 1):
            warnings.append(
                f"balance sheet does not balance: aset - (liabilitas + total ekuitas) "
                f"= {gap:,.0f}")

    return warnings


def extract_from_text(document_text: str, provider,
                      prompt: Optional[str] = None,
                      usage=None) -> Optional[FinancialStatementExtraction]:
    """One call for one slice of the filing; structured JSON back."""
    user = f"{prompt or EXTRACTION_PROMPT}\n\nDOCUMENT:\n{document_text}"
    raw = provider.complete(SYSTEM_PROMPT, user, usage=usage)
    data = parse_json(raw)
    if "evidence" in data:
        data.pop("evidence")
    return FinancialStatementExtraction.from_dict(_coerce_numbers(data))


FIELDS = [
    "period_end_date", "aset", "total_aset_lancar", "kas",
    "liabilitas", "utang_bank", "ekuitas", "pendapatan",
    "laba_bersih", "kas_dari_aktivitas_operasi", "total_share",
    # Components belong here too: merge_extractions and _coerce_numbers both iterate
    # FIELDS, so anything missing is silently dropped between the per-statement
    # calls -- leaving derived utang_bank and ekuitas with nothing to work from.
    "utang_bank_jangka_pendek", "utang_bank_bagian_lancar",
    "total_ekuitas", "kepentingan_non_pengendali", "total_share_components",
    "kas_components", "saham_beredar", "saham_treasuri",
    "currency", "reporting_scale", "statement_scope",
]


def _filled(extraction) -> int:
    """Count non-empty fields."""
    return sum(1 for f in FIELDS if getattr(extraction, f, None) not in (None, ""))


def merge_extractions(base, new):
    """Fill empty fields of `base` from `new`. First non-null value wins.

    Statements span multiple pages (assets on one page, liabilities/equity on the
    next, income statement and cash flow later), so a single page never carries
    every field. Earlier pages win on conflict because the primary statements come
    before the notes.
    """
    for f in FIELDS:
        if getattr(base, f, None) in (None, "") and getattr(new, f, None) not in (None, ""):
            setattr(base, f, getattr(new, f))
    return base


# The date guard for treasury shares. A shareholder note prints two dates side by side,
# and the model does not always take the current one: shown ITMG's Q2 2022 note, it took
# 33,369,100 treasury shares from the 31 December 2021 column -- all of them were sold in
# March and April 2022 -- and reported 1,096,555,900 outstanding instead of 1,129,925,000.
# Both figures are printed, so grounding passed a wrong number.
#
# The balance sheet settles which date is which, because its current column comes first
# and a nil there is printed as a dash:
#     ITMG Q2 2022   Saham treasuri 20  -  (19,211)          -> none at the current date
#     EMAS Q1 2026   Saham treasuri 2y  -  ( 13,741,835 )    -> none (cancelled Feb 2026)
#     EMAS Q4 2025   Saham treasuri 2z, 21  ( 13,741,835 )  -
#     PTBA Q2 2025   Saham treasuri 24  (12,521)  (12,521)
#     JPFA          "Saham treasuri - Treasury shares -" / "98.905.300 saham (147.851) ..."
_TREASURY_LABEL = re.compile(
    r"saham\s+treasuri|treasury\s+(?:shares|stock)|saham\s+(?:yang\s+)?diperoleh\s+kembali", re.I)
_PAREN_AMOUNT = re.compile(r"\(\s*\d[\d.,]*\s*\)")
# An unbracketed amount that is not a share count ("98.905.300 saham" is a count).
_PLAIN_AMOUNT = re.compile(
    r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?![.,]?\d)(?!\s*(?:saham|shares|lembar))", re.I)
_NIL_MARK = re.compile(r"(?<![\w(])[-\u2013\u2014](?![\w)])")
# A dash between the label and a share count is punctuation, not a nil: JPFA from Q4 2024
# prints "Saham treasuri - 98.905.300 saham (147.851) 2,24 (147.851)". Read as a nil, it
# discarded a correct 11.627.669.901 outstanding on three filings.
_LABEL_DASH = re.compile(r"^\s*[-\u2013\u2014]\s*(?=\d[\d.,]*\s*(?:saham|shares|lembar)\b)", re.I)


def treasury_current_on_balance_sheet(text: str):
    """True if the balance sheet shows treasury shares at the current date, False if its
    current column is nil, None if it prints no treasury line at all."""
    lines = (text or "").split("\n")
    for i, line in enumerate(lines):
        label = _TREASURY_LABEL.search(line)
        if not label:
            continue
        segment = _LABEL_DASH.sub("", line[label.end():], count=1)
        if not (_PAREN_AMOUNT.search(segment) or _PLAIN_AMOUNT.search(segment)):
            # A label with no amount on its line is a heading; the figures are below it.
            segment = lines[i + 1] if i + 1 < len(lines) else ""
        tokens = sorted([(m.start(), "amount") for m in _PAREN_AMOUNT.finditer(segment)]
                        + [(m.start(), "amount") for m in _PLAIN_AMOUNT.finditer(segment)]
                        + [(m.start(), "nil") for m in _NIL_MARK.finditer(segment)])
        if tokens:
            return tokens[0][1] == "amount"
    return None


def _apply_treasury_date_guard(merged, page_texts, groups) -> None:
    """Drop outstanding / treasury counts that cannot belong to the current date."""
    pages = (groups or {}).get("balance_sheet") or []
    if not pages or not page_texts:
        return
    text = "\n".join(page_texts.get(n, "") for n in pages)
    if treasury_current_on_balance_sheet(text) is False and (
            merged.saham_treasuri or merged.saham_beredar is not None):
        print("    \u26a0 balance sheet shows no treasury shares at the current date; "
              f"discarding treasury {merged.saham_treasuri} / outstanding "
              f"{merged.saham_beredar} read from another date")
        merged.saham_treasuri = None
        merged.saham_beredar = None


def table_totals(text: str) -> list:
    """Share counts on 100%-of-ownership rows, in printed order."""
    from page_select import total_row_count
    totals = []
    for line in (text or "").split("\n"):
        count = total_row_count(line)
        if count:
            totals.append(float(re.sub(r"[.,]", "", count)))
    return totals


def _apply_current_table_guard(merged, page_texts, groups) -> None:
    """Replace a table total taken from the comparative date with the current one.

    The note prints the current date's table first. A total that differs from the first
    100% row but equals a later one was read from the comparative table, so the first
    row -- printed, and current by position -- wins. Anything else is left to grounding.
    """
    pages = (groups or {}).get("share_capital") or []
    if not pages or not page_texts:
        return
    totals = table_totals("\n".join(page_texts.get(n, "") for n in pages))
    components = merged.total_share_components
    issued = sum(components) if components else merged.total_share
    if issued is None or not totals or abs(issued - totals[0]) <= 1:
        return
    if any(abs(issued - later) <= 1 for later in totals[1:]):
        print(f"    ⚠ share count {issued:,.0f} is the comparative table's total; "
              f"using the current table's {totals[0]:,.0f}")
        merged.total_share = totals[0]
        merged.total_share_components = None


def merge_group(merged, part, group: str):
    """Merge one statement group's answer; share counts come only from the shareholder table.

    total_share is the count outstanding, and only the shareholder table says what is
    outstanding. A count a statement group volunteers anyway -- the issued count on the
    share-capital line, or worse, DSNG's 10.599.850.000, issued capital divided by par
    value and printed nowhere -- is dropped rather than merged, so it can neither beat
    the table's answer nor stand in for a missing one.

    Everything else keeps the first-non-null rule.
    """
    if part is None:
        return merged
    if group != "share_capital":
        for name in SHARE_FIELDS:
            setattr(part, name, None)
    return merge_extractions(merged, part)


def assess(extraction, page_texts: dict) -> dict:
    """Validate, score every field, and blank the ones not worth asserting.

    Grounding is checked against the PDF's text layer even when the model was shown
    images. That makes it an independent channel: the extractor read pixels, the
    verifier reads characters, so agreement is real evidence rather than the same
    read twice.

    Returns {field: {confidence, grounded, abstained, reasons}} and mutates
    `extraction` in place, removing abstained values.
    """
    document_text = build_document_text(page_texts) if page_texts else ""
    issues = validate(extraction) + validate_against_document(extraction, document_text)
    for issue in issues:
        print(f"    \u26a0 [{issue.severity}] {issue.rule}: {issue.message}")
    # Kept on the extraction rather than only printed: the API has to report which
    # rules fired, and re-running validation to find out would risk answering a
    # different question than the one the abstention decision was made on.
    extraction.issues = [{"rule": i.rule, "severity": i.severity,
                          "message": i.message, "fields": list(i.fields)}
                         for i in issues]

    scores = score_extraction(extraction, document_text, issues)
    abstained = apply_abstention(extraction, scores)
    if abstained:
        print(f"    abstained on {len(abstained)}: {', '.join(abstained)}")

    ungrounded = [n for n, s in scores.items() if s.grounded is False]
    if ungrounded:
        print(f"    not found in document text: {', '.join(ungrounded)}")

    return {n: {"confidence": s.confidence, "grounded": s.grounded,
                "abstained": s.abstained, "reasons": s.reasons}
            for n, s in scores.items()}


def extract_from_pdf(pdf_path: str, page_numbers: Optional[list] = None,
                     usage=None) -> Optional[FinancialStatementExtraction]:
    """Extract statement fields, trying each provider on ITS OWN input mode.

    Gemini defaults to images (a VLM reads layout well and the cost is not ours to
    bear); Ollama defaults to text (a local text model is far cheaper than a local
    vision model of the same quality). Either can be overridden with
    GEMINI_INPUT_MODE / OLLAMA_INPUT_MODE.

    A provider on text mode needs characters: the PDF's own text layer if it has
    one, OCR only if it does not.
    """
    config = ExtractorConfig()

    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    # Page selection reads (and may OCR) the whole document, so it is timed apart from
    # the model calls: on a filing with a broken text layer it dominates the run, and a
    # single total would blame the model for it.
    from usage import Usage
    usage = Usage() if usage is None else usage

    share_pages = []
    if page_numbers is None:
        print(f"\n\U0001F4C4 Selecting pages from {Path(pdf_path).name}...")
        with usage.stage("select_pages"):
            selection = select_statement_pages(pdf_path, max_pages=config.max_pdf_pages)
        page_numbers = selection.pages
        share_pages = selection.share_capital_pages
        print(f"  Method: {selection.method}")
        print(f"  Pages: {[p+1 for p in page_numbers]} (1-indexed)")
        if share_pages:
            print(f"  Shareholder table: {[p+1 for p in share_pages]} (the source of total_share)")
        else:
            print("  ⚠ no shareholder table found; total_share will be empty")
        print(f"  Reduction: {len(page_numbers)}/{selection.total_pages} pages "
              f"({100*(1-len(page_numbers)/selection.total_pages):.1f}% reduction)")

    pages_1indexed = [p + 1 for p in page_numbers]

    chain = get_provider_chain()
    page_texts = None      # read lazily, only if some provider wants text
    split = os.getenv("SPLIT_BY_STATEMENT", "true").lower() in ("1", "true", "yes")

    # Why each provider gave up, so the caller is told the difference between "the
    # filing defeated us" and "nobody was answering the phone". Collapsing both into
    # one generic failure told an API caller to fix their request when what they
    # actually needed to do was wait.
    unavailable = []

    for index, provider in enumerate(chain):
        mode = getattr(provider, "input_mode", "text")
        if index:
            # Said out loud: the row this document becomes will carry a different model
            # from its neighbours, and whoever reads the CSV should be able to see why.
            print(f"\n\u21aa {chain[index - 1].name} unavailable; "
                  f"handing this document to {provider.name}")
        print(f"\n\U0001F50D {provider.name} [{mode}]...")

        if mode == "image":
            if page_texts is None:
                with usage.stage("read_text"):
                    page_texts = read_page_texts(pdf_path, page_numbers)
            try:
                with usage.stage("extract"):
                    result = _extract_from_images(pdf_path, page_numbers, config,
                                                  provider, page_texts, share_pages,
                                                  usage=usage)
            except LLMUnavailable as exc:
                unavailable.append(f"{provider.name}: {exc}")
                continue
            if result is not None and _filled(result):
                result.usage = usage
                result.pages_selected = pages_1indexed
                result.model = provider.name
                return result
            continue

        if page_texts is None:
            page_texts = read_page_texts(pdf_path, page_numbers)
            if not any(len(t.strip()) >= MIN_TEXT_CHARS for t in page_texts.values()):
                page_texts = ocr_pages(pdf_path, page_numbers)

        groups = group_pages(page_texts, share_pages) if split else {}
        if not groups:
            groups = {"all": sorted(page_texts)}

        if provider.name.startswith("ollama"):
            print("   (local model; first call also loads the weights - be patient)")

        merged = FinancialStatementExtraction()
        started = time.time()
        failed = False
        for group, pages in groups.items():
            if GROUP_FIELDS.get(group) == []:
                continue
            text = build_document_text({n: page_texts[n] for n in pages})
            if not text:
                continue
            fields = GROUP_FIELDS.get(group)
            prompt = _focus_prompt(fields) if fields else EXTRACTION_PROMPT
            print(f"  [{group}] pages {[p+1 for p in pages]}, {len(text):,} chars")
            try:
                part = extract_from_text(text, provider, prompt=prompt, usage=usage)
            except LLMUnavailable as e:
                print(f"    \u2717 {e}")
                unavailable.append(f"{provider.name}: {e}")
                failed = True
                break
            except Exception as e:
                print(f"    \u2717 {type(e).__name__}: {e}")
                continue
            before = _filled(merged)
            merge_group(merged, part, group)
            print(f"    +{_filled(merged)-before} field(s)")

        if failed:
            continue

        _apply_current_table_guard(merged, page_texts, groups)
        _apply_treasury_date_guard(merged, page_texts, groups)
        for warning in derive_fields(merged):
            print(f"    \u26a0 {warning}")

        with usage.stage("assess"):
            merged.field_confidence = assess(merged, page_texts)
        merged.usage = usage
        merged.pages_selected = pages_1indexed
        merged.model = provider.name

        if _filled(merged):
            print(f"  \u2713 {_filled(merged)}/{len(FIELDS)} fields in {time.time()-started:.0f}s\n")
            return merged
        print("  \u2717 no fields filled")

    if unavailable:
        # Every provider was unreachable, throttled or misconfigured. That is a
        # transient condition on our side, not a bad document: an HTTP caller should
        # see 503 and retry, not 422 and go looking for a fault in their PDF.
        raise LLMUnavailable("no provider was available - " + "; ".join(unavailable))
    raise LLMError("Every provider failed")


def ocr_pages(pdf_path: str, page_numbers: list) -> dict:
    """OCR pages that have no text layer. Only reached for scanned filings.

    Requires tesseract (`brew install tesseract tesseract-lang`) and pytesseract.
    Indonesian filings are bilingual, so both language packs are requested.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        print("  (OCR unavailable: pip install pytesseract, brew install tesseract)")
        return {}

    import io
    texts = {}
    for n in page_numbers:
        try:
            image = Image.open(io.BytesIO(render_pdf_page_to_image(pdf_path, n)))
            texts[n] = pytesseract.image_to_string(image, lang="ind+eng")
            print(f"  OCR page {n+1}: {len(texts[n]):,} chars")
        except Exception as e:
            print(f"  OCR page {n+1} failed: {e}")
    return texts


def _extract_from_images(pdf_path, page_numbers, config, provider, page_texts=None,
                         share_pages=None, usage=None):
    """Vision path: one call per statement, showing all of that statement's pages.

    Sending pages one at a time was necessary when every page cost a separate
    request anyway; grouping them means the model sees a statement whole -- the
    balance sheet's section headings and its indented rows land in the same call as
    the numbers underneath them, which is the context a flattened text layer loses.
    """
    import base64

    dpi = int(os.getenv("IMAGE_DPI", "150"))
    split = os.getenv("SPLIT_BY_STATEMENT", "true").lower() in ("1", "true", "yes")

    groups = group_pages(page_texts, share_pages) if (split and page_texts) else {}
    if not groups:
        groups = {"all": list(page_numbers)}

    merged = FinancialStatementExtraction()
    for group, pages in groups.items():
        if GROUP_FIELDS.get(group) == []:
            continue
        images = []
        for n in pages:
            try:
                images.append(base64.standard_b64encode(
                    render_pdf_page_to_image(pdf_path, n, dpi=dpi)).decode())
            except Exception as exc:
                print(f"    \u2717 render page {n+1}: {exc}")
        if not images:
            continue

        fields = GROUP_FIELDS.get(group)
        prompt = _focus_prompt(fields) if fields else EXTRACTION_PROMPT
        kb = sum(len(i) for i in images) / 1024
        print(f"  [{group}] pages {[p+1 for p in pages]}, {len(images)} image(s), {kb:,.0f} KB")

        try:
            raw = provider.complete(SYSTEM_PROMPT, prompt, images=images, usage=usage)
            data = parse_json(raw)
            data.pop("evidence", None)
            part = FinancialStatementExtraction.from_dict(_coerce_numbers(data))
        except LLMUnavailable as exc:
            # Raised rather than swallowed into a None: the caller distinguishes "this
            # provider is gone" from "this provider read nothing useful", and only the
            # first should send an HTTP caller away to retry later.
            print(f"    \u2717 {exc}")
            print(f"    abandoning {provider.name}")
            raise
        except Exception as exc:
            print(f"    \u2717 {type(exc).__name__}: {exc}")
            continue

        before = _filled(merged)
        merge_group(merged, part, group)
        print(f"    +{_filled(merged) - before} field(s)")

    _apply_current_table_guard(merged, page_texts, groups)
    _apply_treasury_date_guard(merged, page_texts, groups)
    for warning in derive_fields(merged):
        print(f"    \u26a0 {warning}")

    with (usage.stage("assess") if usage else _nullcontext()):
        merged.field_confidence = assess(merged, page_texts or {})

    if not _filled(merged):
        print("\u2717 Failed to extract any field\n")
        return None
    print(f"  \u2713 {_filled(merged)}/{len(FIELDS)} fields\n")
    return merged






if __name__ == "__main__":
    import sys

    test_pdf = sys.argv[1] if len(sys.argv) > 1 else "data/raw/Q1_2022_ARCI.pdf"
    try:
        result = extract_from_pdf(test_pdf)
    except LLMError as e:
        # Expected operational states (model not pulled, server down, rate limited)
        # are not bugs; a traceback here only buries the sentence that helps.
        print(f"\n\u2717 {e}")
        raise SystemExit(1)

    if not result:
        print("\u2717 Extraction failed")
        raise SystemExit(1)

    print("=== AS PRINTED ===")
    print(json.dumps(result.to_dict(), indent=2))

    usage = getattr(result, "usage", None)
    if usage:
        u = usage.to_dict()
        tokens = u["tokens"]
        stages = ", ".join(f"{k} {v/1000:.1f}s" for k, v in u["latency_ms"].items())
        print(f"\n=== USAGE ===")
        print(f"  {u['llm_calls']} LLM call(s) | {stages}")
        print(f"  tokens in {tokens['input'] if tokens['input'] is not None else '-'}"
              f" / out {tokens['output'] if tokens['output'] is not None else '-'}")
        cost = u["cost"]
        print(f"  cost {cost['amount']} {cost['currency']}" if cost["amount"] is not None
              else f"  cost - ({cost.get('reason', 'unknown')})")
        for note in u["notes"]:
            print(f"  note: {note}")

    scores = getattr(result, "field_confidence", {})
    if scores:
        print("\n=== CONFIDENCE ===")
        for name, s in sorted(scores.items(), key=lambda kv: kv[1]["confidence"]):
            mark = "ABSTAINED" if s["abstained"] else ("grounded" if s["grounded"]
                   else "NOT IN TEXT" if s["grounded"] is False else "-")
            print(f"  {name:30}{s['confidence']:>6.2f}  {mark}")

    try:
        page_texts = read_page_texts(test_pdf, select_statement_pages(test_pdf).pages)
        norm = to_idr(result, pdf_path=test_pdf,
                      document_text=build_document_text(page_texts))
    except ValueError as e:
        print(f"\n\u2717 Konversi ke Rupiah gagal: {e}")
        raise SystemExit(1)

    print("\n=== IN FULL RUPIAH ===")
    if norm["fx"]:
        fx = norm["fx"]
        print(f"kurs: {fx.idr_per_usd:,.2f} IDR/USD  ({fx.source}, hal. {fx.page})")
        print(f"       \"{fx.evidence[:70]}\"")
    print(f"skala: x{norm['scale_applied']:,}")
    for w in norm["warnings"]:
        print(f"  \u26a0 {w}")
    print()
    for k, v in norm["values"].items():
        if v is None:
            print(f"  {k:24} -")
        elif isinstance(v, str):
            print(f"  {k:24} {v}")
        else:
            print(f"  {k:24} {v:>28,}")
