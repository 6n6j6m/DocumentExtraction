"""
One way to get the text of a filing, whatever state its text layer is in.

Three subsystems read the PDF's characters independently -- page selection, the
exchange-rate reader, and the grounding check -- and each of them used to call
pdfplumber directly. That was fine while every filing carried a clean text layer.
It stops being fine the moment one does not, because the three fail in three
different ways and none of them says why:

    page selection      finds no statement titles, silently falls back to page 1-10
    extract_fx_rate     finds no rate, raises "no exchange rate is disclosed"
    grounding           verifies nothing, so every figure looks unprintable

PT Merdeka Gold Resources (EMAS) Q3 2025 is such a filing: it embeds subset fonts
with no ToUnicode CMap, so pdfplumber returns raw glyph ids -- 100% of its
characters land in the Unicode Private Use Area. The page is perfectly legible to a
human and to a VLM; only the character stream is gibberish. The failure the user
sees is the FX one, which blames the document for something the document does state.

So the decision "is this text real?" is made in one place, and a page that fails it
is OCR'd instead. OCR results are cached on disk because a 97-page filing costs
around two minutes to OCR and nothing afterwards.
"""

import json
import os
import re
from pathlib import Path

# A glyph-id text layer lands in the Private Use Area. Real Indonesian and English
# text never does. The threshold is deliberately low: even a fifth of a page coming
# back as glyph ids means the mapping is broken, not that the page uses symbols.
PUA_RATIO_UNUSABLE = 0.20

# Below this, a page carries no usable text regardless of encoding -- a scan, or a
# near-empty separator page.
MIN_USABLE_CHARS = 200

_LETTER = re.compile(r"[A-Za-z]")


def _pua_ratio(text: str) -> float:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if 0xE000 <= ord(c) <= 0xF8FF) / len(chars)


def text_layer_usable(text: str) -> bool:
    """Is this page's extracted text actually readable text?

    False for three distinct situations that all mean "ask the pixels instead":
    an empty or near-empty layer, a layer of Private Use Area glyph ids, and a
    layer with no letters in it at all.
    """
    if not text or len(text.strip()) < MIN_USABLE_CHARS:
        return False
    if _pua_ratio(text) >= PUA_RATIO_UNUSABLE:
        return False
    return bool(_LETTER.search(text))


def _cache_path(pdf_path: str, kind: str = "full") -> Path:
    root = Path(__file__).resolve().parent.parent
    suffix = "" if kind == "full" else f".{kind}"
    return root / "output" / "ocr_cache" / f"{Path(pdf_path).stem}{suffix}.json"


# Page SELECTION only needs to know what a page IS, and that is written at the top of
# it: the statement title, the entity name, the currency and scale header. Everything
# below is detail that selection never reads.
#
# That distinction is worth a lot on a scanned filing. Reading every page in full to
# find the eight that matter cost three minutes on a 97-page filing whose text layer is
# glyph ids -- almost all of it spent OCR'ing pages at full resolution that were then
# thrown away. Rendering only the top third, at 120 dpi instead of 300, cuts the pixels
# by roughly twenty times, and the title is large type that survives the lower
# resolution easily.
TITLE_FRACTION = 0.35     # of page height; the title block never reaches this far down
TITLE_DPI = 120


def _ocr_title(pdf_path: str, page_number: int) -> str:
    """OCR just the head of a page -- enough to identify it, far cheaper than the page."""
    from extract import render_pdf_page_to_image
    import io
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(
        render_pdf_page_to_image(pdf_path, page_number, dpi=TITLE_DPI)))
    head = image.crop((0, 0, image.width, int(image.height * TITLE_FRACTION)))
    return pytesseract.image_to_string(head, lang="ind+eng")


def page_titles(pdf_path: str) -> dict:
    """{page_number: text from the top of the page}, for identifying pages cheaply.

    Uses the text layer wherever it is readable -- which costs nothing and is the case
    for most filings -- and falls back to a cropped, low-resolution OCR only for the
    pages that are unreadable. Callers should treat the result as a title region, not
    as the page: it is deliberately incomplete.
    """
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        texts = {n: (page.extract_text() or "") for n, page in enumerate(pdf.pages)}

    unreadable = [n for n, t in texts.items() if not text_layer_usable(t)]
    if not unreadable:
        return texts

    try:
        import pytesseract  # noqa: F401
    except ImportError:
        print(f"  ⚠ {len(unreadable)} page(s) unreadable and OCR is not installed; "
              f"page selection will fall back to the first pages")
        return texts

    cache_file = _cache_path(pdf_path, "titles")
    cache = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text())
        except ValueError:
            cache = {}

    missing = [n for n in unreadable if str(n) not in cache]
    if missing:
        print(f"  text layer unreadable on {len(unreadable)} page(s); reading titles "
              f"only ({len(missing)} to OCR, {len(unreadable) - len(missing)} cached)")
    for n in unreadable:
        key = str(n)
        if key not in cache:
            try:
                cache[key] = _ocr_title(pdf_path, n)
            except Exception as exc:
                print(f"    ✗ title OCR page {n+1}: {exc}")
                continue
        texts[n] = cache[key]

    if missing:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))
    return texts


def _ocr_page(pdf_path: str, page_number: int, dpi: int) -> str:
    from extract import render_pdf_page_to_image
    import io
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(render_pdf_page_to_image(pdf_path, page_number, dpi=dpi)))
    # The filings are bilingual, so both language packs are requested.
    return pytesseract.image_to_string(image, lang="ind+eng")


def page_texts(pdf_path: str, pages=None, use_ocr: bool = True) -> dict:
    """{page_number: text} for the requested pages, OCR'd where the layer is broken.

    Args:
        pdf_path: the filing.
        pages: 0-indexed page numbers, or None for every page.
        use_ocr: set False to see the raw text layer, unrepaired.
    """
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        wanted = list(range(total)) if pages is None else [p for p in pages if 0 <= p < total]
        texts = {n: (pdf.pages[n].extract_text() or "") for n in wanted}

    broken = [n for n, t in texts.items() if not text_layer_usable(t) and t.strip()]
    empty = [n for n, t in texts.items() if not t.strip()]
    if not use_ocr or not (broken or empty):
        return texts

    # Only pages that are actually unreadable are OCR'd. A filing with one rotated
    # page pays for one page, not for the document.
    todo = sorted(set(broken) | set(empty))
    cache_file = _cache_path(pdf_path)
    cache = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text())
        except ValueError:
            cache = {}

    try:
        import pytesseract  # noqa: F401
    except ImportError:
        print(f"  ⚠ {len(todo)} page(s) have an unreadable text layer and OCR is not "
              f"installed (pip install pytesseract, brew install tesseract). "
              f"Page selection, grounding and the FX rate will all be degraded.")
        return texts

    # 300, not 200. At 200 dpi tesseract read EMAS's current-period exchange rate
    # column as "S2" while the comparative column beside it came out cleanly -- which
    # would have produced a plausible rate from the WRONG period. Costs about a second
    # a page more, once, and the result is cached.
    dpi = int(os.getenv("OCR_DPI", "300"))
    missing = [n for n in todo if str(n) not in cache]
    if missing:
        print(f"  text layer unreadable on {len(todo)} page(s); OCR on {len(missing)} "
              f"(cached: {len(todo) - len(missing)})")
    for n in todo:
        key = str(n)
        if key not in cache:
            try:
                cache[key] = _ocr_page(pdf_path, n, dpi)
            except Exception as exc:
                print(f"    ✗ OCR page {n+1}: {exc}")
                continue
        texts[n] = cache[key]

    if missing:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))
    return texts
