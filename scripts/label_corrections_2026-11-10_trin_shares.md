
---

## TRIN total_share outstanding (proposed 2026-11-10, approved by the user 2026-11-17)

**Found by:** `scripts/evaluate_output.py --ticker TRIN` after re-extracting the stale rows.
`total_share` is shares OUTSTANDING (issued less treasury), as everywhere else in the
workbooks.

| Cell | Period | Was | Now | Evidence |
|---|---|---:|---:|---|
| `P13` | TAHUNAN 2022 | 4.404.476 | **4.205.476** | Q4_2022_TRIN.pdf p101 note 28: "Sub-total 4.205.476 95%", "Saham treasuri 199.000 5%", "Total 4.404.476 100%"; the label was the issued total |
| `D13` | Q4 2025 | 4.352.457 | **4.424.040** | Q4_2025_TRIN.pdf p103, 2025 table: "Sub-total 4.424.040 97,20%", "Saham treasuri 127.417 2,80%"; 4.352.457 is the Sub-total of the 2024 comparative table below it |

Units unchanged (thousands of shares as printed; the TRIN unit decision of CP19 stands).

**Consequence if left:** book value per share and EPS for these two periods computed on
the wrong share count; one correct extraction scored as wrong.
