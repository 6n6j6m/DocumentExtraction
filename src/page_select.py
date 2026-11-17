"""
Deterministic page selection for multi-page financial statement filings.

Why this exists: IDX quarterly/annual filings run 50-150+ pages, but the four
primary statements (balance sheet, income statement, statement of changes in
equity, cash flow statement) are packed into the first handful of pages.
Sending the whole document to a VLM would be ~15x more expensive than necessary.

Method: Keyword scan over each page's title region (first 250 characters).
The 250-char threshold was chosen empirically to avoid false positives from
auditor opinion pages while still catching all real statement pages.
"""

import re
from dataclasses import dataclass

# Bilingual title markers (Indonesian + English)
# Issuers word these titles differently. "Neraca" is the pre-2012 term and is still
# used by some filers; "laba rugi komprehensif" and "penghasilan komprehensif" are
# both current. Matching only one wording silently returns zero pages for an issuer
# that uses another -- a failure that looks like an empty document, not a bad regex.
STATEMENT_MARKERS = [
    # Balance sheet
    r"laporan posisi keuangan", r"statement of financial position",
    r"\bneraca\b", r"\bbalance sheet\b",
    # Income statement
    r"laporan laba rugi", r"statement of profit or loss",
    r"laba rugi dan penghasilan komprehensif", r"comprehensive income",
    r"\bincome statement\b",
    # Equity
    r"laporan perubahan ekuitas", r"statement of changes in equity",
    # Cash flow
    r"laporan arus kas", r"statement of cash flows", r"\bcash flow",
]
# Spaces are optional: PGAS Q4 2023's text layer has none ("LAPORANPOSISIKEUANGAN",
# "STATEMENTOFPROFITORLOSS"), so no title matched and selection fell back to the first
# ten pages -- cover, auditor's report -- and nine of ten fields came back empty.
def _spaced(pattern: str) -> str:
    return pattern.replace(" ", r"\s*")


_MARKER_RE = re.compile("|".join(_spaced(m) for m in STATEMENT_MARKERS), re.IGNORECASE)

# Title region size (in characters)
TITLE_REGION_CHARS = 250

# Fallback behavior
MAX_PAGES_DEFAULT = 20
FALLBACK_FIRST_N_PAGES = 10
ALWAYS_SCAN_ALL_IF_UNDER = 15


@dataclass
class PageSelection:
    """Result of page selection."""
    pages: list[int]              # 0-indexed page numbers
    total_pages: int
    method: str                   # "keyword_match" | "fallback_first_n" | "whole_document"
    matched_pages: list[int]      # Which pages had keyword matches
    share_capital_pages: list[int] = None   # the shareholder table total_share is read from
    bank_loan_pages: list[int] = None       # lender breakdown when statement combines lenders

    def __post_init__(self):
        if self.share_capital_pages is None:
            self.share_capital_pages = []
        if self.bank_loan_pages is None:
            self.bank_loan_pages = []


# Where the issued share count is disclosed varies by issuer, and it is the one
# scored field that is not necessarily printed on a primary statement at all:
#
#   ARCI  balance sheet, beside the share capital line   (inside the span)
#   CPIN  capital note, a few pages after the statements (inside the span)
#   JPFA  shareholding note, page 127 of 171            (far outside the span)
#
# Relying on it falling inside the statement span is therefore a bias towards the
# issuers it happened to work for. The count is instead located directly, by the
# phrases used to introduce it, anywhere in the document.
SHARE_CAPITAL_MARKERS = [
    r"ditempatkan dan disetor penuh", r"issued and fully paid",
    r"modal ditempatkan", r"saham beredar", r"outstanding shares",
]
_SHARE_MARKER_RE = re.compile("|".join(SHARE_CAPITAL_MARKERS), re.IGNORECASE)

# Share counts can be smaller than 1e9: RCCC has 750.000.000 shares. Requiring at
# least two groups and a 100%-total-row check keeps note prose and percentages out.
# Both separators are accepted: PTBA, ITMG, AADI, ADMR and EMAS use English grouping.
_SHARE_COUNT_RE = re.compile(r"\d{1,3}([.,])\d{3}(?:\1\d{3})+")

