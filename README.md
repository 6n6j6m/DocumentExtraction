# Financial Statement Extraction — IDX Quarterly Filings

Extracts a fixed schema of financial figures from Indonesian Stock Exchange (IDX)
filings, normalises them to full Rupiah, and scores the result against audited
ground truth.

Working document set: **PT Archi Indonesia Tbk (ARCI), Q1–Q4 2022** — four filings
of 121–123 pages each, bilingual (Indonesian | English) in side-by-side columns,
reported in **US Dollars** while the comparison set is in Rupiah.

**Current result: 40/40 fields correct** across four periods (`gemini-3.1-flash-lite`,
image mode), with **11/11 fault-injection tests** passing. Scorecard committed at
`output/scorecard_gemini_gemini-3.1-flash-lite_image.json`.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then add GEMINI_API_KEY

# extract one filing
python src/extract.py data/raw/Q1_2022_ARCI.pdf

# full evaluation against ground truth
python scripts/run_eval.py

# a subset, or a specific provider
python scripts/run_eval.py --periods Q1 Q2
python scripts/run_eval.py --provider ollama
python scripts/run_eval.py --no-cache --tolerance 0.001

# catch a regression before shipping (exit 1 if any field got worse)
python scripts/compare_runs.py output/scorecard_A.json output/scorecard_B.json

# prove the guards fire: 11 fault-injection tests
python -m pytest tests/ -v          # or: python tests/test_guards.py
```

### What a single extraction prints

```
=== AS PRINTED ===        the figures as the filing states them
=== CONFIDENCE ===        per-field score, grounding, abstentions
=== IN FULL RUPIAH ===    after scale and FX, with the rate and the line it came from
```

```
=== CONFIDENCE ===
  period_end_date                 0.85  -
  currency                        0.85  -
  aset                            1.00  grounded
  liabilitas                      1.00  grounded
  utang_bank                      1.00  -
  total_ekuitas                   1.00  grounded
  ...
```

| Mark | Meaning |
|---|---|
| `grounded` | the figure was found verbatim in the page's text layer |
| `NOT IN TEXT` | absent from the filing — almost certainly invented |
| `ABSTAINED` | below threshold; the value was **removed** from the output |
| `-` | not verifiable verbatim (metadata, or a derived value) |

Metadata sits at 0.85 by construction: `currency` is inferred from "Disajikan dalam
Dolar Amerika Serikat" rather than printed as a token, and dates are reformatted to
ISO — neither can be matched verbatim, so neither is fully trusted nor penalised.

Running fully local instead:

```bash
ollama serve
ollama pull qwen3-vl:8b
LLM_PROVIDER=ollama python src/extract.py data/raw/Q1_2022_ARCI.pdf
```

Predictions are cached per provider under `output/predictions/<provider>_<mode>/`,
so re-running to inspect results costs no API calls. `--no-cache` forces a fresh
extraction.

---

## Dataset, and why this one

Public IDX filings, downloaded as published. They were chosen because they are
awkward in ways that matter:

| Property | Why it makes the problem real |
|---|---|
| 121–123 pages | The four statements occupy ~8 pages; the rest is notes |
| Two-column bilingual layout | Flattened text interleaves Indonesian and English |
| Comparative columns | Every figure sits beside a prior-period figure |
| Reported in USD | Must be converted to IDR to sit beside Rupiah filers |
| Three rows labelled "Utang bank" | Distinguished only by the section heading above them |
| Negative non-controlling interest | Parent-attributable equity is *larger* than total equity |
| One rotated page per filing | Its text layer extracts as ~330 unusable fragments |

Ground truth lives in `data/ground_truth/ARCI.xlsx`, one column per period. It was
labelled by hand from the filings and is stated in full Rupiah.

## Schema

Eleven scored fields, mapped to spreadsheet rows by `EXCEL_ROWS` in `src/schema.py`
so the sheet stays the single source of naming:

`aset` · `total_aset_lancar` · `kas` · `liabilitas` · `utang_bank` · `ekuitas` ·
`pendapatan` · `laba_bersih` · `kas_dari_aktivitas_operasi` · `total_share` ·
`period_end_date`

Plus metadata (`currency`, `reporting_scale`, `statement_scope`) and four
**component fields** the model is asked for instead of the values they combine into
— see *Ask for components, not conclusions* below.

---

## Architecture

```
PDF (122 pages)
   │
   ├─ page_select.py    keyword scan of each page's title region (first 250 chars)
   │                    → 8 pages   [93.4% fewer pages]
   │                    → grouped: balance_sheet / income / cash_flow
   │
   ├─ extract.py        one call PER STATEMENT, asking only for that
   │                    statement's fields
   │      ├─ image mode → render pages, send all of a group's images together
   │      └─ text mode  → text layer, condensed, page markers preserved
   │
   ├─ llm.py            provider layer: Gemini (REST) | Ollama (local)
   │                    JSON forced at the API level, not just requested
   │
   ├─ derive_fields()   utang_bank = short-term + current-maturity components
   │                    ekuitas    = total equity − non-controlling interest
   │                    + balance-sheet identity check
   │
   └─ normalize.py      scale (FULL/THOUSANDS/…) × FX rate read FROM THE FILING
                        → full Rupiah
