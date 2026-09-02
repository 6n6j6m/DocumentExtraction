"""
Financial statement extraction schema for PT Archi Indonesia (ARCI).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FinancialStatementExtraction:
    """Extracted financial statement fields from ARCI filings.
    
    Field mapping and keyword rules:
    
    - shares_outstanding: "disetor penuh pada tanggal [date]" (most recent date)
    - total_assets: "Total Aset"
    - total_current_assets: "Total Aset Lancar"
    - cash_and_equivalents: "Kas dan Setara Kas"
    - total_liabilities: "Total Liabilitas"
    - short_term_bank_debt: "Utang Bank Jangka Pendek" + "Utang Bank Saja" (sum, exclude long-term)
    - total_equity: "Ekuitas yang Diatribusikan kepada Pemilik Induk" (EXCLUDE Kepentingan Non Pengendali)
    - net_income: "Laba ... Tahun Berjalan yang Diatribusikan kepada Pemilik Induk" (EXCLUDE Kepentingan Non Pengendali)
    - revenue: "Pendapatan dari Kontrak dengan Pelanggan"
    - operating_cash_flow: "Kas Neto Diperoleh dari Aktivitas Operasi"
    """
    
    # Identifiers
    period_end_date: Optional[str] = None          # ISO format: YYYY-MM-DD
    
    # Balance sheet items
    total_assets: Optional[float] = None
    total_current_assets: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    total_liabilities: Optional[float] = None
    short_term_bank_debt: Optional[float] = None  # Utang Bank Jangka Pendek + Utang Bank Saja
    total_equity: Optional[float] = None          # Ekuitas yang Diatribusikan (exclude non-controlling)
    
    # Income statement items
    revenue: Optional[float] = None                # Pendapatan dari Kontrak dengan Pelanggan
    net_income: Optional[float] = None             # Laba Tahun Berjalan yang Diatribusikan (exclude non-controlling)
    
    # Cash flow items
    operating_cash_flow: Optional[float] = None    # Kas Neto Diperoleh dari Aktivitas Operasi
    
    # Shares
    shares_outstanding: Optional[float] = None     # Disetor penuh pada tanggal [date]
    
    # Metadata
    currency: Optional[str] = None                 # "USD" or "IDR"
    statement_scope: Optional[str] = None          # "CONSOLIDATED" or "PARENT_ONLY"
    
    def to_dict(self):
        """Convert to dictionary."""
        return {
            "period_end_date": self.period_end_date,
            "total_assets": self.total_assets,
            "total_current_assets": self.total_current_assets,
            "cash_and_equivalents": self.cash_and_equivalents,
            "total_liabilities": self.total_liabilities,
            "short_term_bank_debt": self.short_term_bank_debt,
            "total_equity": self.total_equity,
            "revenue": self.revenue,
            "net_income": self.net_income,
            "operating_cash_flow": self.operating_cash_flow,
            "shares_outstanding": self.shares_outstanding,
            "currency": self.currency,
            "statement_scope": self.statement_scope,
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
