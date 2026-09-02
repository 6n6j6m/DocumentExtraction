"""
Core extraction pipeline for financial statements.

Uses Gemini REST API (via requests) instead of google-generativeai package
to avoid dependency issues. Works with GEMINI_API_KEY environment variable.
"""

import os
import json
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
from page_select import select_statement_pages
from normalize import to_idr, extract_fx_rate


class ExtractorConfig:
    """Configuration for extraction."""
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.max_pdf_pages = int(os.getenv("MAX_PDF_PAGES", "20"))
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")


def render_pdf_page_to_image(pdf_path: str, page_num: int) -> bytes:
    """Render PDF page to PNG bytes using pdf2image.
    
    Args:
        pdf_path: Path to PDF
        page_num: 0-indexed page number
        
    Returns:
        PNG bytes
    """
    images = convert_from_path(pdf_path, first_page=page_num+1, last_page=page_num+1, dpi=150)
    if not images:
        raise ValueError(f"Failed to render page {page_num}")
    
    img = images[0]
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()


def extract_json_from_response(text: str) -> dict:
    """Extract JSON from response, handling markdown code fences.
    
    Args:
        text: Raw response text (may contain markdown, code fences, etc.)
        
    Returns:
        Parsed JSON dict
    """
    # Remove markdown code fences if present
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    return json.loads(text)


def extract_from_image(image_bytes: bytes, config: ExtractorConfig) -> Optional[FinancialStatementExtraction]:
    """Send image to Gemini via REST API and extract financial data.
    
    Args:
        image_bytes: PNG image bytes
        config: ExtractorConfig instance
        
    Returns:
        FinancialStatementExtraction if successful, None otherwise
    """
    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"{SYSTEM_PROMPT}\n\n{EXTRACTION_PROMPT}"
                    },
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": image_base64,
                        }
                    }
                ]
            }
        ]
    }
    
    headers = {
        "Content-Type": "application/json",
    }
    
    params = {
        "key": config.api_key
    }
    
    try:
        print(f"  Sending to Gemini API ({config.model_name})...")
        response = requests.post(config.api_url, json=payload, headers=headers, params=params, timeout=30)
        
        if response.status_code != 200:
            print(f"  ✗ API error: {response.status_code}")
            print(f"    {response.text[:200]}")
            return None
        
        response_data = response.json()
        
        # Extract text from response
        if "candidates" not in response_data or not response_data["candidates"]:
            print(f"  ✗ No candidates in response")
            return None
        
        response_text = response_data["candidates"][0]["content"]["parts"][0]["text"]
        print(f"  Raw response: {response_text[:200]}...")
        
        json_data = extract_json_from_response(response_text)
        print(f"  ✓ Parsed JSON")
        
        # Convert numeric strings to floats where needed
        for key in ['aset', 'total_aset_lancar', 'kas',
                    'liabilitas', 'utang_bank', 'ekuitas',
                    'pendapatan', 'laba_bersih', 'kas_dari_aktivitas_operasi', 'total_share']:
            if key in json_data and json_data[key] is not None:
                try:
                    json_data[key] = float(json_data[key])
                except (ValueError, TypeError):
                    json_data[key] = None
        
        extraction = FinancialStatementExtraction.from_dict(json_data)
        return extraction
        
    except requests.exceptions.Timeout:
        print(f"  ✗ API timeout (30s)")
        return None
    except json.JSONDecodeError as e:
        print(f"  ✗ Failed to parse JSON: {e}")
        return None
    except Exception as e:
        print(f"  ✗ Extraction error: {e}")
        return None


FIELDS = [
    "period_end_date", "aset", "total_aset_lancar", "kas",
    "liabilitas", "utang_bank", "ekuitas", "pendapatan",
    "laba_bersih", "kas_dari_aktivitas_operasi", "total_share", "currency",
    "reporting_scale", "statement_scope",
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


def extract_from_pdf(pdf_path: str, page_numbers: Optional[list] = None) -> Optional[FinancialStatementExtraction]:
    """Extract financial statement data from a PDF.

    Uses page selection to find the statement pages, then extracts from EVERY
    selected page and merges the results, because the fields are spread across
    the balance sheet, income statement and cash flow pages.

    Args:
        pdf_path: Path to PDF file
        page_numbers: 0-indexed pages to try. If None, uses page selection.

    Returns:
        FinancialStatementExtraction with merged fields, or None if nothing extracted.
    """
    config = ExtractorConfig()

    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    if page_numbers is None:
        print(f"\n\U0001F4C4 Selecting pages from {Path(pdf_path).name}...")
        selection = select_statement_pages(pdf_path, max_pages=config.max_pdf_pages)
        page_numbers = selection.pages
        print(f"  Method: {selection.method}")
        print(f"  Pages: {[p+1 for p in page_numbers]} (1-indexed)")
        print(f"  Reduction: {len(page_numbers)}/{selection.total_pages} pages "
              f"({100*(1-len(page_numbers)/selection.total_pages):.1f}% reduction)\n")

    merged = FinancialStatementExtraction()
    pages_used = []

    for page_num in page_numbers:
        print(f"\U0001F50D Extracting from page {page_num + 1}...")
        try:
            image_bytes = render_pdf_page_to_image(pdf_path, page_num)
            extraction = extract_from_image(image_bytes, config)
        except Exception as e:
            print(f"  \u2717 Error: {e}")
            continue

        if extraction is None:
            continue

        before = _filled(merged)
        merge_extractions(merged, extraction)
        after = _filled(merged)

        if after > before:
            pages_used.append(page_num + 1)
            print(f"  \u2713 +{after - before} new field(s) -> {after}/{len(FIELDS)} filled")
        else:
            print("  - no new fields")

        if after == len(FIELDS):
            print("  All fields filled, stopping early.")
            break

    total = _filled(merged)
    if total == 0:
        print("\u2717 Failed to extract any field\n")
        return None

    print(f"\n\u2713 Extracted {total}/{len(FIELDS)} fields from pages {pages_used}\n")
    return merged


if __name__ == "__main__":
    import sys

    test_pdf = sys.argv[1] if len(sys.argv) > 1 else "data/raw/Q1_2022_ARCI.pdf"
    result = extract_from_pdf(test_pdf)

    if not result:
        print("\u2717 Extraction failed")
        raise SystemExit(1)

    print("=== AS PRINTED ===")
    print(json.dumps(result.to_dict(), indent=2))

    try:
        norm = to_idr(result, pdf_path=test_pdf)
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
