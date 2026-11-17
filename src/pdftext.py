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
_DIGIT_RUN = re.compile(r"\d+")

# A third way a text layer breaks, and the one that hides best. Some filings are
# typeset so that every glyph is its own positioned text run; pdfplumber then returns
# the page one character at a time, with the columns interleaved:
#
#     T o ta l A s e t L a n c a r        20 .4 0 9 .3 0 1 .3
#
# Every check downstream reads that as a page that simply does not contain the
# figures. It has letters, no Private Use Area glyphs and thousands of characters, so
# the two tests above pass it -- and then grounding fails on every value, the FX
# reader finds no rate, and the bank-debt position check finds no rows. PT Grahaprima
# (GTRA) files this way in Q1 2024, Q1 2025 and Q1 2026 while the other quarters of
# the same issuer come out clean, which is why the same document read twice a year
# apart behaves differently.
#
# Two conditions together, because either alone has honest counter-examples. A note
# page listing many one-character bullets scores high on the first; a page of dates
# and note references scores high on the second. A page where MOST tokens are single
# characters AND most numbers have been reduced to lone digits is not prose.
SHREDDED_SINGLE_CHAR_TOKENS = 0.50
SHREDDED_LONE_DIGIT_RUNS = 0.75
_SHRED_MIN_TOKENS = 40
_SHRED_MIN_NUMBERS = 30


def _pua_ratio(text: str) -> float:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if 0xE000 <= ord(c) <= 0xF8FF) / len(chars)


def text_layer_shredded(text: str) -> bool:
    """True when the layer came out one character at a time.

    Needs enough of a page to judge: on a short page the two ratios swing on a
    handful of tokens, and a sparse page is not worth OCR'ing anyway.
    """
    tokens = text.split()
    runs = _DIGIT_RUN.findall(text)
    if len(tokens) < _SHRED_MIN_TOKENS or len(runs) < _SHRED_MIN_NUMBERS:
        return False
    single = sum(1 for t in tokens if len(t) == 1) / len(tokens)
    lone = sum(1 for r in runs if len(r) == 1) / len(runs)
    return single >= SHREDDED_SINGLE_CHAR_TOKENS and lone >= SHREDDED_LONE_DIGIT_RUNS


def text_layer_usable(text: str) -> bool:
    """Is this page's extracted text actually readable text?

    False for four distinct situations that all mean "ask the pixels instead":
    an empty or near-empty layer, a layer of Private Use Area glyph ids, a layer
    with no letters in it at all, and a layer shredded into single characters.
    """
    if not text or len(text.strip()) < MIN_USABLE_CHARS:
        return False
    if _pua_ratio(text) >= PUA_RATIO_UNUSABLE:
        return False
    if not _LETTER.search(text):
        return False
    return not text_layer_shredded(text)


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


# Two OCR readings of every OCR'd page, not one. The primary is the reading this repo
# has always used (300 dpi, tesseract's default layout analysis) and is what a model
# is shown. The alternate -- 400 dpi, --psm 6, one uniform block -- is used only to
# VERIFY figures. Measured on the replay of all 290 filings: switching to the alternate
# outright fixed six TOTL figures tesseract had misread at 300 dpi (2.428.785.813 read
# as 2.428.185.813, separators dropped in 847.433.444 and 1.793.562.796) and broke
# eight others it had read right. No single setting wins; a figure printed in either
# reading is printed.
OCR_PRIMARY = (300, None)
OCR_ALTERNATE = (400, 6)


class OCRText(str):
    """Page text from OCR, carrying the alternate reading for verification only."""
    alternate = ""


def _ocr_page(pdf_path: str, page_number: int, dpi: int, psm=None) -> str:
    from extract import render_pdf_page_to_image
    import io
    import pytesseract
    from PIL import Image, ImageOps

    image = Image.open(io.BytesIO(render_pdf_page_to_image(pdf_path, page_number, dpi=dpi)))
    # The filings are bilingual, so both language packs are requested.
    if psm is None:
        return pytesseract.image_to_string(image, lang="ind+eng")
    return pytesseract.image_to_string(ImageOps.grayscale(image), lang="ind+eng",
                                       config=f"--psm {psm}")


def _ocr_cached(pdf_path: str, pages: list, dpi: int, psm, kind: str) -> dict:
    """{page: text} for one OCR setting, from and into its own cache file."""
    cache_file = _cache_path(pdf_path, kind)
    cache = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text())
        except ValueError:
            cache = {}
    missing = [n for n in pages if str(n) not in cache]
    for n in missing:
        try:
            cache[str(n)] = _ocr_page(pdf_path, n, dpi, psm)
        except Exception as exc:
            print(f"    ✗ OCR page {n+1}: {exc}")
    if missing:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache))
    return {n: cache[str(n)] for n in pages if str(n) in cache}


# Two more ways a page passes text_layer_usable while its figures are not in the layer,
# both found by tracing the PURA/RCCC/TRIN/TRUK evaluation back to its pages:
#
#   * The title, header and footnote are real text, but the TABLE is a scanned image
#     pasted underneath. PURA Q4 2023 prints its whole balance sheet, income statement
#     and cash flow that way (pages 10-14): ~500 characters of header, zero figures.
#     Grounding read those pages, found none of the eleven figures the model had read
#     correctly from the image, and withheld all of them.
#   * Part of the page is typeset one glyph per run ("1 0 0 %", "1 5 ,2 8 %") while the
#     rest is normal. PURA Q2 2025's shareholder table (page 55) is 53% single-character
#     tokens, under the shredded threshold, so the selector never saw its 100% row and
#     total_share was never asked for.
#
# A page like that is OCR'd like any broken page. Set OCR_MIXED_PAGES=false to get the
# old behaviour back, which is how the change is measured.
MIXED_IMAGE_SHARE = 0.20      # of page area covered by images
MIXED_MAX_FIGURES = 2         # a statement page prints dozens; a scanned one prints none
SPACED_LINE_SINGLE = 0.60     # a line is "spaced" when this share of its tokens is 1 char
SPACED_LINE_SHARE = 0.25      # ...and a page is, when this share of its lines are
_FIGURE = re.compile(r"\d{1,3}(?:[.,]\d{3})+")


