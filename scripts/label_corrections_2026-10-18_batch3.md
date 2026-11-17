
---

## utang_bank (and one kas) in four older workbooks (2026-10-18, PROPOSED -- batch 3)

**Found by:** tracing every wrong utang_bank cell in the replay of the 14 older issuers to
the filing. In seven of them the extractor read the filing correctly and the label had
added a non-current loan, a lease, an employee-benefit line, or taken the comparative
column -- all excluded by the field's own definition (bank and non-bank financial
institution loans due within one year).

| Workbook | Cell | Period | Was | Now | Evidence |
|---|---|---|---:|---:|---|
| AADI | `H8` | Q4 2024 | 11.074.016.129.032 | **659.419.354.839** | 40.884 thousand USD current portion (p. balance sheet); the label added the 645.705 non-current portion |
| ADMR | `C8` | Q1 2026 | 16.264.593.220.339 | **637.406.779.661** | 37.607 thousand USD current bank loan; the label added the 922.004 non-current loan |
| ADMR | `B8` | Q2 2026 | 20.674.714.285.714 | **3.833.410.714.286** | p7 'Utang bank - bagian jangka pendek 19 214.671'; the label added the 943.113 non-current loan |
| ADMR | `F8` | Q2 2025 | 5.284.096.774 | **0** | p7: the only bank loan (493.785.754) is NON-current; the label 327.614 USD is the lease non-current portion |
| CPIN | `H8` | Q4 2024 | 7.392.848.000.000 | **5.400.000.000.000** | p14 'Utang bank jangka pendek 5.400.000 2.14.38 7.392.848': CPIN prints the current year LEFT of the notes; the label was the 2023 column |
| TLDN | `M8` | Q3 2023 | 504.707.348.000 | **441.100.000.000** | p6 current maturity 'Utang bank 441.100.000'; the label added 63.607.348. short-term employee benefits |
| ADMR | `R6` | Q2 2022 | 6.346.501.388.060 | **5.495.776.552.239** | p6 'Kas dan setara kas 5 368.217.029' = cash-flow closing balance p11; the label added 56.998.564 USD. the TRADE RECEIVABLES total of note 7 (p60) |

**Consequence if left:** seven correct extractions scored as wrong, and leverage ratios
on these periods computed from a debt figure that includes long-term loans or leases.