```

### Why a single well-designed call per statement, not an agent

The pages are known before any model runs, the field list is fixed, and the output
is one flat JSON object. There is nothing for an agent to decide at runtime, so a
planning loop would add latency and failure modes to buy nothing. What the problem
actually needed was **narrower calls**, not smarter control flow — see the measured
effect below.

---

## Key decisions and trade-offs

### Ask for components, not conclusions

The two fields the model kept getting wrong were the two requiring *selection* and
*arithmetic* rather than reading:

- **`utang_bank`** — three balance-sheet rows are labelled `Utang bank`. Two belong
  in the total; the third (non-current) does not. They are told apart only by the
  section heading several lines above.
- **`ekuitas`** — the printed rows are `Total Ekuitas` and `Kepentingan
  Non-Pengendali`. The wanted value is the difference, and the NCI is negative here,
  so the answer is *larger* than the printed total.

Neither is now asked for. The model reports the four atomic rows; the combination
happens in `derive_fields()`. This changed the task from "pick two of three
identically-labelled rows and add them" to "copy the number beside this label".

Two secondary benefits: the arithmetic is exact, and a wrong answer localises to
*one misread row* instead of an opaque total. If the model volunteers the combined
value anyway, it is cross-checked against the components and the components win,
with a warning.

**Trade-off:** four extra fields to extract, and the schema no longer mirrors the
output one-to-one.

### The exchange rate comes from the filing, not from an API

ARCI reports in USD; the comparison set is in Rupiah. Rather than call an FX
service, `normalize.py` reads the rate the filing itself discloses:

```
1.000 Rupiah   0,0697        →  IDR per USD = 1000 / 0.0697 = 14,347.20
```

This keeps the conversion consistent with the numbers being converted, works
offline, and is auditable — every result carries the quoted line and page it came
from. Cross-checked against Bank Indonesia's middle rate:

| | From filing | BI middle rate | Δ |
|---|---:|---:|---:|
| Q1 | 14,347.2 | 14,349 | 0.01% |
| Q2 | 14,858.8 | 14,848 | 0.07% |
| Q3 | 15,243.9 | 15,247 | 0.02% |
| Q4 | 15,723.3 | 15,731 | 0.05% |

Differences are the filing's own 4-decimal rounding. A fallback derives the rate
from a disclosed `Rp… (US$…)` pair when the rate table is absent, and says so.

**Trade-off:** a filing that discloses no rate cannot be converted. It raises rather
than substituting a guessed rate — a plausible wrong number is worse than a refusal.

### Never convert what is not money

`total_share` is a share count. Scaling or FX-converting it silently corrupts every
per-share metric downstream by a factor of ~14,000. It is carried through
`normalize.py` untouched, by name.

### Confidence is computed, not self-reported

`src/confidence.py` scores every field from three signals the system can check
itself. A model's own stated confidence is not one of them — it is poorly
calibrated and free to inflate.

| Signal | Weight | What it asks |
|---|---:|---|
| **Grounding** | 0.60 | Does this exact figure appear in the filing's text layer? |
| **Validation** | 0.25 | Is the field implicated in a failing structural rule? |
| **Derivation** | 0.15 | If computed, how good were the rows it came from? |

**Grounding is the anti-hallucination test.** Every number is re-rendered in
Indonesian format (`694671337` → `694.671.337`, negatives as `(76.732)`) and
searched for in the page text. A figure the document does not contain was invented.

This works in image mode too, and is *stronger* there: the extractor reads pixels,
the verifier reads characters, so agreement is genuine corroboration rather than the
same read performed twice.

A field implicated in an **error-severity** rule is capped at 0.50 — below the
abstention threshold — because such a rule does not hint that a value is doubtful,
it demonstrates that the value disagrees with the document.

Derived fields are graded on their **components**, not themselves: `utang_bank` is a
sum, so it is correctly absent from the filing, and testing it verbatim would punish
the right answer.

Below `CONFIDENCE_ABSTAIN_THRESHOLD` (default 0.55) the value is **removed**, not
merely flagged — a low-confidence number left in the output gets used by whatever
reads it next.

Observed behaviour:

| Scenario | Result |
|---|---|
| Correct extraction | nothing abstained |
| `kas` replaced with an invented figure | `kas` abstained (not in text) |
| Bank debt read from the non-current row | `utang_bank` + component abstained |
| Balance sheet does not balance | all three implicated fields abstained |

### Validation that needs no ground truth

`src/validate.py` runs the checks a reader could make with only the filing: the
balance-sheet identity, containment (`kas ≤ total_aset_lancar ≤ aset`), component
sums, sign sanity, whole-number share counts, recognised currency and scale.

One rule needs the document itself. Grounding cannot catch a value copied from the
**wrong but real** row — the number is genuinely printed, so it verifies. Only its
position distinguishes it. Since three rows read `Utang bank` and differ only by the
section heading above them, `validate_against_document()` reconstructs which amount
sits under which heading and checks the extracted components against it. That is the
system's most likely failure, so it is tested directly rather than hoped about.

---

## Evaluation

`scripts/run_eval.py` reads the spreadsheet column for each period, runs extraction,
normalises to Rupiah, and compares field by field.

Design points that matter:

- **Two comparisons, deliberately not merged.** As-printed (USD) isolates *extraction*
  error; converted (IDR) adds *conversion* error. A field right in USD but wrong in
  IDR is a scale or rate bug, not a misread row — one number cannot say which.
- **Tolerance is 0.01% by default.** Loose enough for float residue, tight enough to
  catch a wrong-but-similar row. At 1% the equity error described below survives
  undetected.
- **Statuses are distinct:** `correct` / `wrong` / `missed` / `no_truth`, and a
  `missed` caused by deliberate abstention is counted separately from one where the
  model simply returned nothing.
- **Every wrong answer is classified by kind**, because counting failures is not
  understanding them. A scale bug, a comparative-column read and an invented number
  all score as "wrong" but have different causes and different fixes:

  | Kind | Detected by |
  |---|---|
  | `wrong_scale_1e3/6/9` | ratio to truth is a power of a thousand |
  | `wrong_currency_conversion` | ratio falls in the plausible IDR/USD band |
  | `wrong_sign` | ratio ≈ −1 |
  | `hallucinated` | value is not printed anywhere in the filing |
  | `wrong_near_miss` | within 5% — a neighbouring row or the comparative column |
  | `wrong_value` | none of the above |
- **Exit code 1 when anything is `wrong`**, so it can gate CI.
- **Per-provider, per-mode scorecards.** `scorecard_<provider>_<model>_<mode>.json` —
  without the mode in the name, a text run and an image run overwrite each other and
  the comparison silently becomes a run compared with itself.

### Results

`gemini-3.1-flash-lite`, image mode, Q1–Q4 2022:

```
correct   40      wrong   0      missed   0
accuracy  100%  (40/40)
```

### Catching a regression before it ships

`scripts/compare_runs.py` diffs two scorecards **per field, per period**, and exits 1
on any `correct → not-correct` transition regardless of the totals.

Aggregate accuracy is the wrong gate: a change that fixes three fields and breaks two
looks like a net gain, but shipping it means two fields that used to be right are now
wrong. On a test pair where accuracy *improved* by one field, the tool still fails
the build:

```
REGRESSIONS
  Q1 kas                    correct -> wrong
