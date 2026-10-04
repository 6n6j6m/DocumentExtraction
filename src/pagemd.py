#!/usr/bin/env python3
"""
A statement page as a markdown table, rebuilt from where the ink actually is.

The text layer these filings carry flattens a row into one string, and loses the two
things a reader needs most:

    Pinjaman bank 13 18.672.839.545 1 7.149.123.737 Bank loans

WHICH COLUMN IS THE CURRENT PERIOD is nowhere in that line -- the model has to infer
that the first amount is, which the prompt spends a paragraph on and which is still the
most common error in the archive. And WHERE ONE NUMBER ENDS: "1 7.149.123.737" is
17.149.123.737, split because the PDF puts a space inside the number.

Both are recoverable from geometry, not from language:

**Amounts are right-aligned.** Every figure in one column shares a right edge to within
a point or two, so the page's columns can be found once and every row assigned to them.
The first numeric column is then the current period on every row, stated rather than
inferred.

**A split number's boxes touch.** Measured on GTRA Q2 2024: the gap between "1" and
"7.149.123.737" is -0.02 points, while a note reference sits 46-96 points from the amount
beside it and two adjacent columns are 32 points apart. Merging on a sub-point gap cannot
swallow a note number; nothing else in these layouts is that close.

This is the same insight `numfmt.repair_digit_gaps` applies to strings, done one level
earlier where the word boxes still say what belongs together.
"""

import re
from statistics import median
from typing import Optional

LINE_TOLERANCE = 2.5       # points; words within this vertical distance are one row
EDGE_TOLERANCE = 6.0       # points; amounts whose right edges are this close share a column
MIN_COLUMN_MEMBERS = 4     # a column needs this many amounts before it is a column
TOUCHING = 0.6             # points; a gap this small is a split number, not a space
LABEL_MARGIN = 60          # amounts are at most this wide, so a label ends this far left
INDENT_STEP = 9.0          # points of indentation that count as one level of nesting
MIN_CELLS_PER_COLUMN = 3   # a column with fewer filled cells than this is not a column

_AMOUNT = re.compile(r"^\(?-?[\d.,]{3,}\)?$")
_DIGITS = re.compile(r"\d")
_LEADING_GROUP = re.compile(r"^\d{1,3}$")
_GROUPED = re.compile(r"^\(?-?\d{1,3}(?:[.,]\d{3})+\)?$")
_MONTHS = re.compile(r"Jan|Feb|Mar|Apr|Mei|May|Jun|Jul|Agu|Aug|Sep|Okt|Oct|Nov|Des|Dec", re.I)


def _is_amount(text: str) -> bool:
    return bool(_AMOUNT.match(text) and _DIGITS.search(text))


def merge_split_numbers(words: list) -> list:
    """Join word boxes that touch and together form one grouped number.

    The PDF writes 17.149.123.737 as "1" and "7.149.123.737" with no gap between the
    boxes. Read as two words it becomes a stray 1 in the label column and an amount an
    order of magnitude too small -- and both look entirely plausible downstream.
    """
    merged = []
    for word in words:
        if merged:
            previous = merged[-1]
            gap = word["x0"] - previous["x1"]
            joined = previous["text"] + word["text"]
            if (abs(gap) <= TOUCHING and _LEADING_GROUP.match(previous["text"])
                    and _GROUPED.match(word["text"]) and _GROUPED.match(joined)):
                merged[-1] = {**previous, "text": joined, "x1": word["x1"]}
                continue
        merged.append(dict(word))
    return merged


def _lines(words: list) -> list:
    grouped = {}
    for word in words:
        grouped.setdefault(round(word["top"] / LINE_TOLERANCE), []).append(word)
    return [sorted(grouped[key], key=lambda w: w["x0"]) for key in sorted(grouped)]


def numeric_columns(words: list) -> list:
    """The right edge of each amount column, left to right.

    Only fully grouped figures ("443.624.000") vote on where a column is. A note
    reference reads as a number -- TLDN prints "3,10" beside a third of its rows -- and
    letting those vote invented a column of note numbers sitting between the current
    period and the comparative one.
    """
    clusters = []
    for edge in sorted(w["x1"] for w in words if _GROUPED.match(w["text"])):
        if clusters and edge - clusters[-1][-1] <= EDGE_TOLERANCE:
            clusters[-1].append(edge)
        else:
            clusters.append([edge])
    return [median(c) for c in clusters if len(c) >= MIN_COLUMN_MEMBERS]


