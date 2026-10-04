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
