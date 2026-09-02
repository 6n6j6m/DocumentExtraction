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
STATEMENT_MARKERS = [
    r"laporan posisi keuangan", r"statement of financial position",
    r"laporan laba rugi", r"statement of profit or loss",
    r"laporan perubahan ekuitas", r"statement of changes in equity",
    r"laporan arus kas", r"statement of cash flows",
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
    
    return select_from_page_texts(texts, max_pages=max_pages,
                                  always_scan_all_if_under=always_scan_all_if_under)
