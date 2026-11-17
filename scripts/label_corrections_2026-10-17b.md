
---

## TRIN consolidated figures and parent-attributable profit (2026-10-17, second batch)

**Origin:** typed in by hand into rows whose extraction had failed (`status=error` in the
9 October CSV), or copied from that CSV.

**Found by:** re-extracting PURA/RCCC/TRIN/TRUK with `gemini-3.5-flash-lite` after the
CP19 fixes. Every one of the 23 cells scored wrong was traced to the PDF; in these 16 the
label, not the model, disagreed with the filing.

| Cell | Period, field | Was | Now | Evidence (thousands of Rupiah) |
|---|---|---:|---:|---|
| `H4` | Q4 2024 aset | 973.210.391.000 | **2.222.883.786.000** | p11 TOTAL ASET |
| `H5` | Q4 2024 total_aset_lancar | 553.693.033.000 | **1.408.461.498.000** | p11 |
| `H6` | Q4 2024 kas | 4.628.746.000 | **30.318.046.000** | p11 |
| `H7` | Q4 2024 liabilitas | 409.872.252.000 | **1.804.103.147.000** | p12 TOTAL LIABILITAS |
| `H8` | Q4 2024 utang_bank | 153.192.667.000 | **695.981.931.000** | p12 current maturity, bank and non-bank lenders |
| `H9` | Q4 2024 ekuitas | 563.338.139.000 | **512.068.584.000** | p13 attributable to owners of the parent |
| `H10` | Q4 2024 laba_bersih | -43.463.315.000 | **-133.851.628.000** | p15 Pemilik entitas induk |
| `H11` | Q4 2024 pendapatan | 2.655.971.000 | **216.640.836.000** | p14 PENDAPATAN |
| `H12` | Q4 2024 kas_dari_aktivitas_operasi | 4.722.287.000 | **-9.620.193.000** | p17 |
| `P10` | Q4 2022 laba_bersih | -28.044.284.000 | **205.740.000** | p16 Pemilik entitas induk (the label was the TOTAL row, with the wrong sign) |
| `L10` | Q4 2023 laba_bersih | -146.450.768.000 | **-90.244.453.000** | p14 Pemilik entitas induk (label: total) |
| `I10` | Q3 2024 laba_bersih | -62.449.060.000 | **-45.211.769.000** | p7 Pemilik Entitas Induk (label: loss before tax) |
| `E10` | Q3 2025 laba_bersih | 31.096.003.000 | **28.483.202.000** | p7 Pemilik Entitas Induk (label: total) |
| `N12` | Q2 2023 kas_dari_aktivitas_operasi | -66.612.336.000 | **-230.537.354.000** | p9 "( 230.537.354)"; -66.612.336 is the H1 2022 figure (Q2 2022 filing p17), i.e. the comparative column |
| `P12` | Q4 2022 kas_dari_aktivitas_operasi | -35.264.794.000 | **-143.820.184.000** | p18 "Aktivitas Operasi (143.820.184)"; the label was the investing line below it; the Q4 2023 filing's comparative column agrees |
| `D10` | Q4 2025 laba_bersih | -10.530.558.000 | **12.188.231.000** | p14 Pemilik entitas induk (label: total, wrong sign) |

**Why Q4 2024 went wrong:** the annual report prints the parent-only statements as
supplementary information on pp. 127-132. Every Q4 2024 label came from there; the sheet
labels consolidated figures in every other period.

**Not changed, pending the share-count review:** TRIN `total_share` everywhere, and RCCC
Q2 2023 `total_share` (787.500.000 is not printed in that filing; it prints 750.000.000).

**Consequence if left:** sixteen cells in which a correct extraction scored as wrong;
TRIN's accuracy understated by 7.8 points on these cells alone.
