"""
Financial statement extraction schema for PT Archi Indonesia (ARCI).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FinancialStatementExtraction:
    """Extracted financial statement fields from ARCI filings.
    
    Field mapping and keyword rules:
    
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
    utang_bank: Optional[float] = None  # Utang Bank Jangka Pendek + Utang Bank Saja
    ekuitas: Optional[float] = None          # Ekuitas yang Diatribusikan (exclude non-controlling)
    
    # Income statement items
    pendapatan: Optional[float] = None                # Pendapatan dari Kontrak dengan Pelanggan
    laba_bersih: Optional[float] = None             # Laba Tahun Berjalan yang Diatribusikan (exclude non-controlling)
    
    # Cash flow items
    kas_dari_aktivitas_operasi: Optional[float] = None    # Kas Neto Diperoleh dari Aktivitas Operasi
    
    # Shares
    total_share: Optional[float] = None     # Disetor penuh pada tanggal [date]
    
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
            "currency": self.currency,
            "reporting_scale": self.reporting_scale,
            "statement_scope": self.statement_scope,
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


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
