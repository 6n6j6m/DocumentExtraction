"""
Extraction prompts for PT Archi Indonesia financial statements.

These prompts guide Gemini to extract specific fields using ARCI-specific
keyword rules and Indonesian financial terminology.
"""

SYSTEM_PROMPT = """You are an expert financial statement analyst specializing in Indonesian company filings.

Your task is to extract financial data from PT Archi Indonesia (ARCI) quarterly/annual reports.

CRITICAL RULES:
1. Extract ONLY values that appear explicitly in the document
2. Use exact keywords and phrases specified below
3. Return null for missing fields (not zero, not empty string)
4. Always include the evidence quote (exact text from document) for each field
5. Currency is typically USD; if different, note it
6. Dates in ISO format: YYYY-MM-DD
7. Numbers without formatting (no commas, no dots except decimals)
8. EXCLUDE non-controlling interest (kepentingan non pengendali) from totals
"""

EXTRACTION_PROMPT = """Extract the following fields from this ARCI financial statement:

FIELD EXTRACTION RULES (Indonesian keywords):

1. period_end_date
   - Extract the reporting period end date (e.g., "31 Maret 2022" → "2022-03-31")
   - Look for: "Periode berakhir", "Tanggal", "31 Desember", "30 Juni", etc.

2. total_assets (Total Aset)
   - Keyword: "Total Aset" (balance sheet line item)
   - This is the total of all assets
   - Example: "Total Aset: 694.671.337"

3. total_current_assets (Total Aset Lancar)
   - Keyword: "Total Aset Lancar"
   - This is current assets only (cash, receivables, inventory, etc.)
   - Example: "Total Aset Lancar: 73.325.265"

4. cash_and_equivalents (Kas dan Setara Kas)
   - Keyword: "Kas dan Setara Kas"
   - This is cash and cash equivalents line item
   - Example: "Kas dan Setara Kas: 23.125.502"

5. total_liabilities (Total Liabilitas)
   - Keyword: "Total Liabilitas"
   - This is total of all liabilities
   - Example: "Total Liabilitas: 450.000.000"

6. short_term_bank_debt (Utang Bank Jangka Pendek)
   - Keywords: "Utang Bank Jangka Pendek" + "Utang Bank Saja"
   - ADD these two line items together (if both exist)
   - EXCLUDE long-term bank debt
   - Example: If "Utang Bank Jangka Pendek: 50M" and "Utang Bank Saja: 30M" → Sum = 80M

7. total_equity (Ekuitas yang Diatribusikan)
   - Keyword: "Ekuitas yang Diatribusikan kepada Pemilik Induk"
   - IMPORTANT: EXCLUDE "Kepentingan Non Pengendali" (non-controlling interest)
   - Use only the parent entity equity
   - Example: "Ekuitas yang Diatribusikan: 200.000.000"

8. revenue (Pendapatan)
   - Keyword: "Pendapatan dari Kontrak dengan Pelanggan"
   - This is revenue from contracts with customers (income statement)
   - Example: "Pendapatan dari Kontrak dengan Pelanggan: 500.000.000"

9. net_income (Laba Bersih)
   - Keyword: "Laba ... Tahun Berjalan yang Diatribusikan kepada Pemilik Induk"
   - IMPORTANT: EXCLUDE "Kepentingan Non Pengendali"
   - Use only the parent entity net income
   - Example: "Laba Tahun Berjalan yang Diatribusikan: 100.000.000"

10. operating_cash_flow (Arus Kas Operasi)
    - Keyword: "Kas Neto Diperoleh dari Aktivitas Operasi"
    - This is net cash from operating activities (cash flow statement)
    - Example: "Kas Neto Diperoleh dari Aktivitas Operasi: 150.000.000"

11. shares_outstanding (Modal Saham/Shares)
    - Keyword: "disetor penuh pada tanggal [DATE]"
    - Extract the most recent date and number of shares
    - Example: "Modal Saham disetor penuh pada tanggal 31 Desember 2022: 100.000.000"

12. currency
    - Usually "USD" for ARCI (look for "Dolar Amerika Serikat" or "$")
    - Could also be "IDR" if stated otherwise
    - Example: "Disajikan dalam Dolar Amerika Serikat"

13. statement_scope
    - "CONSOLIDATED" if using consolidated financial statements ("Konsolidasian")
    - "PARENT_ONLY" if using parent entity only statements ("Entitas Induk")
    - Default: "CONSOLIDATED"

RESPONSE FORMAT:
Return valid JSON with all fields. Use null for missing fields.

Example:
{
  "period_end_date": "2022-03-31",
  "total_assets": 694671337,
  "total_current_assets": 73325265,
  "cash_and_equivalents": 23125502,
  "total_liabilities": null,
  "short_term_bank_debt": null,
  "total_equity": null,
  "revenue": null,
  "net_income": null,
  "operating_cash_flow": null,
  "shares_outstanding": null,
  "currency": "USD",
  "statement_scope": "CONSOLIDATED"
}

IMPORTANT:
- Include evidence for every field (exact quote from document)
- If you cannot find a field, use null (not zero)
- Double-check equity and net income to EXCLUDE non-controlling interest
- Numbers should be whole values (remove formatting)
"""
