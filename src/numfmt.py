"""
Reading a figure as a filing prints it, under either grouping convention.

IDX filers do not agree on separators. ARCI and JPFA print the Indonesian
convention -- dot groups thousands, comma is the decimal point ("694.671.337",
"15.000,50"). EMAS prints the English one throughout, because its Indonesian column
is typeset beside an English one ("80,322,232"). A parser tuned to either convention
silently mangles the other: read as Indonesian, "80,322,232" becomes unparseable;
read as English, "694.671" becomes 694.671 -- a thousandfold understatement that
still looks like a number.

The convention is therefore decided per value from its shape, which is unambiguous
in every case that matters, and only genuinely ambiguous for a single group of
exactly three digits ("1.234"), where thousands is assumed because a statement line
item is a whole currency amount far more often than a three-decimal fraction.
"""

import re

_US_GROUPED = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
_ID_GROUPED = re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$")
_ONE_GROUP = re.compile(r"^\d{1,3}[.,]\d{3}$")

# PDF text layers routinely break a printed figure across a space, in three shapes
# seen in real filings:
#
#   CPIN   "14.406"              extracts as "1 4.406"        digit | digit
#   GTRA   "1.092.421.914.566"   extracts as "1 .092.421..."  digit | separator
#   GTRA   "43.048.092.371"      extracts as "4 3.048.092.371"
#
# Anything reading figures out of a text layer -- the grounding check, the bank-debt
# position check -- has to close those gaps first or it reads a different number than
# the one printed, which is worse than reading none.
_DIGIT_GAP = re.compile(r"(?<=\d)[ \t]+(?=\d)"          # 1 4.406
                        r"|(?<=\d)[ \t]+(?=[.,]\d)"      # 1 .092
                        r"|(?<=[.,])[ \t]+(?=\d)")        # 1. 092


def repair_digit_gaps(text: str) -> str:
    """Rejoin figures a text layer split across a space.

    Adjacent columns may run together as a side effect ("26.340.959 25.149.999"
    becomes one long run). That is acceptable for substring searching, which is all
    this is used for, and it is repaired per line where the position matters.
    """
    return _DIGIT_GAP.sub("", text or "")


# Reading the COLUMNS of a row needs the opposite trade. Closing every gap turns
# "Pinjaman bank 14 17.729.771.107 17.744.025.136" -- a note reference and two
# periods -- into one 26-digit run that parses as nothing at all. So only the gap
# that a split figure leaves is closed: a lone digit standing at the start of a word,
# immediately before a properly grouped number, is that number's first digit.
_SPLIT_LEAD = re.compile(r"(?<!\d)(\d)[ \t]+(?=\d{1,3}[.,]\d{3}|[.,]\d{3})")

# A figure as a statement prints one: at least one group of three behind a separator.
# Anything shorter is a note reference or a year, not an amount.
_GROUPED = re.compile(r"\(?\d{1,3}(?:[.,]\d{3})+\)?")


def grouped_numbers(line: str) -> list:
    """Every printed amount on one line, in the order the columns appear.

    Used where the POSITION of a figure carries meaning -- which column, which row,
    under which heading -- and where joining two columns together would therefore
    read a number that is not on the page.
    """
    repaired = _SPLIT_LEAD.sub(r"\1", line or "")
    values = [parse_grouped_number(m.group()) for m in _GROUPED.finditer(repaired)]
    return [v for v in values if v is not None]



def parse_grouped_number(text):
    """Parse a printed figure to a float, or None if it is not one.

    Parentheses mean negative, as they do on every financial statement.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)

    raw = str(text).strip()
    if not raw:
        return None

    negative = raw.startswith("(") and raw.endswith(")")
    body = raw[1:-1].strip() if negative else raw
    body = body.replace(" ", " ").replace(" ", "")
    body = re.sub(r"^[+-]", lambda m: "" if m.group() == "+" else "-", body)
    if body.startswith("-"):
        negative = True
        body = body[1:]
    body = re.sub(r"[^\d.,]", "", body)
    if not body:
        return None

    if _US_GROUPED.match(body):
        body = body.replace(",", "")
    elif _ID_GROUPED.match(body):
        body = body.replace(".", "").replace(",", ".")
    elif _ONE_GROUP.match(body):
        # "1.234" / "1,234": one group of exactly three. Thousands, not a fraction.
        body = body.replace(".", "").replace(",", "")
    elif "," in body and "." in body:
        # Mixed and irregular: whichever separator comes last is the decimal point.
        decimal = "," if body.rfind(",") > body.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        body = body.replace(thousands, "").replace(decimal, ".")
    elif "," in body:
        body = body.replace(",", ".")      # a decimal comma
    # A lone dot is already a decimal point.

    try:
        value = float(body)
    except ValueError:
        return None
    return -value if negative else value
