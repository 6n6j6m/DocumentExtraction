"""
Normalisation: turn as-printed statement figures into full Rupiah.

Two things stand between a printed figure and a comparable number:

1. SCALE. Filings print "(dalam ribuan Rupiah)", "(dalam jutaan Rupiah)" or
   nothing at all (full units). ARCI prints full units; many IDR filers print
   thousands. The scale multiplies every monetary figure.

2. CURRENCY. ARCI keeps its books in USD (approved by the Ministry of Finance,
   see note 2 of any ARCI filing), so its figures must be converted to IDR to
   sit beside an IDR filer like TLDN.

The exchange rate is taken FROM THE FILING ITSELF rather than an external
source, because the filing discloses the rate it used:

    "Pada tanggal 31 Maret 2022 ... nilai tukar yang digunakan untuk AS$1 adalah:
     1.000 Rupiah   0,0697"

That line reads "1,000 Rupiah = US$0.0697", so IDR per USD = 1000 / 0.0697.
Using the filing's own rate keeps the conversion consistent with the numbers
being converted, and makes it auditable: every result carries the quote it
came from.
"""

import re
from dataclasses import dataclass
from typing import Optional

# Monetary fields only. total_share is a COUNT of shares and must never
# be scaled or converted; dates/currency/scope are not numbers.
MONETARY_FIELDS = [
    "aset", "total_aset_lancar", "kas",
    "liabilitas", "utang_bank", "ekuitas",
    "pendapatan", "laba_bersih", "kas_dari_aktivitas_operasi",
]

SCALE_MULTIPLIER = {
    "FULL": 1,
    "THOUSANDS": 1_000,
    "MILLIONS": 1_000_000,
    "BILLIONS": 1_000_000_000,
}

# "1.000 Rupiah 0,0697 0,0701 0,0686" -> first number is the current period.
# We match this row DIRECTLY rather than first locating the page by its heading
# ("nilai tukar yang digunakan untuk AS$1 adalah"): the filings are printed in two
# columns, Indonesian beside English, so once the page text is flattened that
# heading is split by the English column and any adjacency-based match fails.
# The row itself is distinctive enough to find on its own.
_RATE_ROW = re.compile(r"1[.,]?000\s+Rupiah\s+([0-9]+,[0-9]+)")
# Fallback: a disclosed pair such as "Rp10.880.000.000 (US$758,241)"
_PAIR = re.compile(r"Rp\s?([\d.]{9,})\s*\(?\s*US\$\s?([\d,]+)")


@dataclass
class FxRate:
    """An IDR-per-USD rate plus where it came from."""
    idr_per_usd: float
    source: str          # "disclosed_rate_table" | "derived_from_pair"
    page: int            # 1-indexed
    evidence: str


def _num(s: str) -> float:
    """Parse an Indonesian-formatted number: dot=thousands, comma=decimal."""
    return float(s.replace(".", "").replace(",", "."))


def extract_fx_rate(pdf_path: str) -> Optional[FxRate]:
    """Read the USD/IDR rate the filing says it used.

    Strategy 1: the disclosed rate table row ("1.000 Rupiah  0,0697").
    Strategy 2: a disclosed Rp / US$ pair elsewhere in the notes.

    Returns None when neither is present, rather than guessing a rate.
    """
    import pdfplumber

    pair_fallback = None
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""

            for line in text.split("\n"):
                m = _RATE_ROW.search(line)
                if m:
                    usd_per_1000_idr = _num(m.group(1))
                    if usd_per_1000_idr > 0:
                        return FxRate(
                            idr_per_usd=1000 / usd_per_1000_idr,
                            source="disclosed_rate_table",
                            page=i + 1,
                            evidence=line.strip(),
                        )

            if pair_fallback is None:
                for m in _PAIR.finditer(text.replace("\n", " ")):
                    rp = _num(m.group(1))
                    usd = float(m.group(2).replace(",", ""))
                    if usd > 0 and 8_000 < rp / usd < 25_000:
                        pair_fallback = FxRate(
                            idr_per_usd=rp / usd,
                            source="derived_from_pair",
                            page=i + 1,
                            evidence=m.group(0).strip(),
                        )
                        break

    return pair_fallback


def to_idr(extraction, fx: Optional[FxRate] = None, pdf_path: Optional[str] = None) -> dict:
    """Convert an extraction's monetary fields to full Rupiah.

    Args:
        extraction: FinancialStatementExtraction (values as printed)
        fx: rate to use. If None and the statement is in USD, it is read from pdf_path.
        pdf_path: filing to read the rate from, when fx is not supplied.

    Returns:
        {"values": {field: int_idr_or_None},
         "currency": "IDR",
         "scale_applied": int,
         "fx": FxRate or None,
         "warnings": [str]}

    Raises:
        ValueError: statement is in USD but no rate could be found. Better to stop
                    than to emit rupiah figures produced by a guessed rate.
    """
    warnings = []

    scale_name = (getattr(extraction, "reporting_scale", None) or "FULL").upper()
    if scale_name not in SCALE_MULTIPLIER:
        warnings.append(f"Unknown reporting_scale {scale_name!r}, assuming FULL")
        scale_name = "FULL"
    scale = SCALE_MULTIPLIER[scale_name]

    currency = (extraction.currency or "").upper()
    if currency not in ("IDR", "USD"):
        warnings.append(f"Unknown currency {currency!r}, assuming IDR (no conversion)")
        currency = "IDR"

    if currency == "USD":
        if fx is None:
            if pdf_path is None:
                raise ValueError("Statement is in USD but no fx rate and no pdf_path given")
            fx = extract_fx_rate(pdf_path)
        if fx is None:
            raise ValueError(
                f"Statement is in USD but no exchange rate is disclosed in {pdf_path}. "
                "Refusing to convert with a guessed rate."
            )
        if fx.source == "derived_from_pair":
            warnings.append(
                f"Rate derived from a disclosed Rp/US$ pair (p{fx.page}), not from the "
                "rate table; may be off by a rounding-level amount."
            )
        rate = fx.idr_per_usd
    else:
        fx = None
        rate = 1.0

    values = {}
    for field in MONETARY_FIELDS:
        raw = getattr(extraction, field, None)
        values[field] = None if raw in (None, "") else round(float(raw) * scale * rate)

    # Carried through unconverted, on purpose.
    values["total_share"] = getattr(extraction, "total_share", None)
    values["period_end_date"] = getattr(extraction, "period_end_date", None)

    return {
        "values": values,
        "currency": "IDR",
        "scale_applied": scale,
        "fx": fx,
        "warnings": warnings,
    }
