
---

## AKRA Q1 2022 - Q3 2023 printed in thousands (2026-11-03, approved by the user)

**Found by:** the 1000x gap between AKRA's 2022-Q3 2023 labels and its 2024+ labels
(Q1 2023 revenue 10.891.301.304 vs Q1 2024 9.811.388.310.000).

**Cause:** every one of these seven filings heads its statements "(Angka disajikan dalam
ribuan Rupiah, (Amounts are expressed in thousands of Rupiah, ...)". The scale reader
(`normalize._HEADER_STATEMENT`) wanted the verb straight after the parenthesis, missed
that header, and took the par-value line "(dalam Rupiah penuh)" under Modal saham as the
header instead -- so the label audit and the extractor both applied FULL.

**Change:** columns N-T (Q3 2023, Q2 2023, Q1 2023, TAHUNAN 2022, Q3 2022, Q2 2022,
Q1 2022), rows 4-12 (aset ... kas_dari_aktivitas_operasi), 63 cells, each multiplied by
1000. Checked before the change: every old label except utang_bank (a sum of two lines)
is printed verbatim in its filing, and every filing carries the "ribuan" header. Row 13
(total_share) is a count and is untouched.

**Two cells corrected beyond the scale** (values in thousands as printed):

| Cell | Period / field | Was (x1000) | Now | Evidence |
|---|---|---:|---:|---|
| `P8` | Q1 2023 utang_bank | 549.832.511 | **548.258.806** | p5: "Hutang bank jangka pendek dan lainnya - ... 1.573.705" is blank for Mar 2023; 1.573.705 is the Dec 2022 comparative. Only the current maturity 548.258.806 remains |
| `O11` | Q2 2023 pendapatan | 19.712.698.187 | **19.854.711.809** | p7 "Sub-total 19.854.711.809" (contracts + rental 142.013.622); the Q2 2024 filing prints it as "Total Pendapatan", and the workbook already uses Total Pendapatan from Q3 2023 on |

**Consequence if left:** seven AKRA periods 1000x too small, and every ratio on them
(book value per share, EPS, PBV, PE) off by the same factor.