# Some text layers split the first digit of a count into a separate run (RCCC:
# printed 750.000.000 -> extracted "7 50.000.000"). Repair only that shape so
# adjacent numeric columns are not accidentally merged.
_SPLIT_SHARE_LEAD = re.compile(r"(?<!\d)(\d)[ \t]+(?=\d{1,3}[.,]\d{3}|[.,]\d{3})")


def _repair_share_count_gaps(line: str) -> str:
    return _SPLIT_SHARE_LEAD.sub(r"\1", line or "")

# AUTHORISED capital is a ceiling, not the shares in issue. DSNG prints
# "Modal dasar: 35.000.000.000 saham" on the line above "Modal ditempatkan dan disetor
# penuh", so a marker-plus-neighbour search counted the ceiling as found and stopped --
# and the model, correctly refusing to report authorised capital, left total_share empty
# on all eighteen DSNG filings.
_AUTHORISED_RE = re.compile(r"modal\s+dasar|authori[sz]ed", re.I)

# The shareholder-composition table ends in a total row that carries the issued count
# beside 100% of ownership -- every issuer in the archive prints one, in one of these
# forms: "100,00", "100.00", "100%", "100,00%", "100,000", "100,0000" (TAPG Q3 2023).
#
# A bare "100" is accepted only on a line that opens as a total row. DSNG's history note
# reads "Rp 100 (Rupiah penuh) per saham ... changed to 1,844,700,000 shares" -- a par
# value beside a share count -- and accepting any plain 100 made that sentence the
# best-evidenced share page in the filing. But ADMR Q1 2023 prints its real total as
# "Total 40,882,331,500 100 303,919,662", with no mark at all.
_HUNDRED_PERCENT_RE = re.compile(r"(?<![\d.,])100(?:[.,]0{2,4}\s*%?|\s*%)(?![\d.,])")
_BARE_TOTAL_ROW_RE = re.compile(r"^\s*(?:total|jumlah)\b.*(?<![\d.,])100(?![\d.,%])", re.I)
# A few filings print an internally inconsistent ownership total. PURA Q1 2023, for
# example, prints 104% beside the correctly summed 6,301,930,902 shares; Q2 prints
# 100%. The count is still explicit in a shareholder-table total row. Accept a modest
# overage only there, after the share count, and only when the filing prints a percent
# sign. This does not admit arbitrary percentages or subsidiary rows as the table total.
_OVER_100_TOTAL_PERCENT_RE = re.compile(
    r"^\s*(?:total|jumlah)\b.*(?<![\d.,])(?:10[1-9]|110)(?:[.,]\d+)?\s*%", re.I)
_OVER_100_PERCENT_RE = re.compile(r"(?<![\d.,])(?:10[1-9]|110)(?:[.,]\d+)?\s*%")


def _hundred_percent(line: str) -> bool:
    return bool(_HUNDRED_PERCENT_RE.search(line) or _BARE_TOTAL_ROW_RE.search(line))


def total_row_count(line: str):
    """The share count on a shareholder-table total row, or None.

    The count comes BEFORE the 100% -- "Total 11.726.575.201 100,00", "1,129,925,000
    564,963 63,892 100.00". A subsidiary table reverses it: ADMR Q2 2025 lists "100.00%
    100.00% 1,069,356,077", ownership percentages followed by total assets in dollars, on a
    page that names the subsidiary's shareholders -- and was found as the share table.
    """
    line = _repair_share_count_gaps(line)
    if _AUTHORISED_RE.search(line):
        return None
    match = _SHARE_COUNT_RE.search(line)
    if not match:
        return None
    rest = line[match.end():]
    if (_HUNDRED_PERCENT_RE.search(rest)
            or (_BARE_TOTAL_ROW_RE.search(line) and re.search(
                r"(?<![\d.,])100(?![\d.,%])", rest))
            or (_OVER_100_TOTAL_PERCENT_RE.search(line)
                and _OVER_100_PERCENT_RE.search(rest))):
        return match.group(0)
    return None
