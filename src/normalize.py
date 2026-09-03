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

# The rate row is matched DIRECTLY rather than by first locating the page from its
# heading ("nilai tukar yang digunakan untuk AS$1 adalah"): the filings print
# Indonesian beside English, so once the text is flattened that heading is split by
# the other column and any adjacency-based match fails.
#
# Issuers do not agree on how the row is written, and the differences all break a
# regex tuned to one of them:
#
#   ARCI  "1.000 Rupiah          0,0697 0,0701"   1,000 as the unit, decimal comma
#   EMAS  ".61 0.62 Indonesian Rupiah 10,000"     10,000 as the unit, decimal dot,
#                                                 numbers BEFORE the label, and the
#                                                 leading zero lost to OCR
#
# So the row is read in pieces instead: find the Rupiah unit, then read the plausible
# rate off the same line, and let the sanity band decide whether the result is a rate
# at all. That accepts either separator convention and survives an OCR'd page.
_RUPIAH_LINE = re.compile(r"rupiah", re.I)
_RATE_UNIT = re.compile(r"\b(1|10|100|1000)[.,]000\b")
# ".61", "0,0697", "16.393" -- a decimal with 2-6 places, not part of a longer number.
_RATE_VALUE = re.compile(r"(?<![\d.,])(\d*[.,]\d{2,6})(?![\d])")

# A rate outside this band is not an IDR/USD rate; it is a page number, a percentage
# or an OCR artefact. Used to accept or reject a candidate rather than to invent one.
RATE_MIN, RATE_MAX = 8_000, 25_000

# Fallback: a disclosed pair such as "Rp10.880.000.000 (US$758,241)"
_PAIR = re.compile(r"Rp\s?([\d.]{9,})\s*\(?\s*US\$\s?([\d,]+)")


@dataclass
class FxRate:
    """An IDR-per-USD rate plus where it came from."""
    idr_per_usd: float
    source: str          # "disclosed_rate_table" | "derived_from_pair"
    page: int            # 1-indexed
    evidence: str
    decimals: int = 4          # decimal places the filing quoted the rate to
    quoted_value: float = 0.0  # the figure as printed, e.g. 0.0697 or 0.61
    # Other plausible rates on the same row: the comparative-period columns. Kept so
    # the caller can say which was taken and what it was taken over.
    other_candidates: tuple = ()

    @property
    def rounding_error(self) -> float:
        """Relative uncertainty implied by the quoted precision.

        ARCI quotes 0,0697 for 1.000 Rupiah -- half a unit in the last decimal place
        is 0.07%. EMAS quotes 0.61 for 10.000 Rupiah, which is 0.8%: an order of
        magnitude coarser, and far wider than the 0.01% tolerance the evaluator uses.
        Carrying it stops a converted figure from being read as more precise than the
        rate it was produced with.
        """
        if not self.quoted_value or self.decimals <= 0:
            return 0.0
        return (0.5 * 10 ** -self.decimals) / self.quoted_value


def _num(s: str) -> float:
    """Parse an Indonesian-formatted number: dot=thousands, comma=decimal."""
    return float(s.replace(".", "").replace(",", "."))


def _decimal(token: str) -> tuple:
    """Read a quoted rate figure. Returns (value, decimal places).

    Accepts either separator convention, and a leading zero that OCR dropped:
    "0,0697" -> (0.0697, 4);  "0.61" -> (0.61, 2);  ".61" -> (0.61, 2).
    """
    normalised = token.replace(",", ".")
    if normalised.startswith("."):
        normalised = "0" + normalised
    value = float(normalised)
    places = len(normalised.split(".")[1]) if "." in normalised else 0
    return value, places


def _rate_from_line(line: str):
    """An IDR-per-USD rate quoted on this line, or None.

    The unit ("1.000 Rupiah", "Indonesian Rupiah 10,000") and the figure may appear
    in either order, so the unit is located and removed first and the figure is then
    read from what remains. Candidates are tried in printed order -- the current
    period is the first numeric column -- and the first one landing in the plausible
    band wins. Anything outside the band is not a rate, so nothing is guessed.
    """
    unit_match = _RATE_UNIT.search(line)
    if not unit_match:
        return None
    unit = float(unit_match.group(0).replace(".", "").replace(",", ""))

    remainder = line[:unit_match.start()] + " " + line[unit_match.end():]
    plausible = []
    for token in _RATE_VALUE.findall(remainder):
        try:
            value, places = _decimal(token)
        except ValueError:
            continue
        if value <= 0:
            continue
        rate = unit / value
        if RATE_MIN < rate < RATE_MAX:
            plausible.append((rate, places, value))
    if not plausible:
        return None
    # The current period is the first numeric column; the rest are comparatives.
    rate, places, value = plausible[0]
    return rate, places, value, tuple(round(r, 2) for r, _, _ in plausible[1:])


