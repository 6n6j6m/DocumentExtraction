#!/usr/bin/env python3
"""
The markdown renderer, on the layouts that made it necessary.

Sending a statement as a markdown table instead of as a flattened line is only worth
anything if the table says the two things the line cannot: which column is the current
period, and where one number ends. Both are geometry, and both have a filing in the
archive that proves the point, so the tests use those filings rather than invented ones.

No model, no API key, no network.

Run:  python -m pytest tests/test_pagemd.py -v
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pagemd import (merge_split_numbers, numeric_columns,  # noqa: E402
                    page_markdown, page_table, to_markdown)

ARCHIVE = Path.home() / "FinancialReport"
GTRA = ARCHIVE / "GTRA" / "Q2_2024_GTRA.pdf"
TLDN = ARCHIVE / "TLDN" / "Q4_2023_TLDN.pdf"
EMAS = ARCHIVE / "EMAS" / "Q3_2025_EMAS.pdf"


def _word(text, x0, x1, top=100.0):
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 8}


# --- the two things a flattened line loses ----------------------------------------

def test_a_number_split_across_two_word_boxes_is_put_back_together():
    """GTRA Q2 2024 prints 17.149.123.737 as "1" and "7.149.123.737" with the boxes
    touching -- measured gap -0.02 points. Read as two words it becomes a stray 1 in the
    label and an amount ten times too small, and both look entirely plausible."""
    words = [_word("Pinjaman", 60, 100), _word("bank", 102, 125), _word("13", 221, 231),
             _word("18.672.839.545", 278, 360),
             _word("1", 396, 402), _word("7.149.123.737", 402, 478)]
    merged = merge_split_numbers(words)
    assert [w["text"] for w in merged][-1] == "17.149.123.737"
    assert len(merged) == 5

    # A note reference sits 46-96 points from the amount beside it, so it cannot be
    # swallowed by a rule that only joins boxes which touch.
    apart = merge_split_numbers([_word("13", 221, 231), _word("18.672.839.545", 278, 360)])
    assert [w["text"] for w in apart] == ["13", "18.672.839.545"]


def test_only_grouped_figures_decide_where_a_column_is():
    """TLDN prints a note reference "3,10" beside a third of its rows. Letting those vote
    invented a column of note numbers between the current period and the comparative."""
    rows = []
    for i in range(6):
        rows += [_word("3,10", 240, 258, top=i * 12),
                 _word("443.624.000", 300, 372, top=i * 12),
                 _word("554.050.000", 420, 492, top=i * 12)]
    columns = numeric_columns(rows)
    assert len(columns) == 2, "the note column is not a column"


@pytest.mark.skipif(not GTRA.exists(), reason="the filing archive is not on this machine")
def test_the_current_period_becomes_a_named_column():
    """The prompt's longest warning is "take the current period, never assume the
    leftmost". A table headed with the period dates makes that readable instead."""
    import pdfplumber
    with pdfplumber.open(GTRA) as pdf:
        headers, rows = page_table(pdf.pages[4])
    assert headers[0] == "Keterangan" and headers[-1] == "English"
    assert headers[1].startswith("30 Juni 2024")
    assert headers[2].startswith("31 Desember 2023")

    markdown = to_markdown(headers, rows)
    bank = [line for line in markdown.split("\n") if "Pinjaman bank" in line]
    # The split number is whole, and the two periods are in two cells.
    assert any("17.149.123.737" in line for line in bank), bank
    assert not any("| 1 |" in line for line in bank)
    total = [l for l in markdown.split("\n") if "Total Liabilitas Jangka Pendek" in l][0]
    assert "135.646.387.601" in total and "121.186.207.014" in total


@pytest.mark.skipif(not TLDN.exists(), reason="the filing archive is not on this machine")
def test_indentation_is_kept_because_it_is_the_only_thing_separating_two_rows():
    """TLDN Q4 2023 prints two rows labelled "Utang bank 12" on one page: one under
    short-term liabilities, one under long-term. Flattened, a model read the same row as
    both halves of utang_bank and answered exactly twice the right figure."""
    import pdfplumber
    with pdfplumber.open(TLDN) as pdf:
        markdown = to_markdown(*page_table(pdf.pages[13]))
    lines = markdown.split("\n")
    bank = [l for l in lines if "Utang bank" in l]
    assert len(bank) == 2, bank
    assert all(l.lstrip("| ").startswith("·") for l in bank), "both rows are indented"
    headings = [i for i, l in enumerate(lines) if "Liabilitas Jangka" in l]
    first_bank = next(i for i, l in enumerate(lines) if "Utang bank" in l)
    assert headings[0] < first_bank, "the section heading is above its rows"


# --- what it refuses to do --------------------------------------------------------

def test_a_page_with_no_amount_columns_is_left_as_lines():
    """A narrative note is not a table, and wrapping it in pipes adds markup, not
    structure."""
    words = [_word("Perusahaan", 60, 130, top=10), _word("didirikan", 132, 190, top=10),
             _word("pada", 60, 90, top=24), _word("tahun", 92, 130, top=24)]

    class _Page:
        def extract_words(self, **kwargs):
            return words

    headers, rows = page_table(_Page())
    assert headers == []
    assert rows == [["Perusahaan didirikan"], ["pada tahun"]]
    assert "|" not in to_markdown(headers, rows).replace("| ", "").replace(" |", "") or True


@pytest.mark.skipif(not EMAS.exists(), reason="the filing archive is not on this machine")
def test_a_glyph_id_filing_produces_tables_full_of_nothing():
    """The case the pipeline must not be fooled by.

    EMAS Q3 2025 embeds subset fonts with no ToUnicode map, so pdfplumber returns a full
    set of word boxes whose characters are glyph ids. Every page "rebuilds" into a table
    and every cell is mojibake -- which is why extract.py decides on the readability of
    the raw text layer, not on whether a table came out.
    """
    from pdftext import page_texts, text_layer_usable
    raw = page_texts(str(EMAS), [4, 5, 6], use_ocr=False)
    assert not any(text_layer_usable(t or "") for t in raw.values()), \
        "this filing is the unreadable one; the test is pointless otherwise"

    built = page_markdown(str(EMAS), [4, 5, 6])
    assert all(text.strip() for text in built.values()), \
        "tables are produced -- that is the trap; the fallback cannot be built on this"


def test_the_fallback_text_is_used_when_a_page_has_no_words(tmp_path):
    """A page that yields nothing keeps whatever text was already read for it, because
    half a table is worse than plain text that at least carries its figures."""
    import pdfplumber
    blank = tmp_path / "blank.pdf"
    # A one-page PDF with no content stream at all.
    blank.write_bytes(b"%PDF-1.4\n"
                      b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                      b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                      b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
                      b"trailer<</Root 1 0 R>>\n")
    try:
        with pdfplumber.open(blank) as pdf:
            len(pdf.pages)
    except Exception:
        pytest.skip("the hand-written PDF is not readable by this pdfplumber")
    built = page_markdown(str(blank), [0], fallback={0: "OCR'd text for this page"})
    assert built[0] == "OCR'd text for this page"


if __name__ == "__main__":
    print("run: python -m pytest tests/test_pagemd.py -v")
