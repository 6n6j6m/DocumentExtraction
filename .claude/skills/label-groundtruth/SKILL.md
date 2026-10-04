---
name: label-groundtruth
description: Build and audit ground truth for the financial-statement eval set. Use when labelling a new period or issuer, correcting an existing label, or auditing the spreadsheet against the filings. Keeps labelling independent of the model under evaluation and records every correction to an audit log.
---

# Ground-truth labelling and audit

Ground truth is the foundation the whole scorecard rests on. If it is wrong, every
metric is wrong in a way no amount of care elsewhere can recover. This skill records
the rules that labelling has to follow here, and the audit trail that makes "ground
truth you can trust" a checkable claim rather than an assertion.

## The rule that matters most

**Never let the model under evaluation write its own ground truth.**

A label copied from an extraction — even a correct-looking one — turns the scorecard
into a measurement of the model agreeing with itself. Labels are read from the filing
by a person, or by a *different and stronger* model whose output is then checked
field by field against the printed page before it is accepted. A pre-filled value is
a form to correct, never an answer.

The same applies to the prompt: no figure from a filing in the eval set may appear as
an example in `src/prompts.py`. Placeholder digits (`111.111.111`, `222.222.222`) are
used there for exactly this reason.

## Where ground truth lives

`data/ground_truth/<TICKER>.xlsx`, sheet `Sheet1`:

- **Cell `D1`** names the issuer. `scripts/run_eval.py` refuses to score a run whose
  `--ticker` disagrees with it — these workbooks are made by copying an existing one,
  and a copy that was never re-labelled would otherwise score one issuer against
  another's figures.
- **Row 3** holds the period headers: `Q1 2022`, `Q2 2022`, `Q3 2022`, and
  `TAHUNAN <year>` for the annual (Q4) report, whose figures are cumulative.
- **Rows 4–13** are the scored fields, mapped by `EXCEL_ROWS` in `src/schema.py`. The
  sheet is the system of record for field naming: if a label in column A is edited,
  edit `EXCEL_ROWS` to match rather than renaming the field.
- Values are stated in **full Rupiah**. An empty cell means *not yet labelled* and is
  excluded from scoring — it is not an assertion that the figure is absent.

## Labelling a period

1. **Open the filing itself**, not a summary or a previous year's sheet.
2. **Read the current-period column.** Consolidated vs parent-entity, and
   current-period vs comparative, are the two easiest columns to take by mistake.
   *Check the column header date, not the row position.* This is the single most
   common labelling error, and it is also the extractor's most common failure — so a
   mistake here can silently agree with a wrong extraction.
3. **Take the parent-attributable subtotal** for `ekuitas` and `laba_bersih`, per the
   sheet's own header, `(HANYA YANG BISA DIATRIBUSIKAN KE ENTITAS INDUK SAJA)`. Where
   non-controlling interest is negative the parent share is *larger* than the printed
   total — the opposite of the usual intuition, and the source of a real error already
   logged in `CORRECTIONS.md`.
4. **Note the scale and currency printed in the header** before converting anything.
   A missed "dalam ribuan" is a 1000x error in every figure on the page.
5. **Record how the figure reached full Rupiah.** For an issuer reporting in USD the
   conversion uses the rate the filing itself discloses (see `src/normalize.py`), so
   the label and the pipeline share a rate. That makes the converted comparison
   non-independent, and the README says so; do not present it as a test of conversion.

## Log every correction

Any change to a label after it was first entered goes in
`data/ground_truth/CORRECTIONS.md`, one entry per cell, with:

- the cell reference, the old value and the new one
- **origin** — where the wrong value came from (manual labelling, an import, a
  pre-fill)
- **found by** — what surfaced it, which is what shows the audit was real
- **evidence** from the filing, with the page
- **consequence if left** — which downstream metrics the error would have biased
- any **guard added** so the same class of error is caught next time

The existing ARCI `ekuitas` entry is the worked example to follow.

## Auditing with the agent

`scripts/audit_labels.py` re-reads the filings to check the labels (see the README section
"Auditing the ground truth with an agent"). Its rules follow from this skill's:

- **The auditor is never the evaluated model.** It refuses to start if `AUDIT_MODEL` or a
  fallback equals `GEMINI_MODEL`.
- **The reading is blind.** The first conversation is never shown a label.
- **A proposal is a form, not a label.** `PROPOSED_CORRECTIONS.md` is written in the
  format below; nothing edits a workbook. Check each entry against the filing, edit the
  workbook by hand, and move the entry into `CORRECTIONS.md` with "Found by: agentic label
  audit".
- **Score the auditor before trusting it**: `scripts/audit_benchmark.py` measures it on
  the errors `HEAD` still carries and on planted ones.

## Invariants to preserve

- The sheet names its own issuer in `D1`, and it matches the filename.
- Empty means unlabelled, not absent. If a filing genuinely does not report a field,
  say so in `CORRECTIONS.md` rather than leaving an ambiguous blank cell.
- A label is never adjusted to make the scorecard look better. If a label and an
  extraction disagree, the filing is the tiebreaker, and whichever loses gets fixed.
