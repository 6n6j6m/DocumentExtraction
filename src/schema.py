"""
Financial Statement Extraction Schema

Defines the structure for extracted financial statement data from ARCI (PT Archi Indonesia Tbk).
All monetary values are stored as strings (as-printed from document) and normalized later.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FinancialStatementExtraction:
    """
    Extracted financial statement data from ARCI quarterly/annual reports.

    All monetary fields are stored as strings in their original format (e.g., "1074611806").
    Dates are stored as strings (e.g., "2022-06-30").

    These are "raw" extracted values before normalization.
    """

    # Reporting period
    period_end_date: Optional[str] = None  # e.g., "2022-06-30"

    # Balance Sheet - Assets
    total_assets: Optional[str] = None
    total_current_assets: Optional[str] = None
    cash: Optional[str] = None  # Kas dan Setara Kas

    # Balance Sheet - Liabilities
    total_liabilities: Optional[str] = None
    bank_loans: Optional[str] = None  # Utang Bank (short-term + long-term)

    # Balance Sheet - Equity
    total_equity: Optional[str] = None  # Ekuitas yang Diatribusikan kepada Pemilik

    # Income Statement
    net_income: Optional[str] = None  # Laba Periode/Tahun Berjalan yang Diatribusikan
    revenue: Optional[str] = None  # Pendapatan dari Kontrak dengan Pelanggan

    # Cash Flow Statement
    operating_cash_flow: Optional[str] = None  # Kas Neto Diperoleh dari Aktivitas Operasi

    # Share Information
    total_shares: Optional[str] = None  # Total Saham (ditempatkan dan disetor penuh)

    # Currency/Unit info
    currency: Optional[str] = None  # e.g., "USD" or "IDR"
    reporting_unit: Optional[str] = None  # e.g., "thousands", "millions", "actual"

    # Raw transcription (untuk validasi & grounding nanti)
    transcription: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


# Contoh structure untuk testing (nanti dihapus)
if __name__ == "__main__":
    sample = FinancialStatementExtraction(
        period_end_date="2022-06-30",
        total_assets="1074611806",
        total_current_assets="166840645",
        cash="22920611",
        total_liabilities="660973156",
        bank_loans="49041039",
        total_equity="413638650",
        net_income="80251426",
        revenue="322288365",
        operating_cash_flow="92133771",
        total_shares="25235000000",
        currency="USD",
        reporting_unit="actual"
    )
    print(sample.to_dict())
