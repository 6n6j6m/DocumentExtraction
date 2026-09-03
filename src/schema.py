"""
Financial statement extraction schema for Indonesian (IDX) filings.

The label examples below follow PSAK terminology rather than one issuer's wording.
The system was developed against ARCI and has only been scored on it, but nothing
in this schema is specific to that issuer.
"""

from dataclasses import dataclass
from typing import Optional


class SchemaTypeError(ValueError):
    """A payload assigned a value of the wrong type to a schema field.

    A ValueError subclass so existing `except ValueError` handlers keep working, but
    distinct enough for the API layer to turn into a 400 rather than a 500.
    """


# What each field may hold. Kept as data rather than read from the annotations at
# runtime because the annotations are Optional[...] unions, and unwrapping those is
# more code than restating three categories.
NUMBER = "number"
TEXT = "text"
NUMBER_LIST = "number_list"

FIELD_TYPES = {
    "period_end_date": TEXT,
    "aset": NUMBER,
    "total_aset_lancar": NUMBER,
    "kas": NUMBER,
    "liabilitas": NUMBER,
    "utang_bank": NUMBER,
    "ekuitas": NUMBER,
    "pendapatan": NUMBER,
    "laba_bersih": NUMBER,
    "kas_dari_aktivitas_operasi": NUMBER,
    "total_share": NUMBER,
    "utang_bank_jangka_pendek": NUMBER,
    "utang_bank_bagian_lancar": NUMBER,
    "total_ekuitas": NUMBER,
    "kepentingan_non_pengendali": NUMBER,
    "total_share_components": NUMBER_LIST,
    "currency": TEXT,
    "reporting_scale": TEXT,
    "statement_scope": TEXT,
}