def _column_headers(lines: list, columns: list) -> list:
    """Name the columns from the page's own date header, when it prints one.

    A column headed "30 Juni 2024" needs no rule about which column is current, and the
    prompt's longest warning -- take the current period, verify the header, never assume
    the leftmost -- becomes a thing the model can read instead of a thing it must infer.
    """
    for line in lines[:14]:
        text = " ".join(w["text"] for w in line)
        if not _MONTHS.search(text):
            continue
        dates = [part.strip(" /") for part in re.split(r"\s{2,}|/", text)
                 if re.search(r"\d{4}", part) and _MONTHS.search(part)]
        if len(dates) >= len(columns):
            return dates[:len(columns)]
    return [f"kolom {i + 1}" for i in range(len(columns))]


def _indent(x0: float, left_edge: float) -> str:
    """Indentation, kept because in these statements it IS the section.

    TLDN Q4 2023 prints two rows labelled "Utang bank 12" on the same page: one under
    short-term liabilities, one under long-term. Nothing in the words tells them apart --
    only how far right the label starts. Flattened to plain text, a model read the same
    row as both halves of `utang_bank` and returned exactly twice the right answer.
    """
    depth = int(max(0.0, x0 - left_edge) // INDENT_STEP)
    return "· " * min(depth, 6)


def page_table(page) -> tuple:
    """(headers, rows) for one pdfplumber page."""
    words = merge_split_numbers(page.extract_words(keep_blank_chars=False))
    if not words:
        return [], []
    lines = _lines(words)
    columns = numeric_columns(words)
    if not columns:
        # A page with no amount columns -- a narrative note, a cover. Left as lines: a
        # one-column "table" would add markup and no structure.
        return [], [[" ".join(w["text"] for w in line)] for line in lines]

    label_left = min((w["x0"] for line in lines for w in line
                      if not _is_amount(w["text"])), default=0.0)
    rows = []
    for line in lines:
        label, cells, trailing = [], [""] * len(columns), []
        for word in line:
            if _is_amount(word["text"]):
                distances = [abs(word["x1"] - edge) for edge in columns]
                nearest = distances.index(min(distances))
                if min(distances) <= EDGE_TOLERANCE * 3:
                    cells[nearest] = (cells[nearest] + " " + word["text"]).strip()
                    continue
            if word["x0"] > max(columns):
                trailing.append(word["text"])
            else:
                label.append(word)
        text = _indent(label[0]["x0"], label_left) + " ".join(w["text"] for w in label) \
            if label else ""
        rows.append([text] + cells + [" ".join(trailing)])

    # A column that almost nothing landed in was never a column: a run of note numbers
    # or a stray right-aligned figure can look like one, and an empty column in the
    # middle of a table invites the reader to wonder what belongs in it.
    keep = [i for i in range(len(columns))
            if sum(1 for row in rows if row[i + 1].strip()) >= MIN_CELLS_PER_COLUMN]
    if keep and len(keep) != len(columns):
        columns = [columns[i] for i in keep]
        rows = [[row[0]] + [row[i + 1] for i in keep] + [row[-1]] for row in rows]

    return ["Keterangan"] + _column_headers(lines, columns) + ["English"], rows


def to_markdown(headers: list, rows: list) -> str:
    """A markdown table. Empty rows are dropped; pipes in text are escaped."""
    if not rows:
        return ""
    width = len(headers) if headers else max(len(row) for row in rows)
    out = []
    if headers:
        out.append("| " + " | ".join(headers) + " |")
        out.append("|" + "---|" * width)
    for row in rows:
        padded = (list(row) + [""] * width)[:width]
        if not any(cell.strip() for cell in padded):
            continue
        out.append("| " + " | ".join(cell.replace("|", "\\|") for cell in padded) + " |")
    return "\n".join(out)


def page_markdown(pdf_path: str, page_numbers=None, fallback: Optional[dict] = None) -> dict:
    """{page_number: markdown} for the requested pages.

    A page whose text layer is unreadable -- a scan, or subset fonts with no ToUnicode
    map -- has no word boxes to build geometry from. Those pages fall back to whatever
    text was already read for them (OCR, usually), because half a table is worse than
    a page of plain text that at least carries its figures.
    """
    import pdfplumber

    out = {}
    with pdfplumber.open(pdf_path) as pdf:
        wanted = (range(len(pdf.pages)) if page_numbers is None
                  else [n for n in page_numbers if 0 <= n < len(pdf.pages)])
        for n in wanted:
            try:
                headers, rows = page_table(pdf.pages[n])
                markdown = to_markdown(headers, rows)
            except Exception:
                markdown = ""
            if not markdown.strip() and fallback:
                markdown = fallback.get(n, "") or ""
            out[n] = markdown
    return out