def text_layer_spaced(text: str) -> bool:
    """True when a quarter of the page's lines are typeset one character at a time."""
    rows = [line.split() for line in (text or "").split("\n")]
    rows = [row for row in rows if len(row) >= 6]
    if len(rows) < 4:
        return False
    spaced = sum(1 for row in rows
                 if sum(len(token) == 1 for token in row) / len(row) >= SPACED_LINE_SINGLE)
    return spaced / len(rows) >= SPACED_LINE_SHARE


def figures_behind_image(page, text: str) -> bool:
    """True when the page's figures are pixels: text with no figures, over an image."""
    if len(_FIGURE.findall(text or "")) > MIXED_MAX_FIGURES:
        return False
    area = float(page.width * page.height) or 1.0
    covered = 0.0
    for image in page.images or []:
        width = max(0.0, min(image["x1"], page.width) - max(image["x0"], 0))
        height = max(0.0, min(image["bottom"], page.height) - max(image["top"], 0))
        covered += width * height
    return covered / area >= MIXED_IMAGE_SHARE


def mixed_pages_enabled() -> bool:
    return os.getenv("OCR_MIXED_PAGES", "true").lower() in ("1", "true", "yes")


def page_needs_ocr(page, text: str) -> bool:
    """The one per-page decision: is this page's text layer the page's content?"""
    if not (text or "").strip() or not text_layer_usable(text):
        return True
    if not mixed_pages_enabled():
        return False
    return text_layer_spaced(text) or figures_behind_image(page, text)


SEPARATED_POINTS = 3.0     # a lone digit this far from the next figure is its own token
_LONE_DIGIT = re.compile(r"^\d$")
_FIGURE_WORD = re.compile(r"^\(?(?:\d{1,3}(?:[.,]\d{3})+|[.,]\d{3}(?:[.,]\d{3})*)\)?$")


def mark_separated_digits(page, text: str) -> str:
    """Write two spaces where a lone digit and the figure after it are separate tokens.

    The flattened text cannot tell "1 7.149.123.737" (GTRA: one figure, boxes touching)
    from "1 77.250.439" (TRIN Q3 2022: a stray digit 35 points before the figure) or
    "2,8&9 7.008.790.794" (TRUK: a note reference). The word boxes can, and the
    archive leaves no doubt: every such pair is either touching or more than 10 points
    apart. A double space keeps numfmt from joining what the page printed apart.
    """
    try:
        words = page.extract_words()
    except Exception:
        return text
    separated, touching = set(), set()
    for a, b in zip(words, words[1:]):
        if abs(a["top"] - b["top"]) > 2:
            continue
        lead = a["text"][-1:] if a["text"] else ""
        if not (lead.isdigit() and _FIGURE_WORD.match(b["text"])):
            continue
        if not (_LONE_DIGIT.match(a["text"]) or not a["text"][-2:-1].isdigit()):
            continue
        pair = f"{lead} {b['text']}"
        (separated if b["x0"] - a["x1"] > SEPARATED_POINTS else touching).add(pair)
    for pair in separated - touching:
        text = text.replace(pair, pair.replace(" ", "  ", 1))
    return text


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
        texts = {n: mark_separated_digits(pdf.pages[n], pdf.pages[n].extract_text() or "")
                 for n in wanted}
        mixed = [n for n, t in texts.items()
                 if t.strip() and text_layer_usable(t) and page_needs_ocr(pdf.pages[n], t)]

    broken = [n for n, t in texts.items() if not text_layer_usable(t) and t.strip()]
    broken += mixed
    empty = [n for n, t in texts.items() if not t.strip()]
    if not use_ocr or not (broken or empty):
        return texts

    # Only pages that are actually unreadable are OCR'd. A filing with one rotated
    # page pays for one page, not for the document.
    todo = sorted(set(broken) | set(empty))
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        print(f"  ⚠ {len(todo)} page(s) have an unreadable text layer and OCR is not "
              f"installed (pip install pytesseract, brew install tesseract). "
              f"Page selection, grounding and the FX rate will all be degraded.")
        return texts

    # 300 rather than 200 dpi was the first lesson: at 200 tesseract read EMAS's
    # current-period exchange rate column as "S2" while the comparative column beside
    # it came out cleanly. The primary reading keeps its cache name ("full"), so text
    # read before the alternate existed is still used rather than re-OCR'd.
    dpi = int(os.getenv("OCR_DPI", str(OCR_PRIMARY[0])))
    primary = _ocr_cached(pdf_path, todo, dpi, OCR_PRIMARY[1], "full")
    alternate = _ocr_cached(pdf_path, todo, OCR_ALTERNATE[0], OCR_ALTERNATE[1],
                            f"full-{OCR_ALTERNATE[0]}dpi-psm{OCR_ALTERNATE[1]}")
    for n in todo:
        if n in primary:
            text = OCRText(primary[n])
            text.alternate = alternate.get(n, "")
            texts[n] = text
    return texts