_SHAREHOLDER_PAGE_RE = re.compile(r"pemegang\s+saham|shareholders?\b", re.I)

# Some issuers put bank and non-bank financial-institution loans in one balance-sheet
# line, then split them by lender in the debt note. The statement row is already valid
# for `utang_bank`; select the note as additional evidence for its current portion.
_MIXED_BANK_ROW_RE = re.compile(
    r"utang\s+bank\s+dan\s+lembaga[\s\S]{0,100}non\s*[-–]?\s*bank|"
    r"bank\s+loans?\s+and\s+non\s*[-–]?\s*bank\s+financial\s+institutions?\s+loans?",
    re.I)
_BANK_NOTE_TITLE_RE = re.compile(
    r"^\s*\d{1,2}\.\s*(?:utang\s+bank\s+dan\s+lembaga\s+keuangan\s+non|"
    r"bank\s+loans?\s+and\s+non\s*[-–]?\s*bank\s+financial)", re.I | re.M)
_CURRENT_PORTION_RE = re.compile(r"bagian\s+lancar|current\s+portion", re.I)


def find_bank_loan_note_pages(page_texts, *, mixed_row_present: bool = True) -> list:
    """Find the first debt-note page and its current-portion continuation, if any.

    This is narrowly gated by a combined bank/non-bank financial-institution row. In
    the note, the first page usually has the lender table and the next page carries the
    current-portion breakdown. Narrative references to collateral or bank loans do not
    match the numbered note-title pattern.
    """
    if not mixed_row_present:
        return []
    items = (sorted(page_texts.items()) if isinstance(page_texts, dict)
             else list(enumerate(page_texts)))
    texts = {int(n): (text or "") for n, text in items}
    for n in sorted(texts):
        if not _BANK_NOTE_TITLE_RE.search(texts[n]):
            continue
        pages = [n]
        next_text = texts.get(n + 1, "")
        if _CURRENT_PORTION_RE.search(next_text) and re.search(r"\bbank\b", next_text, re.I):
            pages.append(n + 1)
        elif _CURRENT_PORTION_RE.search(texts[n]) and re.search(r"\bbank\b", texts[n], re.I):
            pass
        return pages
    return []


def find_shareholder_table_pages(page_texts, limit: int = 1) -> list:
    """Pages where a shareholder table ends: a share count beside 100% of ownership.

    total_share is the count OUTSTANDING, and the shareholder table is the one place a
    filing states who holds its shares -- and therefore what is outstanding: a printed
    "Jumlah saham beredar" row (JPFA, PTBA), a treasury row to take off the total (EMAS,
    ITMG), or no treasury row, in which case the total is outstanding. The share-capital
    line on the balance sheet or the statement of changes in equity is deliberately NOT
    searched: it prints the issued count and says nothing about what is outstanding.

    Pages come back in document order and the first is the one to read. The current
    date's table is printed before the comparative one -- EMAS Q1 2026 on page 64, its
    December 2025 table on page 65 -- and a narrative phrase search would reach a
    company's history first: DSNG's notes state 1.844.700.000 shares at its listing, a
    stock split before the 10.599.842.400 in issue now.

    Authorised capital never counts as a total row.

    Args:
        page_texts: list of page text, or {page_number: text}
        limit: stop after this many pages.
    """
    items = (sorted(page_texts.items()) if isinstance(page_texts, dict)
             else list(enumerate(page_texts)))

    def issued_count(lines: list, j: int) -> bool:
        """Line j carries a share count that is not authorised capital.

        Authorised capital is recognised by its label on the same line OR the line
        directly above, because issuers wrap it both ways. DSNG prints
        "Modal dasar: Authorized capital:" and the 35.000.000.000 on the next line,
        right above the issued-capital phrase -- a same-line check let that ceiling
        through as the count in issue. ARCI wraps the other way, the issued phrase
        above its count, so the line above is only read as authorised when neither
        line carries an issued-capital phrase.
        """
        line = _repair_share_count_gaps(lines[j])
        if not _SHARE_COUNT_RE.search(line) or _AUTHORISED_RE.search(line):
            return False
        above = _repair_share_count_gaps(lines[j - 1]) if j > 0 else ""
        if _AUTHORISED_RE.search(above) and not (
                _SHARE_MARKER_RE.search(line) or _SHARE_MARKER_RE.search(above)):
            return False
        return True

    found = []
    previous_n, previous_text = None, ""
    for n, text in items:
        text = text or ""
        lines = text.split("\n")
        # The table's heading can sit on the page before its total. DSNG's composition
        # table starts on page 77 and totals on page 78, which repeats no heading. Only
        # the physically preceding page counts, so a heading far away cannot vouch for a row.
        about_shareholders = bool(_SHAREHOLDER_PAGE_RE.search(text)) or (
            previous_n == n - 1 and bool(_SHAREHOLDER_PAGE_RE.search(previous_text)))
        previous_n, previous_text = n, text
        if about_shareholders and any(
                issued_count(lines, j) and total_row_count(lines[j])
                for j in range(len(lines))):
            found.append(n)
            if len(found) >= limit:
                break
    if not found:
        found = _shareholder_table_without_total_count(items, limit)
    if not found:
        found = _shareholder_table_in_split_columns(items, limit)
    return found


