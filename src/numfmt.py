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
