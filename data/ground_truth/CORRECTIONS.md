# Ground-truth corrections

Every change made to a label after it was first entered, with the evidence that
justified it. Ground truth is the foundation the whole scorecard rests on; if it is
wrong, every metric is wrong in a way no care elsewhere recovers. An audit trail is
what makes "ground truth you can trust" a checkable claim rather than an assertion.

Format: one entry per corrected cell.

---

## ARCI `ekuitas`, Q1 and Q2 2022 — wrong equity subtotal

| | Cell | Was (IDR) | Now (IDR) |
|---|---|---:|---:|
| Q1 2022 | `S9` | 3,474,681,606,887 | **3,475,782,496,413** |
| Q2 2022 | `R9` | 3,668,083,982,169 | **3,670,567,132,244** |

**Origin:** manual labelling.

**Found by:** cross-checking the labels against the filings while building the FX
conversion. The balance-sheet reconstruction disagreed on `ekuitas` for Q1 and Q2 by
0.03%, while Q3 and Q4 agreed exactly.

**What was wrong:** both cells had been filled with `Total Ekuitas` — the
consolidated total, which *includes* non-controlling interest — instead of the
parent-attributable subtotal. Q3 and Q4 used the parent-attributable figure, so the
sheet was inconsistent with itself and with its own header, `(HANYA YANG BISA
DIATRIBUSIKAN KE ENTITAS INDUK SAJA)`.

**Evidence, from the filings (US Dollars, page 7 of each interim report):**

| | Total Ekuitas | Kepentingan Non-Pengendali | Attributable to parent |
|---|---:|---:|---:|
| Q1 | 242,185,308 | (76,732) | **242,262,040** |
| Q2 | 246,862,052 | (167,116) | **247,029,168** |
| Q3 | 247,982,427 | (145,186) | 248,127,613 ✓ already correct |
| Q4 | 247,755,439 | (82,486) | 247,837,925 ✓ already correct |

**Why it was easy to miss:** the non-controlling interest is **negative** in these
filings, so equity attributable to the parent is *larger* than total equity — the
opposite of the usual intuition. The resulting error is 0.03%, small enough to look
like rounding.

**Consequence if left:** `ekuitas` feeds BVPS, ROE, PBV and DER, so two of the four
periods would have carried a quiet bias in every derived ratio. The extractor would
also have been scored as wrong on a field it read correctly.

**Guard added:** `derive_fields()` in `src/extract.py` now computes the
parent-attributable figure as `total_ekuitas - kepentingan_non_pengendali` rather
than asking the model for it, and `src/validate.py` checks the printed
identity. `tests/test_guards.py` covers both.

**Detection depended on tolerance.** At the default 0.01% the discrepancy fails the
comparison; at a 1% tolerance it passes silently. This is the reason the default is
tight.

---

## ADMR and PTBA `D1` — the sheet named the wrong issuer

| Workbook | Cell | Was | Now |
|---|---|---|---|
| `ADMR.xlsx` | `D1` | ITMG | **ADMR** |
| `PTBA.xlsx` | `D1` | AADI | **PTBA** |

**Origin:** each workbook was made by copying an existing one and overwriting the
columns — the procedure `.claude/skills/label-groundtruth` describes — and the issuer
cell was never re-typed.

**Found by:** extending the evaluation harness from one ticker to the whole corpus.
`load_ground_truth()` compares `D1` against the ticker being scored and raises rather
than scoring one issuer's extraction against another's figures. Two of the fourteen
workbooks tripped it.

**Evidence that only the label was wrong, not the figures.** `total share` is a count of
shares and is never scaled or FX-converted, so it identifies an issuer on sight:

| Workbook | `total share` as labelled | The issuer named in `D1` |
|---|---:|---:|
| `ADMR.xlsx` | 40,882,331,500 — ADMR's shareholder-table total | ITMG issues 1,129,925,000 |
| `PTBA.xlsx` | 11,514,357,250 / 11,487,209,350 — PTBA outstanding | AADI issues 7,786,891,760 |

Total assets agree: `ADMR.xlsx` runs Rp 14–74 trillion against ITMG's Rp 28–43 trillion,
and `PTBA.xlsx` Rp 36–48 trillion against AADI's Rp 95–113 trillion. The columns hold the
right issuer's filings throughout; only the name in `D1` was stale.

**Consequence if left:** the ticker guard refuses both workbooks, so 360 labelled cells —
16% of the corpus, two of the fourteen issuers — could never be scored. The guard was
doing its job; the label was the defect.