_SHARE_CAPITAL_TITLE_RE = re.compile(r"modal\s+saham|share\s+capital", re.I)
_COUNT_WITH_PERCENT_RE = re.compile(r"\d{1,3}(?:[.,]\d{3}){2,}\s+\d{1,3}[.,]\d{1,2}\s*%")


def _shareholder_table_without_total_count(items: list, limit: int) -> list:
    """The share-capital note's shareholder table when its total row lost its count.

    PURA Q2 2025 types its shareholder table one glyph per run; OCR recovers the
    holders ("962.621.880 15,28%") and a "100%" line but drops the total's share count,
    so the rule above -- a count beside 100% -- never fires and total_share is never
    asked for. Only used when that rule found nothing: a page titled as the share-
    capital note, about shareholders, with a 100% line and at least two holder rows
    printing a count and a percentage. The page is then read from its image.
    """
    found = []
    for n, text in items:
        text = text or ""
        if not (_SHARE_CAPITAL_TITLE_RE.search(text) and _SHAREHOLDER_PAGE_RE.search(text)):
            continue
        if not _HUNDRED_PERCENT_RE.search(text):
            continue
        if len(_COUNT_WITH_PERCENT_RE.findall(text)) < 2:
            continue
        found.append(n)
        if len(found) >= limit:
            break
    return found


_TOTAL_COUNT_LINE_RE = re.compile(r"^\s*(?:jumlah|total)\b\s*(\d{1,3}([.,])\d{3}(?:\2\d{3}){2,})\s*$",
                                  re.I | re.M)


def _shareholder_table_in_split_columns(items: list, limit: int) -> list:
    """The share-capital note when OCR has pulled its table apart by column.

    APEX Q3 2025's page 53 is OCR'd and comes back as one column at a time: the holders,
    then their counts, then "Jumlah 3.546.466.661" on a line of its own, and the
    percentages ("53,510%", "100%") further down beside the amounts. Neither rule above
    fires -- no count sits beside 100%, no count beside any percentage -- so total_share
    was never asked for. Only used when both found nothing: a page titled as the
    share-capital note, about shareholders, with a bare "Jumlah/Total <count>" line that
    is not authorised capital and a 100% line. The page is then read by the model.
    """
    found = []
    for n, text in items:
        text = text or ""
        if not (_SHARE_CAPITAL_TITLE_RE.search(text) and _SHAREHOLDER_PAGE_RE.search(text)):
            continue
        if not _HUNDRED_PERCENT_RE.search(text):
            continue
        lines = text.split("\n")
        totals = [j for j, line in enumerate(lines) if _TOTAL_COUNT_LINE_RE.match(line)
                  and not _AUTHORISED_RE.search(line)
                  and not (j > 0 and _AUTHORISED_RE.search(lines[j - 1]))]
        if not totals:
            continue
        found.append(n)
        if len(found) >= limit:
            break
    return found


