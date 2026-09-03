# Ground-truth corrections — ARCI

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
