
---

## PURA, RCCC, TRIN, TRUK — first check of the four new workbooks (2026-10-17)

**Origin:** the four workbooks were filled from the extraction CSVs of 9 October: 660 of
668 labelled cells are identical to `~/FinancialReport/<T>/<T>.csv`, including rows whose
extraction failed (`status=error`) and whose figures were typed in by hand. Every error
below is in a typed-in or copied cell; none was found in a cell the model read and the
confidence layer accepted.

**Found by:** tracing the evaluation of these four issuers back to the PDFs, plus the
free label screen (`scripts/audit_labels.py --phase screen`), which flagged a copied
column, two x1000 jumps and a subtotal larger than its total.

| Workbook | Cell | Period, field | Was | Now | Evidence |
|---|---|---|---:|---:|---|
| RCCC | `L4` | Q4 2023 aset | 202.327.685 | **88.069.161.715** | p9 JUMLAH ASET |
| RCCC | `L5` | Q4 2023 total_aset_lancar | 45.792.702.170 | **9.158.111.135** | p9 Jumlah Aset Lancar |
| RCCC | `L6` | Q4 2023 kas | 0 | **750.435.505** | p9 Kas dan bank |
| RCCC | `L7` | Q4 2023 liabilitas | 52.557.527.607 | **45.366.760.486** | p10 JUMLAH LIABILITAS |
| RCCC | `L8` | Q4 2023 utang_bank | 1.494.897.040 | **0** | p10: no bank loan; only consumer financing, labelled 0 in every other RCCC period |
| RCCC | `L9` | Q4 2023 ekuitas | 45.486.429.470 | **42.702.401.229** | p11 Jumlah Ekuitas |
| RCCC | `L10` | Q4 2023 laba_bersih | 8.014.200.649 | **3.501.836.408** | p12 LABA BERSIH TAHUN BERJALAN |
| RCCC | `L11` | Q4 2023 pendapatan | 787.500.000 | **75.756.461.938** | p12 PENDAPATAN |
| RCCC | `L12` | Q4 2023 kas_dari_aktivitas_operasi | (empty) | **31.437.589.559** | p14 |
| TRIN | `C8` | Q1 2026 utang_bank | 714.891.526.000 | **714.891.426.000** | p5, thousands |
| TRIN | `I9` | Q3 2024 ekuitas | 694.287.000.000 | **604.287.000.000** | p6 owners of the parent, thousands |
| TRIN | `I12` | Q3 2024 kas_dari_aktivitas_operasi | -32.839.167 | **-32.839.167.000** | p9, thousands not applied |
| TRIN | `E4` | Q3 2025 aset | 2.097.752.636.000 | **2.097.742.535.000** | p5 JUMLAH ASET, thousands |
| TRIN | `E12` | Q3 2025 kas_dari_aktivitas_operasi | -31.769.558 | **-31.769.558.000** | p9, thousands not applied |
| PURA | `C5` | Q1 2026 total_aset_lancar | 21.075.044.785 | **210.750.744.785** | p4 "2 10.750.744.785"; + non-current 434.481.634.055 = total assets 645.232.378.840 |
| TRUK | `D12` | Q4 2025 kas_dari_aktivitas_operasi | 35.868.960 | **35.868.950** | p16 |
| TRUK | `N4:N12` | Q2 2023, nine monetary fields | Q1 2023's figures | **(emptied)** | `Q2_2023_TRUK.pdf` is byte-identical to `Q1_2023_TRUK.pdf` (same SHA-1, dated 31 Maret 2023). Re-download the real Q2 2023 report, then label it. |

**How RCCC Q4 2023 went wrong:** the column held the Q2 2026 filing's figures shifted one
row up -- its cash in the `aset` slot, total liabilities in `total_aset_lancar`, equity
in `liabilitas`, profit in `utang_bank`, revenue in `ekuitas`, operating cash in
`laba_bersih`, and RCCC's issued share count (787.500.000) in `pendapatan`.

**Not changed, pending the share-count review:** every `total_share` cell, including
TRIN's (the shareholder table prints counts in thousands of shares, so the labels are
1000x small), TRIN Q2/Q4 2022 (issued rather than outstanding), RCCC `L13` and TRUK `N13`.

**Consequence if left:** these issuers were scored against a copy of the extraction, so
any metric on them measured agreement with the CSV rather than accuracy. The typed-in
cells would have been counted as extractor errors on a re-run.

**How it was changed:** only the `<v>` of each listed cell in Sheet1's XML; every other
zip entry copied unchanged; `fullCalcOnLoad` set so Excel recalculates the ratio formulas.