**How it was changed:** the `D1` cell alone was rewritten in the sheet XML, as an inline
string, leaving every other zip entry byte-identical. Verified by reading every cell of
all three sheets in both workbooks before and after: exactly one cell differs in each.
No figure was touched.

**Guard added:** none needed — the existing ticker guard is what found this. The corpus
harness now reports a `D1` mismatch as a named, skipped workbook instead of aborting the
run, so a future copy-paste is visible in the report rather than fatal.

---

## GTRA, every period before Q1 2026 — the columns were shifted by two

**Origin:** manual labelling. Columns `B` and `C` (Q2 2026, Q1 2026) were right; from `D`
onwards every cell held the figure belonging two columns to its left, so the sheet's
Q4 2025 column carried Q2 2026's figures, its Q3 2025 column carried Q1 2026's, and so on
down to `R`.

**Found by:** the first full-corpus evaluation pass. GTRA scored **20.0% (30/150)** while
twelve of the thirteen other issuers scored 92–100% — a slice that a single corpus-wide
accuracy figure of 93% hid completely.

**Evidence, independent of the extractor.** GTRA's own Q4 2025 filing prints total assets
of **1.242.804.936.571** on pages 11, 13 and 85. That figure sat in `F4`, the column headed
Q2 2025. The figure the sheet had in `D4` (Q4 2025), 1.740.079.004.309, appears nowhere in
that filing — it is Q2 2026's. The two newest columns agreed with their own filings, which
is what identified the labels rather than the extraction as the shifted side.

**Consequence if left:** 117 of the 138 wrong cells in the whole corpus were this one
defect. Any change measured against this baseline would have been measured against an
issuer whose every figure was a quarter or two out of place.

**Fixed:** 326 cells — rows 4–13 shifted two columns left, and the derived ratio rows
15–22 recomputed. GTRA now scores **97.3% (146/150)**, and the corpus **98.9% (2204/2229)**,
up from 93.2%.

Two defects in the same workbook survived the shift repair and are corrected in the two
entries below.

**Guard added:** none — the ticker guard and the slices are what found this. The lesson is
in `src/evalmetrics.py`: `by_slice` carries an `n` on every row precisely so one issuer
cannot be averaged away.

---

## JPFA `total share`, Q3 2023 to Q1 2026 — a stale outstanding count

**Origin:** manual labelling. The sheet holds shares OUTSTANDING, which is right, but one
value was carried forward across eleven columns after the figure changed.

**Found by:** the full-corpus pass. All eleven cells scored `wrong` by 7.361.200 shares.

**What was wrong:** `C13` through `M13` held **11.620.308.701**, which is the outstanding
count for Q1 and Q2 2023 (11.726.575.201 issued less 106.266.500 treasury). JPFA sold part
of its treasury holding during 2023: from Q3 2023 the shareholder table prints treasury
98.905.300 and "Total saham beredar **11.627.669.901**". The 2022 columns (`P13`–`S13`,
11.726.575.201) and Q1/Q2 2023 were already correct.

**Consequence if left:** `total_share` is the denominator of EPS, BVPS, PBV and PE, so
eleven quarters of four ratios each carried a 0.06% bias — small enough to look like
rounding, which is exactly why it survived.

**Fixed:** 55 cells — `C13`–`M13` set to 11.627.669.901, and the ratio rows 15, 19, 20 and
21 recomputed. JPFA now has **no wrong cells** (177/180; the three remaining are 2022
periods the extractor withheld).

**Guard added:** none needed in the sheet. The extractor already reads this from the
shareholder table rather than the equity header — see the README section *total_share is
the count outstanding*.

---

## GTRA `utang_bank` Q2 2024 (`J8`) — the same row counted as both halves of its own label

| Cell | Was | Now |
|---|---:|---:|
| `J8` | 37,345,679,090 | **18,672,839,545** |

**Origin:** manual labelling, and it PREDATES the column shift. In the sheet as it stood
before that repair, 37.345.679.090 sat in `L8` — the column headed Q4 2023, which under the
two-column shift was the slot carrying Q2 2024's figures. The repair moved the wrong value
to the right place; it did not create it.

**Found by:** the corpus re-score after the shift was fixed. GTRA went from 117 wrong cells
to exactly one, and that one was wrong by a factor of precisely 2.000 — a ratio that is
never a misread and almost always an arithmetic mistake.

**What was wrong:** row 8 is labelled *"Utang Bank SAJA Jangka Pendek + Panjang jatuh
tempo"* — two terms. GTRA's Q2 2024 balance sheet prints only the second one:

