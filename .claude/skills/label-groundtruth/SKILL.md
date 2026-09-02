---
name: label-groundtruth
description: Build and audit ground truth for the document-extraction eval set. Use when labelling a new document, reviewing a pre-filled stub, or auditing an imported label from a public dataset. Enforces the separation between the pre-fill model and the evaluated model, and records every correction to an audit log.
---

# Ground-truth labelling and audit

Ground truth is the foundation the whole scorecard rests on. If it is wrong,
every metric is wrong in a way no amount of care elsewhere can recover. This
skill exists to make labelling fast enough that it actually gets done, without
making it circular.

## The rule that matters most

**Never let the model under evaluation write its own ground truth.**

Pre-filling runs on `LLM_MODEL_STRONG`; the system being scored runs on
`LLM_MODEL`. If they are the same, the scorecard measures the model agreeing
with itself. `scripts/prefill_groundtruth.py` refuses to run when they match —
do not work around that check.

A pre-filled stub is a **form to correct**, not an answer. Read every field
against the image before accepting it.

## Workflow

### 1. Pre-fill a stub

```bash
python scripts/prefill_groundtruth.py data/raw/<doc>.<ext> --source own
```

Writes `data/ground_truth/_stubs/<doc>.json` plus a `.transcription.txt`.
Nothing lands in `data/ground_truth/` yet.

### 2. Review against the document

Open the image or PDF and check each field. Look specifically for:

- **Absent vs missed.** If the document has no invoice number, the value is
  `null` *and* the field stays out of `_unlabelled`. `null` is a positive
  assertion of absence, and the evaluator scores it as such. Only put a field
  in `_unlabelled` when you have not determined the truth — then it is
  excluded from scoring instead of being scored against a guess.
- **Values as printed.** Keep `"15.000"`, not `15000`. Normalisation happens
  in one place (`src/normalize.py`) so that ground truth and predictions are
  parsed identically. Pre-normalising here breaks that.
- **Line-item order.** Must follow the printed order.
- **Scale.** Financial statements often print "in millions". The ground truth
  records what is printed, and the units field carries the scale.
- **Which column.** On financial statements, consolidated vs parent-entity and
  current-period vs comparative are the two easiest columns to take by
  mistake. Check the column header, not the row position.

### 3. Log every correction

```bash
python scripts/log_correction.py <doc_id> <field> "<was>" "<now>" "<reason>" --origin prefill
```

Use `--origin cord-v2` when correcting an imported public-dataset label. Those
entries are the most valuable ones in the repo: they are direct evidence that
the imported labels were audited rather than trusted, and the README cites the
count.

### 4. Promote to ground truth

Set `"_reviewed": true`, add `_reviewer_notes` if anything was ambiguous, then
move the file into `data/ground_truth/`.

```bash
mv data/ground_truth/_stubs/<doc>.json data/ground_truth/
```

## When labelling by hand instead

For a blind-labelling subset — used to check that the pre-fill process is not
biasing the labels — skip step 1 entirely, write the JSON directly, and set
`"_prefill_model": null`. Comparing blind labels against pre-fill-corrected
labels on the same documents is what justifies trusting the rest.

## Invariants to preserve

- `_doc_key` is the record identifier and matches the source filename stem.
- `document_id` is a *field* — the number printed on the document — and is
  never set to the filename.
- A field is either labelled (a value or `null`) or in `_unlabelled`. Never
  both, never neither.
