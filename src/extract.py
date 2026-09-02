"""
Core extraction pipeline for financial statements.
"""

import os
import json
import base64
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import io
import re

# Load environment variables from .env
load_dotenv(Path(__file__).parent.parent / ".env")

from pdf2image import convert_from_path
import google.generativeai as genai

from schema import FinancialStatementExtraction
from prompts import SYSTEM_PROMPT, EXTRACTION_PROMPT


class ExtractorConfig:
    """Configuration for extraction."""
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        self.max_pdf_pages = int(os.getenv("MAX_PDF_PAGES", "20"))
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")
        
        genai.configure(api_key=self.api_key)


def render_pdf_page_to_image(pdf_path: str, page_num: int) -> bytes:
    """Render PDF page to PNG bytes using pdf2image."""
    images = convert_from_path(pdf_path, first_page=page_num+1, last_page=page_num+1, dpi=150)
    if not images:
        raise ValueError(f"Failed to render page {page_num}")
    
    img = images[0]
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()


def extract_json_from_response(text: str) -> dict:
    """Extract JSON from response, handling markdown code fences."""
    # Remove markdown code fences if present
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    return json.loads(text)


def extract_from_image(image_bytes: bytes, config: ExtractorConfig) -> Optional[FinancialStatementExtraction]:
    """Send image to Gemini and extract financial data."""
    model = genai.GenerativeModel(config.model_name)
    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    
    message = [
        {
            "role": "user",
            "parts": [
                {"text": f"{SYSTEM_PROMPT}\n\n{EXTRACTION_PROMPT}"},
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": image_base64,
                    }
                }
            ]
        }
    ]
    
    try:
        response = model.generate_content(message)
        response_text = response.text.strip()
        print(f"  Raw response: {response_text}")
        
        json_data = extract_json_from_response(response_text)
        print(f"  Parsed JSON: {json_data}")
        
        extraction = FinancialStatementExtraction(**json_data)
        return extraction
        
    except json.JSONDecodeError as e:
        print(f"  Failed to parse JSON: {e}")
        return None
    except Exception as e:
        print(f"  Extraction error: {e}")
        return None


def extract_from_pdf(pdf_path: str, page_numbers: Optional[list] = None) -> Optional[FinancialStatementExtraction]:
    """Extract financial statement data from PDF."""
    config = ExtractorConfig()
    
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    if page_numbers is None:
        page_numbers = [0, 1, 2, 3, 4, 5]  # Try first 6 pages
    
    for page_num in page_numbers:
        print(f"Extracting from page {page_num + 1}...")
        
        image_bytes = render_pdf_page_to_image(pdf_path, page_num)
        extraction = extract_from_image(image_bytes, config)
        
        if extraction and extraction.total_assets:
            print(f"✓ Successfully extracted from page {page_num + 1}")
            return extraction
    
    print("✗ Failed to extract from any page")
    return None


if __name__ == "__main__":
    test_pdf = "data/raw/Q1_2022_ARCI.pdf"
    result = extract_from_pdf(test_pdf)
    if result:
        print("\nExtracted data:")
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print("Extraction failed")
