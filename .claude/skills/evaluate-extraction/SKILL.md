---
name: evaluate-extraction
description: Act as the evaluator of a pipeline run - check every cell the PDF-to-Excel pipeline produced against the user's ground-truth workbook AND against the PDF itself, decide for each disagreement whether the extractor or the label is wrong, fix the extractor (code, test, rerun) or propose the label correction, and report a before/after scorecard. Use after every run of scripts/pdf_to_excel.py (the pdf-to-excel skill calls it), and whenever the user asks to check, evaluate, verify or "cek" an issuer's extraction results, CSV or workbook.
---

# Evaluating a pipeline run

The user runs the pipeline; you are the evaluator. Your job after every run is to say,
with evidence, how many cells are right, which are wrong, **who** is wrong for each one
(the extractor or the label), and to fix what can be fixed. The label workbook is
evidence, not truth: `data/ground_truth/CORRECTIONS.md` lists dozens of labels that
were wrong (shifted columns, comparative figures, a thousandfold scale). The PDF is the
final arbiter.

Reply in Indonesian. Read `docs/CHECKPOINT.md` first if this session has not.

## 1. Gather the evidence (deterministic, no model)

```bash
source .venv/bin/activate
python scripts/evaluate_output.py --ticker AKRA            # several: --ticker AKRA ENRG
python scripts/evaluate_output.py --ticker AKRA --periods Q1_2023 Q2_2023
```

For every cell of `~/FinancialReport/<T>/<t>.csv` it reports: agreement with
`data/ground_truth/<T>.xlsx` (tolerance 1e-4, as `run_eval.py`), and where the pipeline's
figure and, when they disagree, the label's figure are printed in the filing (page, line,
reading: IDR/USD at full/thousands/millions, and whether it is the first figure on its
line). Output: `output/evaluation/<T>_<date>.md` (cells to decide) and `.json` (all).

Statuses: `correct`; `no_label` (printed, unlabelled); `wrong:<kind>` (`scale_1e3`,
`currency_conversion`, `sign`, `near_miss`, `hallucinated`, `value`); `missed` (blank,
label exists); `check_unprinted` (no label, figure not found in the text);
`blank_no_label`.

## 2. Decide every flagged cell against the PDF

The hint in the report is where to look first, never the verdict. For each cell:

1. Open the page it names (`pdftext.page_texts(pdf, [page-1])`); for a scanned page or
   a layout the text mangles, render it (`extract.render_pdf_page_to_image(pdf, page-1)`, save the PNG and read it, or the
   agent's `read_page_image`) and look.
2. Read what is printed for **the current period, the consolidated statement, the
   parent-attributable line** where the field says so (field definitions:
   `src/prompts.py`, `AUDIT_FIELD_RULES`; past decisions: CHECKPOINT and
   CORRECTIONS.md - e.g. pendapatan = the printed revenue-block total, JUMLAH/Total
   Pendapatan/Sub-total, when the filing prints one).
3. Put the cell in exactly one bucket:

| Bucket | Meaning | Action |
|---|---|---|
| extractor wrong | the PDF prints something else for this field and period | fix the cause (step 3) |
| label wrong | the pipeline matches the PDF, the label does not | propose a correction (step 4) |
| convention | both figures are defensible readings (which line counts as revenue, issued vs outstanding shares) | ask the user once, record the decision in CHECKPOINT, then apply it everywhere |
| filing issue | the filing itself is inconsistent or lacks the item | report; the warning in the CSV should say so |
| price | `harga_saham` differs | Yahoo close vs label; report, never "fix" a label from Yahoo silently |

**Never claim the PDF lacks something until you have looked at the pages.** A figure not
found in the text layer may be printed under a misleading header (ENRG Q1 2023's cash-flow
page is titled "CATATAN ATAS LAPORAN KEUANGAN"), split across lines by a bilingual
layout, or on a scanned page.

## 3. Fixing the extractor

- Find the **cause**, not the cell: page selection (`src/page_select.py`), scale/FX
  (`src/normalize.py`), prompt rule (`src/prompts.py`), a validation/repair guard
  (`src/validate.py`, `src/extract.py`). A per-filing special case is not a fix.
- Add a test with the real text shape (`tests/test_guards.py` and friends); the ENRG fix
  first failed on the real PDF because the test used a one-line heading.
- Measure the change on the archive before trusting it: run the old and new code over
  every PDF in `~/FinancialReport/*/` and `data/raw/` and list what changed (scale
  detection, page selection). Anything that changed and was not meant to is a regression.
- Rerun only the affected filings, then re-evaluate:
  ```bash
  python scripts/pdf_to_excel.py --ticker AKRA --refresh Q1_2023 Q2_2023
  python scripts/evaluate_output.py --ticker AKRA
  ```
- Full test suite (`python -m pytest -q`, ~20 min) before reporting.

## 4. Correcting a label

Labels are the user's. **Never edit `data/ground_truth/*.xlsx` without their approval.**
Propose a table: cell, period, field, label, proposed value, evidence (page and the
printed line). On approval, add the batch to `scripts/apply_label_corrections.py` with
its own flag and an entry file `scripts/label_corrections_<date>_<name>.md` (the
`--akra-scale` batch is the model), dry-run it, and give the user the `--apply` command
(writing xlsx may be blocked for you). The entry must land in
`data/ground_truth/CORRECTIONS.md`. See the `label-groundtruth` skill.

## 5. Report

- Scorecard per ticker: `correct/labelled` vs GT and filled/total, **before and after**
  your fixes, each number from a real run of `evaluate_output.py`.
- Every remaining flagged cell with its bucket and evidence.
- What you changed (code, tests, rerun filings, CSV/workbook rows) and what awaits the
  user (label approvals, convention questions).
- Add a checkpoint entry to `docs/CHECKPOINT.md`; update "Status sekarang" and
  "Pekerjaan tertunda". Do not commit.

## Rules

- Every number you report comes from a run; otherwise say "not measured".
- Labels: approval first, CORRECTIONS.md always.
- Model quota: stop and say so; no other keys, accounts or projects.
- Re-extraction costs model calls: `--refresh` the affected periods, not `--force`,
  unless the user agrees.