def shareholder_note_pages(page_texts: dict, page: int) -> list:
    """The table's total page, plus the page before it when only that one has the heading.

    The rows above the total -- a "saham beredar" subtotal, a treasury row -- belong with
    it, and on a table split across pages they are on the page with the heading.
    """
    if not _SHAREHOLDER_PAGE_RE.search(page_texts.get(page) or "") and (page - 1) in page_texts:
        return [page - 1, page]
    return [page]


# Two ways a real statement title escapes the title region, both measured on the archive.
#
# 1. A boilerplate translation notice pushes it out. Many issuers open every page with
#    "The original consolidated financial statements included herein are in the
#    Indonesian language." -- about ninety characters -- followed by a bilingual company
#    name. LSIP's titles then start at character 240-253 and TAPG's income statement at
#    236, so a 250-character region cut each title mid-word: all eighteen LSIP filings
#    fell back to "the first ten pages" (cover, auditor's report, table of contents), and
#    TAPG's income statement was grouped as more balance sheet. The notice says nothing
#    about which page this is, so it is removed before the region is measured.
#
# 2. A bilingual two-column layout splits the title across lines, with the English
#    column in between:
#        LAPORAN POSISI CONSOLIDATED STATEMENT OF
#        KEUANGAN KONSOLIDASIAN FINANCIAL POSITION
#    "Laporan posisi keuangan" never appears whole, so TLDN's first balance-sheet page --
#    the one carrying cash and current assets -- was left out of the selection, and
#    PTBA's Q4 2025 balance sheet was missed entirely.
#
# Widening the region instead was measured and rejected: at 300 characters it fixed LSIP
# and TAPG but moved the page span of ADMR, ITMG and PTBA filings that were already
# right, because note pages mention the statements near their top too. These two rules
# changed only the filings that were wrong (LSIP 18, TLDN 10, TAPG 6, PTBA 2) across all
# 215 filings in the archive.
_TRANSLATION_NOTICE = re.compile(r"^\s*the\s*original[^.]{0,220}?language\.\s*", re.I)
_WRAPPED_TITLE_RES = {
    "balance_sheet": re.compile(r"laporan\s+posisi\b[^\n]*\n\s*keuangan|"
                                r"statement\s+of[^\n]*\n[^\n]*financial\s+position", re.I),
    "income":        re.compile(r"laporan\s+laba\b[^\n]*\n\s*rugi", re.I),
    "equity":        re.compile(r"laporan\s+perubahan\b[^\n]*\n\s*ekuitas", re.I),
    "cash_flow":     re.compile(r"laporan\s+arus\b[^\n]*\n\s*kas", re.I),
}


def _title_head(text: str) -> str:
    """The part of a page where its title can be: the region after any translation notice."""
    return _TRANSLATION_NOTICE.sub("", text or "", count=1)[:TITLE_REGION_CHARS]


def _is_statement_title(head: str) -> bool:
    return bool(_MARKER_RE.search(head)) or any(r.search(head) for r in _WRAPPED_TITLE_RES.values())


def _title_group(head: str):
    """Which statement a title region names, whole or split across lines; None if none."""
    for group, pattern in _GROUP_RES.items():
        if pattern.search(head):
            return group
    for group, pattern in _WRAPPED_TITLE_RES.items():
        if pattern.search(head):
            return group
    return None