```
Liabilitas jangka panjang yang          Current maturities of
  jatuh tempo dalam satu tahun:           long-term liabilities:
    Pinjaman bank    13   18.672.839.545   17.149.123.737    Bank loans
```

There is no short-term bank loan line at all, and note 13 (page 73) confirms it:
115.849.035.609 of bank debt, split 18.672.839.545 current and 97.176.196.064 non-current.
The same 18.672.839.545 was taken as both terms of the definition and added.

**Cross-check that fixes the date as well as the figure:** the comparative column on that
same page is 17.149.123.737, which is exactly what `L8` (Q4 2023) now holds. The two
columns of one printed row sit in the two adjacent cells of the sheet, as they should.

**Consequence if left:** `utang_bank` is one of the ten scored fields, so the extractor was
scored as wrong on a figure it had read correctly — and the other fourteen GTRA periods
agree with the filings exactly, so a single doubled cell would have looked like a model
defect rather than a labelling one.

**Guard that already existed:** `derive_fields()` warns *"utang_bank from one component
only"* precisely because a filing printing one half of this definition is a trap. The code
was built not to make this mistake; the label made it.

---

## GTRA Q3 2022 and Q2 2022 (`Q4:R13`) — leftovers the shift repair could not fill

**Origin:** the column-shift repair. Values were moved two columns left for every column
from `B` to `P`, but `Q` and `R` had no source to move from: their correct contents would
have come from `S` and `T`, which were already empty. They therefore kept their pre-shift
values, which are exact duplicates of `O` and `P` — the figures of Q1 2023 and Q4 2022.

**Found by:** reading across the repaired sheet row by row. `Q4` equalled `O4`, `R4`
equalled `P4`, and the same held for all ten scored rows — ten consecutive quarters of
identical figures, which no company produces.

**Evidence:** the archive has no filing for Q3 2022 or Q2 2022 (GTRA has 15, from Q4 2022
onward), and column `S` was empty before the repair, so no column ever held those periods'
figures. There is nothing to move into `Q` and `R`.

**Consequence if left:** nothing today — with no filing, those columns are never scored.
The day a Q3 2022 filing is added, it would have been scored against Q1 2023's figures and
failed on every field, for a reason invisible in the output. That is the same failure the
ticker guard exists to prevent, one column over.

**Fixed:** `Q4:R13` emptied — 20 cells, values removed, styles and the shared formulas in
rows 15–22 untouched (verified by reading every cell of all three sheets before and after:
exactly those twenty differ, and all twenty are now empty).

**Result of both fixes:** GTRA scores **147/150 with no wrong cells** (three fields the
extractor withheld), and the corpus stands at **98.9% (2204/2229)** with ten wrong cells
left — every one of them the extractor's own.

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

---

## APEX columns shifted one quarter (proposed 2026-11-10, approved by the user 2026-11-17)

**Found by:** `scripts/evaluate_output.py --ticker APEX` -- 14/170 labelled cells agreed
with the extraction, and every period column of the label sheet matched the extraction
of the PREVIOUS quarter on all ten fields (e.g. column "Q3 2026" aset 4.512.312.979.200
= the Q2 2026 filing; column "Q2 2022" = the Q1 2022 filing; Q1 2022 empty). The PDFs
are filed correctly: each prints the quarter-end its file name says
(`organize_filings.identify`: Q1 2022 -> 2022-03-31, Q2 2022 -> 2022-06-30,
Q2 2024 -> 2024-06-30, Q2 2026 -> 2026-06-30).

**Change:** rows 4-13 of columns B-T moved one column to the right (B->C ... S->T),
190 cells; B4:B13 (Q3 2026, no filing yet) emptied. Row 14 (Harga saham) is priced per
its own header and is not moved.

**Evidence after the change:** 180/180 cells equal the extraction, and all 180 extracted
figures are printed in their filing as the first figure on their line (current period).

**Note:** the old labels were identical to the extraction down to the FX rate, i.e. they
were pasted from the pipeline's CSV rather than read from the filings. They are
therefore not independent ground truth for APEX; agreement with them measures the
extractor agreeing with itself. A spot check of some cells against the PDFs by a person
is advised.

**Consequence if left:** 156 correct extractions scored as wrong, and every APEX ratio
(BVPS, ROA, ROE, PBV, PE, EPS, DER) computed on the wrong quarter's balance sheet and
priced at a date one quarter late.

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