def extract_fx_rate(pdf_path: str) -> Optional[FxRate]:
    """Read the USD/IDR rate the filing says it used.

    Strategy 1: the disclosed rate table row, in whichever form the issuer prints it
                ("1.000 Rupiah 0,0697", "Indonesian Rupiah 10,000 ... 0.61").
    Strategy 2: a disclosed Rp / US$ pair elsewhere in the notes.

    Returns None when neither is present, rather than guessing a rate.
    """
    from pdftext import page_texts

    pair_fallback = None
    # OCR'd where the layer is unreadable: EMAS discloses its rate on page 23 in a
    # text layer that extracts as glyph ids, so reading the layer alone reports a
    # filing that states its rate as one that does not.
    texts = page_texts(pdf_path)
    for i in sorted(texts):
        text = texts[i]

        for line in text.split("\n"):
            if not _RUPIAH_LINE.search(line):
                continue
            found = _rate_from_line(line)
            if found:
                rate, places, quoted, others = found
                return FxRate(
                    idr_per_usd=rate,
                    source="disclosed_rate_table",
                    page=i + 1,
                    evidence=line.strip(),
                    decimals=places,
                    quoted_value=quoted,
                    other_candidates=others,
                )

        if pair_fallback is None:
            for m in _PAIR.finditer(text.replace("\n", " ")):
                rp = _num(m.group(1))
                usd = float(m.group(2).replace(",", ""))
                if usd > 0 and RATE_MIN < rp / usd < RATE_MAX:
                    pair_fallback = FxRate(
                        idr_per_usd=rp / usd,
                        source="derived_from_pair",
                        page=i + 1,
                        evidence=m.group(0).strip(),
                    )
                    break

    return pair_fallback


_SCALE_PATTERNS = [
    ("BILLIONS", re.compile(r"dalam\s+miliar|in\s+billions", re.I)),
    ("MILLIONS", re.compile(r"dalam\s+juta|in\s+millions", re.I)),
    ("THOUSANDS", re.compile(r"dalam\s+ribu|in\s+thousands", re.I)),
]


def detect_scale(document_text: str) -> Optional[str]:
    """Read the reporting scale from the statement header.

    The model is asked for this too, but scale is the single most damaging field to
    get wrong -- a missed "dalam ribuan" is a 1000x error in every figure, and it is
    stated in plain text a fixed distance from the title. Reading it directly gives
    an independent answer to check the model's against.
    """
    if not document_text:
        return None
    for name, pattern in _SCALE_PATTERNS:
        if pattern.search(document_text):
            return name
    return None


def to_idr(extraction, fx: Optional[FxRate] = None, pdf_path: Optional[str] = None,
           document_text: Optional[str] = None) -> dict:
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

    stated_scale = getattr(extraction, "reporting_scale", None)
    scale_name = (stated_scale or "FULL").upper()

    detected = detect_scale(document_text or "")
    if stated_scale is None and not document_text:
        # Nothing said the scale and there is no text to read it from. FULL is the
        # only sane default, but it is a guess, and a wrong one multiplies every
        # figure by a thousand -- so it is recorded rather than assumed silently.
        warnings.append("reporting_scale is absent and no document text was supplied "
                        "to read it from; assuming FULL")
    if detected and detected != scale_name:
        # Trust the printed header over the model: it is unambiguous and a wrong
        # scale multiplies every figure by a thousand or more.
        warnings.append(f"model said scale {scale_name}, header says {detected} - "
                        f"using {detected}")
        scale_name = detected
    elif detected is None and scale_name != "FULL":
        warnings.append(f"model said scale {scale_name} but no scale wording was "
                        f"found in the text")
    if scale_name not in SCALE_MULTIPLIER:
        warnings.append(f"Unknown reporting_scale {scale_name!r}, assuming FULL")
        scale_name = "FULL"
    scale = SCALE_MULTIPLIER[scale_name]

    # A MISSING currency and an UNRECOGNISED one are different situations. Missing is
    # what an abstention leaves behind: the confidence layer decided the value was not
    # worth asserting, and quietly assuming IDR turns that refusal into a silent
    # ~14,000x error on a USD filer. Refuse instead -- the whole point of abstaining is
    # that nothing downstream should proceed on the value.
    if getattr(extraction, "currency", None) is None:
        raise ValueError(
            "Reporting currency is absent (not extracted, or abstained on). "
            "Refusing to normalise: assuming a currency would silently misstate every "
            "figure by the exchange rate."
        )
    currency = str(extraction.currency).upper()
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
        # A rate quoted to two decimals carries roughly 0.8% uncertainty, which is 80x
        # the evaluator's tolerance. Every converted figure inherits it, so it is said
        # once rather than discovered later as an unexplained mismatch.
        if fx.rounding_error > 1e-3:
            warnings.append(
                f"Rate quoted to {fx.decimals} decimal places ({fx.quoted_value}), so "
                f"converted figures carry about {fx.rounding_error:.1%} rounding "
                f"uncertainty - wider than the evaluation tolerance."
            )
        if fx.other_candidates:
            # The comparative-period columns sit on the same row. Taking the first is
            # right, but saying which others were there makes the choice checkable.
            warnings.append(
                f"Rate row also carried {', '.join(f'{c:,.0f}' for c in fx.other_candidates)} "
                f"IDR/USD (comparative periods); took the first column, "
                f"{fx.idr_per_usd:,.0f}."
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
