
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
