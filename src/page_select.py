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
_MARKER_RE = re.compile("|".join(STATEMENT_MARKERS), re.IGNORECASE)

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
    share_capital_pages: list[int] = None   # note pages carrying the share count

    def __post_init__(self):
        if self.share_capital_pages is None:
            self.share_capital_pages = []


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

# A share count is a large grouped number: at least three dot-groups, i.e. >= 1e9
# ("24.835.000.000", "11.620.308.701", "16.398.000.000"). Requiring the grouping
# keeps note prose and percentages out.
_SHARE_COUNT_RE = re.compile(r"\d{1,3}(?:\.\d{3}){2,}")

# The marker and the number are often on adjacent lines rather than the same one:
# ARCI prints "Ditempatkan dan disetor penuh -" and the count on the line below.
_SHARE_NEIGHBOURHOOD = 1


def find_share_capital_pages(page_texts, limit: int = 2) -> list:
    """Pages where an issued/outstanding share count is actually printed.

    Args:
        page_texts: list of page text, or {page_number: text}
        limit: stop after this many pages, so a filing that mentions share capital
               throughout its notes does not drag the whole document into the call.
    """
    items = (sorted(page_texts.items()) if isinstance(page_texts, dict)
             else list(enumerate(page_texts)))

    found = []
    for n, text in items:
        lines = (text or "").split("\n")
        marked = [i for i, line in enumerate(lines) if _SHARE_MARKER_RE.search(line)]
        if not marked:
            continue
        for i in marked:
            window = lines[max(0, i - _SHARE_NEIGHBOURHOOD): i + _SHARE_NEIGHBOURHOOD + 1]
            if any(_SHARE_COUNT_RE.search(line) for line in window):
                found.append(n)
                break
        if len(found) >= limit:
            break
    return found


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
        if text and _MARKER_RE.search(text[:TITLE_REGION_CHARS]):
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
    import pdfplumber
    
    with pdfplumber.open(pdf_path) as pdf:
        texts = [page.extract_text() or "" for page in pdf.pages]

    selection = select_from_page_texts(texts, max_pages=max_pages,
                                       always_scan_all_if_under=always_scan_all_if_under)

    # The share count is usually printed on the balance sheet's share-capital line, and
    # for every issuer tested it is. Only when no selected page carries it at all is a
    # note page appended -- otherwise this would add a request per document to re-read
    # something already in front of the model.
    candidates = find_share_capital_pages(texts, limit=8)
    if not any(n in selection.pages for n in candidates):
        share = [n for n in candidates if n not in selection.pages][:1]
        if share:
            selection.share_capital_pages = share
            selection.pages = sorted(selection.pages + share)
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
_GROUP_RES = {g: re.compile("|".join(p), re.IGNORECASE) for g, p in STATEMENT_GROUPS.items()}


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
        head = (page_texts[n] or "")[:TITLE_REGION_CHARS]
        for group, pattern in _GROUP_RES.items():
            if pattern.search(head):
                current = group
                break
        if current:
            groups.setdefault(current, []).append(n)
    return groups