@dataclass
class FinancialStatementExtraction:
    """Extracted financial statement fields from an IDX filing.

    Field mapping and keyword rules (common variants are listed in src/prompts.py):
    
    - total_share: "disetor penuh pada tanggal [date]" (most recent date)
    - aset: "Total Aset"
    - total_aset_lancar: "Total Aset Lancar"
    - kas: "Kas dan Setara Kas"
    - liabilitas: "Total Liabilitas"
    - utang_bank: "Utang Bank Jangka Pendek" + "Utang Bank Saja" (sum, exclude long-term)
    - ekuitas: "Ekuitas yang Diatribusikan kepada Pemilik Induk" (EXCLUDE Kepentingan Non Pengendali)
    - laba_bersih: "Laba ... Tahun Berjalan yang Diatribusikan kepada Pemilik Induk" (EXCLUDE Kepentingan Non Pengendali)
    - pendapatan: "Pendapatan dari Kontrak dengan Pelanggan"
    - kas_dari_aktivitas_operasi: "Kas Neto Diperoleh dari Aktivitas Operasi"
    """
    
    # Identifiers
    period_end_date: Optional[str] = None          # ISO format: YYYY-MM-DD
    
    # Balance sheet items
    aset: Optional[float] = None
    total_aset_lancar: Optional[float] = None
    kas: Optional[float] = None
    liabilitas: Optional[float] = None
    utang_bank: Optional[float] = None            # DERIVED = jangka_pendek + bagian_lancar  # Utang Bank Jangka Pendek + Utang Bank Saja
    ekuitas: Optional[float] = None               # DERIVED = total_ekuitas - kepentingan_non_pengendali          # Ekuitas yang Diatribusikan (exclude non-controlling)
    
    # Income statement items
    pendapatan: Optional[float] = None                # Pendapatan dari Kontrak dengan Pelanggan
    laba_bersih: Optional[float] = None             # Laba Tahun Berjalan yang Diatribusikan (exclude non-controlling)
    
    # Cash flow items
    kas_dari_aktivitas_operasi: Optional[float] = None    # Kas Neto Diperoleh dari Aktivitas Operasi
    
    # Shares
    total_share: Optional[float] = None     # Disetor penuh pada tanggal [date]
    
    # --- Components, asked for separately and combined in code. -----------------
    # Deciding which of three identically-labelled "Utang bank" rows to add, or
    # subtracting a negative non-controlling interest, is selection and arithmetic.
    # A model reading flattened text is unreliable at both and gives no way to see
    # WHICH half it got wrong. Asking for the atomic rows instead turns the task
    # into "copy the number beside this label", and the combination becomes code.
    utang_bank_jangka_pendek: Optional[float] = None      # under "Liabilitas Jangka Pendek"
    utang_bank_bagian_lancar: Optional[float] = None      # under "Bagian lancar atas liabilitas jangka panjang"
    total_ekuitas: Optional[float] = None                 # "Total Ekuitas" (includes NCI)
    kepentingan_non_pengendali: Optional[float] = None    # "Kepentingan Non-Pengendali", often negative

    # Share capital is not always one line. JPFA issues Seri A and Seri B and prints a
    # count for each, never their total; ARCI issues one class and prints it whole.
    # Asking for the per-class counts covers both, and the sum is computed here for
    # the same reason utang_bank is: the arithmetic is exact, and a wrong answer
    # points at one misread class rather than at an opaque total.
    total_share_components: Optional[list] = None         # per-class issued share counts

    # Metadata
    currency: Optional[str] = None                 # "USD" or "IDR"
    reporting_scale: Optional[str] = None          # "FULL" | "THOUSANDS" | "MILLIONS" | "BILLIONS"
    statement_scope: Optional[str] = None          # "CONSOLIDATED" or "PARENT_ONLY"
    
    def to_dict(self):
        """Convert to dictionary."""
        return {
            "period_end_date": self.period_end_date,
            "aset": self.aset,
            "total_aset_lancar": self.total_aset_lancar,
            "kas": self.kas,
            "liabilitas": self.liabilitas,
            "utang_bank": self.utang_bank,
            "ekuitas": self.ekuitas,
            "pendapatan": self.pendapatan,
            "laba_bersih": self.laba_bersih,
            "kas_dari_aktivitas_operasi": self.kas_dari_aktivitas_operasi,
            "total_share": self.total_share,
            "utang_bank_jangka_pendek": self.utang_bank_jangka_pendek,
            "utang_bank_bagian_lancar": self.utang_bank_bagian_lancar,
            "total_ekuitas": self.total_ekuitas,
            "kepentingan_non_pengendali": self.kepentingan_non_pengendali,
            "total_share_components": self.total_share_components,
            "currency": self.currency,
            "reporting_scale": self.reporting_scale,
            "statement_scope": self.statement_scope,
        }
    
    @classmethod
    def from_dict(cls, data: dict, strict: bool = True):
        """Create from a dictionary, rejecting values of the wrong type.

        The annotations on this class used to be documentation only: anything at all
        could be assigned, and the mistake surfaced later as
        `TypeError: '<' not supported between instances of 'str' and 'int'` from inside
        a validation rule, three frames from the thing that was actually wrong. JSON
        reaches this constructor from two directions -- a model response and a cached
        prediction file -- and neither is trustworthy enough to skip the check.

        Every offending field is reported in one message rather than one per attempt,
        because a malformed payload usually has more than one problem and fixing them
        one round trip at a time is miserable.

        `strict=False` restores the old permissive behaviour for callers that have
        already coerced their input.
        """
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        if not strict:
            return cls(**known)

        problems = []
        for name, value in known.items():
            if value is None:
                continue
            expected = FIELD_TYPES.get(name)
            if expected is NUMBER:
                # bool is a subclass of int in Python, so `isinstance(True, int)` is
                # True and a stray boolean would sail through as 1.0.
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    problems.append(f"{name}: expected a number, got "
                                    f"{type(value).__name__} ({value!r})")
            elif expected is TEXT:
                if not isinstance(value, str):
                    problems.append(f"{name}: expected a string, got "
                                    f"{type(value).__name__} ({value!r})")
            elif expected is NUMBER_LIST:
                if not isinstance(value, list) or any(
                        isinstance(v, bool) or not isinstance(v, (int, float))
                        for v in value):
                    problems.append(f"{name}: expected a list of numbers, got {value!r}")

        if problems:
            raise SchemaTypeError(
                f"{cls.__name__} received {len(problems)} field(s) of the wrong type:\n  "
                + "\n  ".join(problems))

        # int is accepted where a float is declared, and normalised here so downstream
        # arithmetic and JSON output do not vary by how the model happened to write it.
        for name, value in list(known.items()):
            if FIELD_TYPES.get(name) is NUMBER and isinstance(value, int):
                known[name] = float(value)
            elif FIELD_TYPES.get(name) is NUMBER_LIST and isinstance(value, list):
                known[name] = [float(v) for v in value]

        return cls(**known)


# Maps each field to the row it belongs to in data/ground_truth/<TICKER>.xlsx.
# The sheet is the system of record for field naming, so the label text here is
# copied verbatim from column A -- if a label in the sheet is edited, edit it here
# too rather than renaming the field.
EXCEL_ROWS = {
    "aset":                       (4,  "Aset"),
    "total_aset_lancar":          (5,  "total aset lancar"),
    "kas":                        (6,  "KAS"),
    "liabilitas":                 (7,  "liabilitas"),
    "utang_bank":                 (8,  "Utang Bank SAJA Jangka Pendek + Panjang jatuh tempo"),
    "ekuitas":                    (9,  "ekuitas"),
    "laba_bersih":                (10, "laba bersih"),
    "pendapatan":                 (11, "pendapatan dari kontrak dengan pelanggan"),
    "kas_dari_aktivitas_operasi": (12, "kas dari aktivitas operasi"),
    "total_share":                (13, "total share"),
}