def select_from_page_texts(page_texts: list[str], *, 
                          max_pages: int = MAX_PAGES_DEFAULT,
                          always_scan_all_if_under: int = ALWAYS_SCAN_ALL_IF_UNDER) -> PageSelection:
    """Pure decision logic for page selection.
    
    Args:
        page_texts: List of extracted text from each page
        max_pages: Maximum pages to select
        always_scan_all_if_under: For documents with fewer pages than this, scan all
        
    Returns:
        PageSelection with pages (0-indexed), total_pages, method, matched_pages
    """
    total = len(page_texts)
    
    # Short documents: scan all pages
    if total <= always_scan_all_if_under:
        return PageSelection(
            pages=list(range(total)),
            total_pages=total,
            method="whole_document",
            matched_pages=[]
        )
    
    # Find pages with statement titles (in title region only)
    matched = []
    for i, text in enumerate(page_texts):
        if text and _is_statement_title(_title_head(text)):
            matched.append(i)
    
    # No matches: fallback to first N pages
    if not matched:
        n = min(FALLBACK_FIRST_N_PAGES, total)
        return PageSelection(
            pages=list(range(n)),
            total_pages=total,
            method="fallback_first_n",
            matched_pages=[]
        )
    
    # Matches found: take contiguous span
    lo, hi = min(matched), max(matched)
    span = list(range(lo, hi + 1))
    
    # Cap if too long
    if len(span) > max_pages:
        span = span[:max_pages]
    
    return PageSelection(
        pages=span,
        total_pages=total,
        method="keyword_match",
        matched_pages=matched
    )


def select_statement_pages(pdf_path: str, *,
                          max_pages: int = MAX_PAGES_DEFAULT,
                          always_scan_all_if_under: int = ALWAYS_SCAN_ALL_IF_UNDER) -> PageSelection:
    """Select pages from PDF based on keyword matching.
    
    Args:
        pdf_path: Path to PDF file
        max_pages: Maximum pages to select
        always_scan_all_if_under: For documents with fewer pages, scan all
        
    Returns:
        PageSelection with 0-indexed page numbers
    """
    from pdftext import page_texts, page_titles

    # Selection matches on statement TITLES, so it reads title regions rather than
    # pages. On a filing whose characters are glyph ids (EMAS embeds subset fonts with
    # no ToUnicode CMap) that is the difference between OCR'ing 97 pages at full
    # resolution and OCR'ing 97 page-heads at a fifth of it. Without either, selection
    # would match nothing and fall back to "the first ten pages" without ever saying it
    # could not read the document.
    titles = page_titles(pdf_path)
    texts = [titles.get(n, "") for n in range(len(titles))]

    selection = select_from_page_texts(texts, max_pages=max_pages,
                                       always_scan_all_if_under=always_scan_all_if_under)

    # total_share comes from the shareholder table in the notes, for every filing -- see
    # find_shareholder_table_pages. The raw text layer is searched first, which every
    # filing pays for (a few seconds, no OCR). Only when the table is not visible there --
    # a shredded layer (JPFA, GTRA, TOTL) or one made of glyph ids (EMAS Q3 2025) -- are
    # the unreadable pages OCR'd to look again.
    layer = page_texts(pdf_path, use_ocr=False)
    if selection.method == "keyword_match":
        selection.pages = sorted(set(selection.pages) |
                                 set(_untitled_cash_flow_after(selection.pages, texts, layer)))
    tables = find_shareholder_table_pages(layer, limit=1)
    if not tables:
        layer = page_texts(pdf_path)
        tables = find_shareholder_table_pages(layer, limit=1)
    if tables:
        selection.share_capital_pages = shareholder_note_pages(layer, tables[0])
        selection.pages = sorted(set(selection.pages) | set(selection.share_capital_pages))
    statement_pages = [n for n in selection.pages
                       if n not in selection.share_capital_pages]
    mixed_debt = any(_MIXED_BANK_ROW_RE.search(layer.get(n, "") or "")
                     for n in statement_pages)
    if mixed_debt:
        selection.bank_loan_pages = find_bank_loan_note_pages(
            layer, mixed_row_present=True)
        if selection.bank_loan_pages:
            selection.pages = sorted(set(selection.pages) | set(selection.bank_loan_pages))
    return selection


# Which statement each title marker belongs to, so pages can be grouped by the
# statement they carry rather than treated as one undifferentiated blob.
STATEMENT_GROUPS = {
    "balance_sheet": [r"laporan posisi keuangan", r"statement of financial position",
                      r"\bneraca\b", r"\bbalance sheet\b"],
    "income":        [r"laporan laba rugi", r"statement of profit or loss",
                      r"laba rugi dan penghasilan komprehensif", r"comprehensive income",
                      r"\bincome statement\b"],
    "equity":        [r"laporan perubahan ekuitas", r"statement of changes in equity"],
    "cash_flow":     [r"laporan arus kas", r"statement of cash flows", r"\bcash flow"],
}
_GROUP_RES = {g: re.compile("|".join(_spaced(m) for m in p), re.IGNORECASE)
              for g, p in STATEMENT_GROUPS.items()}