changes in the other direction
  Q1 ekuitas                missed -> correct
  Q1 utang_bank             wrong -> correct
              baseline  candidate   delta
  correct            2          3      +1
✗ 1 regression(s) - do not ship
```

It also reports fields that are *still wrong but failing differently* — a changed
failure kind means the cause moved even though the count did not — and flags when
the two runs cover different field sets, since that makes their totals incomparable.

`correct → abstained` is reported as a coverage loss rather than a regression by
default (it is not a wrong answer shipped to a user); `--fail-on-new-abstention`
makes it gate too.

### Proving the guards actually do something

A scorecard cannot demonstrate that validation, grounding and abstention work: the
clean path already scores 40/40, and a build with all three deleted would score
identically. Safety machinery is only observable when something goes wrong.

`tests/test_guards.py` therefore breaks one specific thing per test and asserts that
the right guard fires — 11 tests, runnable with or without pytest:

```
PASS  test_correct_extraction_passes_cleanly            no false positives
PASS  test_hallucinated_value_is_caught                 invented figure -> abstained
PASS  test_wrong_but_real_row_is_caught                 wrong row, genuine number
PASS  test_unbalanced_balance_sheet_is_caught
PASS  test_containment_violation_is_caught
PASS  test_fractional_share_count_is_caught
PASS  test_derived_field_is_not_punished_for_being_absent
PASS  test_fx_rate_comes_from_the_filing
PASS  test_share_count_is_never_converted
PASS  test_usd_without_a_rate_refuses_rather_than_guesses
PASS  test_failure_kinds_are_distinguished
11/11 passed
```

The first two are a pair, and both are needed. One proves the guard fires when the
input is broken; the other proves it stays quiet when the input is right. Without the
second, a "guard" that rejects everything would also pass.

`test_wrong_but_real_row_is_caught` is the hard one: `184.336.390` *is* printed in the
filing, so grounding verifies it happily. Only the section heading above it says it
is the wrong row.

`test_derived_field_is_not_punished_for_being_absent` guards against a bug that
actually occurred — grading `utang_bank` on its own grounding abstained on the
correct answer, because a sum is legitimately absent from the document.

### The harness found an error in the ground truth

While cross-checking, the balance-sheet reconstruction disagreed with the labels on
`ekuitas` for Q1 and Q2 by 0.03%. The filings were the tiebreaker: those two cells
had been labelled with `Total Ekuitas` instead of the parent-attributable subtotal,
while Q3 and Q4 used the correct one — an inconsistency *within* the ground truth.

Because NCI is negative in these filings, the correct value is *larger* than the
printed total, which is the opposite of the usual intuition and why the error was
easy to make and easy to miss. Both cells were corrected before the run above.

This is the argument for the tight tolerance: a 0.03% discrepancy is invisible at
any looser setting, and it was a real error.

---

## Production notes

### Optimisations, with measured impact

| Change | Effect |
|---|---|
| Page selection by title keyword | 122 pages → 8 (**93.4% fewer**) |
| One call per statement, narrowed field list | local model **10/14 → 18/18 fields** |
| Group pages into one call (image mode) | **8 requests → 3** per document |
| Drop rotated pages, keep only number-bearing lines + neighbours | text **−25%** (18,467 → 13,857 chars) |
| Size `num_ctx` to the actual input | KV cache **16,384 → 8,192** |

The second row is the one that mattered. A 7B local model given 18 fields across 7
pages answered the first few and quietly dropped the rest; given 4–13 fields across
2–3 pages it answered all of them. The fix was scope per call, not a bigger model.

### Latency

Measured locally (`qwen2.5:7b-instruct`, text mode, single call):

```
load 0.0s | prompt 26.2s (7,700 tok, 294 tok/s) | generate 37.6s (492 tok, 13.1 tok/s) | total 64.1s
```

The Ollama path reports this breakdown on every call, so slowness can be attributed
rather than guessed: a large `load` means a cold model, a large `prompt` means too
much input, a low generate rate means the model is too big for available RAM.
`keep_alive=15m` keeps weights resident so only the first document pays the load.

### Resilience

- **Provider failures are classified.** `LLMUnavailable` (rate limited, unknown model,
  server down, no key) abandons that provider immediately; `LLMError` (one bad page,
  malformed JSON) continues. On a 429 this is the difference between one wasted call
  and eight — and retrying a throttle deepens it.
- **A 404 lists what is available.** An unknown `GEMINI_MODEL` triggers `ListModels`
  and the error names the valid ids instead of sending you back to the docs.
- **Text models are refused images.** With `OLLAMA_INPUT_MODE=image`, the provider
  asks `/api/show` whether the model can see. A text model handed images does not
  error — it ignores them and answers from the prompt, producing well-formed wrong
  numbers. That failure is caught before the call.
- **JSON is enforced at the API level** (`responseMimeType` / Ollama `format: json`),
  with fence-stripping and outermost-object recovery as backstops.
- **The balance sheet is checked** — `aset − (liabilitas + total ekuitas)` — which
  catches a misread without needing ground truth.

---

## Agentic development

This system was built with Claude Code across one long session, working directly
against the repo on a linked machine.

What worked: giving it the filings and asking it to *verify* rather than *assume*.
Every claim in this README that carries a number came from a script run against the
actual PDFs — the page grouping, the FX cross-check, the −25% condensation, the
ground-truth audit. Several defects surfaced only because behaviour was tested
rather than reasoned about: duplicate function definitions left by successive
patches (the older one silently winning), and `FIELDS` missing the new component
fields, which dropped them between calls and left the derived values empty while
the output still looked valid.

**Custom extension:** `.claude/skills/label-groundtruth/SKILL.md`, a repo-local skill
that encodes the ground-truth labelling rules — values as printed rather than
pre-normalised, `null` as a positive assertion of absence versus `_unlabelled` for
"not yet determined", and the rule that the model under evaluation must never
pre-fill its own labels. Its column-selection warning ("check the column header, not
the row position") is exactly the failure the extractor hit later.

---

## Not built yet

Stated plainly because the brief asks for them:

- **Docker / `docker compose up`.** No Dockerfile or compose file. The eval runs as a
  local command, not as a one-shot container against a served API.
- **HTTP API.** Extraction is a library and a CLI; there is no service to bring up.
- **Calibration of the confidence scores.** The weights are reasoned, not fitted; the
  threshold has not been swept against the eval set to find where precision and
  coverage actually trade off.
- **Cross-provider agreement as a fourth signal.** Running two models and scoring
  disagreement is the obvious next input to confidence, and the provider layer
  already supports it.
- **Cost accounting.** Latency is measured on the local path; token cost per document
  is not tracked or reported.

## With more time

1. **Calibrate the abstention threshold** by sweeping it against the eval set and
   plotting precision against coverage, instead of choosing 0.55 by argument.
2. **A second ticker end to end** (TLDN, reported in Rupiah, thousands scale) to force
   the scale path to earn its keep; today only the USD/FULL branch is exercised.
3. **Scanned filings.** `ocr_pages()` is wired in but has never run on a real scan,
   because all four ARCI filings carry a clean text layer.
4. **The layout-aware text path.** `extract_text(layout=True)` preserves the
   indentation that distinguishes the three `Utang bank` rows; it costs +28% tokens
   and was not needed once components were extracted separately, but it is the next
   lever if another issuer's labels prove less regular.

---

## Repo layout

```
src/
  page_select.py   title-region keyword scan; groups pages by statement
  extract.py       orchestration, per-statement calls, derived fields
  llm.py           provider layer (Gemini REST / Ollama), JSON handling
  normalize.py     reporting scale + FX from the filing → full Rupiah
  validate.py      structural rules + section-anchored bank-debt check
  confidence.py    grounding/validation/derivation → per-field score, abstention
  schema.py        field definitions, EXCEL_ROWS mapping
  prompts.py       system + extraction prompts, per-field keyword rules
scripts/
  run_eval.py      scorecard generation, failure classification
  compare_runs.py  regression gate between two scorecards
tests/
  test_guards.py   fault injection; proves each guard fires (and stays quiet)
data/
  raw/             four ARCI filings
  ground_truth/    ARCI.xlsx (labels), TLDN.xlsx, JSON template
output/
  scorecard_*.json committed results from real runs
  predictions/     cached per provider and mode
.claude/skills/    label-groundtruth (custom agent skill)
```