def classify_pages(page_texts: dict) -> dict:
    """Group pages by which statement they belong to.

    A statement runs from its title page until the next statement's title, so a
    continuation page (which repeats no title) inherits the group of the page
    before it.

    Args:
        page_texts: {page_number: text}
    Returns:
        {group_name: [page_numbers]} preserving order, groups with no pages omitted.
    """
    groups = {}
    current = None
    for n in sorted(page_texts):
        group = _title_group(_title_head(page_texts[n] or ""))
        if group:
            current = group
        if current:
            groups.setdefault(current, []).append(n)
    if "cash_flow" not in groups:
        _recover_cash_flow_by_body(page_texts, groups)
    return groups


# The body of a cash-flow statement, which no other statement prints: the operating
# section heading, followed on the same page by the investing or financing one.
# Bilingual pages set the two languages side by side, so a heading can break across lines
# with the other language in between: ENRG prints "ARUS KAS DARI CASH FLOWS FROM" over
# "AKTIVITAS OPERASI OPERATING ACTIVITIES".
_CASH_FLOW_OPERATING = re.compile(r"arus\s+kas\s+dari\s+aktivitas|cash\s+flows?\s+from\s+"
                                  r"operating|arus\s+kas\s+dari\b[^\n]*\n\s*aktivitas\s+"
                                  r"operasi", re.I)
_CASH_FLOW_OTHER = re.compile(r"aktivitas\s+(?:investasi|pendanaan)|investing\s+activities|"
                              r"financing\s+activities", re.I)


def _untitled_cash_flow_after(span: list, titles: list, layer: dict) -> list:
    """The cash-flow pages just past the selected span, when no selected page is titled one.

    ENRG Q1 2023 heads its cash-flow page "CATATAN ATAS LAPORAN KEUANGAN" like TRIN Q4
    2022, but there the page fell inside the span of titled pages and
    _recover_cash_flow_by_body found it; ENRG prints it LAST, so the span ended one page
    before it and cash from operations was never asked for. Only the page right after
    the span is looked at, by the same body test, and the one after that if it continues.
    """
    if not span or any(_title_group(_title_head(titles[n] if n < len(titles) else ""))
                       == "cash_flow" for n in span):
        return []
    n = max(span) + 1
    text = layer.get(n) or ""
    if not (_CASH_FLOW_OPERATING.search(text) and _CASH_FLOW_OTHER.search(text)):
        return []
    following = layer.get(n + 1) or ""
    if _CASH_FLOW_OTHER.search(following) and not _title_group(_title_head(following)) \
            and not _CASH_FLOW_OPERATING.search(following):
        return [n, n + 1]
    return [n]


def _recover_cash_flow_by_body(page_texts: dict, groups: dict) -> None:
    """Find the cash-flow statement by what it prints when no page is titled as one.

    TRIN Q4 2022 heads its cash-flow pages "CATATAN ATAS LAPORAN KEUANGAN
    KONSOLIDASIAN" -- the notes title, a typesetting slip -- so the pages joined the
    equity statement before them and no cash-flow question was ever asked. Only used
    when title matching found no cash-flow page at all; the page that opens the
    operating section, and the page after it if it continues to financing, are moved.
    """
    for n in sorted(page_texts):
        text = page_texts[n] or ""
        if not (_CASH_FLOW_OPERATING.search(text) and _CASH_FLOW_OTHER.search(text)):
            continue
        pages = [n]
        following = page_texts.get(n + 1) or ""
        if (n + 1) in page_texts and _CASH_FLOW_OTHER.search(following) \
                and not _title_group(_title_head(following)):
            pages.append(n + 1)
        for name in list(groups):
            groups[name] = [p for p in groups[name] if p not in pages]
            if not groups[name]:
                del groups[name]
        groups["cash_flow"] = pages
        return
