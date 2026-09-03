# Financial Statement Extraction — IDX Quarterly Filings

Pulls a fixed schema of ten financial figures out of Indonesian Stock Exchange filings —
100 to 170 page bilingual PDFs — normalises them to full Rupiah, scores the result
against hand-labelled ground truth, and **declines to answer when it is not confident**
rather than guessing.

**Two issuers are scored**, and they say different things:

| Issuer | Result | What it is |
|---|---|---|
| **ARCI** | **40/40** (100%) | USD, full units. The issuer this was developed against. |
| **JPFA** | **33/36** (91.7%) | Rupiah, millions. Never seen during development. |

JPFA is the more informative number. Nothing is scored `wrong` in either — but on JPFA
the system **declined to answer three times**, because one period's balance sheet does
not balance and it refused to assert figures it had grounds to doubt. That is the
behaviour this whole design argues for, and JPFA is where it first happened outside a
test.

**54 tests**, of which 25 break one specific thing each and assert the right guard fires.

**What is still not scored.** CPIN and EMAS are extracted and checked against what each
filing says about itself, but they have no labels. The distinction is kept sharp
throughout: a filing that validates is not a filing that was measured.

---

## Start here

Four ways in, in increasing order of what they need from you. Everything the commands
below refer to — the filings, the labels, the committed results — is in the repository, so
none of it has to be taken on trust.

| | Needs | Takes | Shows |
|---|---|---|---|
| **1. Run the tests** | Python only — **no API key** | ~90 s | That the guards, the confidence layer and the abstention logic do what this README says |
| **2. Extract one filing** | A free Gemini key | ~25 s | The system reading a real 122-page filing end to end |
| **3. Score it** | The key | ~4 min | Both issuers re-scored from scratch |
| **4. Docker** | Docker + the key | ~6 min | `compose up` serving the API, then **one command** that scores both issuers **against that API** |

### 1. Run the tests — no key required

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q
```

```
54 passed
```

Nothing here touches the network: `tests/test_api.py` stubs the provider, and
`tests/test_guards.py` works from the committed PDFs. This is the cheapest way to see
what the system actually guarantees — each test breaks one thing and names the guard that
should catch it. Start with `test_wrong_but_real_row_is_caught` and
`test_hallucinated_value_is_caught`.

### 2. Extract one filing

Get a free key from [Google AI Studio](https://aistudio.google.com/apikey), then:

```bash
cp .env.example .env          # put the key in GEMINI_API_KEY
python src/extract.py data/raw/Q1_2022_ARCI.pdf
```

Roughly 25 seconds and 3 API calls on the free tier. You should see page selection
narrowing 122 pages to 8, three per-statement calls, a confidence line per field, and the
figures converted to Rupiah using an exchange rate read out of the filing itself:

```
📄 Selecting pages from Q1_2022_ARCI.pdf...
  Pages: [5, 6, 7, 8, 9, 10, 11, 12] (1-indexed)
  Reduction: 8/122 pages (93.4% reduction)

🔍 gemini:gemini-3.1-flash-lite [image]...
  [balance_sheet] pages [5, 6, 7], 3 image(s), 1,247 KB   +13 field(s)
  [income]        pages [8, 9, 10], 3 image(s)             +2 field(s)
  [cash_flow]     pages [11, 12], 2 image(s)               +1 field(s)

=== USAGE ===
  3 LLM call(s) | select_pages 5.9s, read_text 0.3s, extract 9.9s
  tokens in 18019 / out 982

=== IN FULL RUPIAH ===
kurs: 14,347.20 IDR/USD  (disclosed_rate_table, hal. 29)
       "1.000 Rupiah 0,0697 0,0701 0,0686 1,000 Rupiah"
  aset                          9,966,590,200,861
```

Try the other issuers too — they are the more interesting documents:

```bash
python src/extract.py data/raw/Q1_2022_JPFA.pdf     # Rupiah, millions, two share classes
python src/extract.py data/raw/Q3_2025_EMAS.pdf     # no usable text layer; OCR path, slow first run
```

### 3. Score it — the full evaluation

**Without an API key**, from the predictions committed in this repository:

```bash
python scripts/run_eval.py
```

This calls no model at all. It reads the extraction results already in
`output/predictions/`, converts them to Rupiah, compares them field by field against
`data/ground_truth/ARCI.xlsx`, and writes a scorecard — the full 40/40, reproduced on your
machine in a few seconds. It is the fastest way to inspect what is actually being
measured: the tolerance, the four statuses, the failure taxonomy, the per-field errors.

What it cannot do is test a change, because nothing was re-extracted. For that:

```bash
python scripts/run_eval.py --ticker ARCI --no-cache      # 13 calls, ~2 min
python scripts/run_eval.py --ticker JPFA --no-cache      # 16 calls, ~2 min
```

Each writes its own scorecard, `output/scorecard_<TICKER>_<provider>_<mode>.json`. For
ARCI, expect:

```
SUMMARY
  correct       40
  wrong          0
  missed         0
  accuracy     100.0%  (40/40)

  usage
    LLM calls            13
    tokens              75151 in / 4071 out
    latency             18-26s per document
```

The `usage` block is measured, not estimated: both providers report their own token
counts. `cost` reads *unpriced* by design — see [*Cost*](#cost).

Exit codes are meant for CI: **0** if nothing is wrong, **1** if any field is `wrong`,
**2** if the run could not be performed at all (no provider, no filings, a ground-truth
sheet labelled for a different issuer).

### 4. Docker, exactly as the brief describes

```bash
docker compose up -d
curl localhost:8000/health

GIT_COMMIT=$(git rev-parse --short HEAD) docker compose run --rm eval
```

`up` leaves the extraction API serving on port 8000; `run --rm eval` is a one-shot that
runs the harness **against that API** and writes the scorecard to `./output` on your
machine. `GIT_COMMIT` is optional but worth passing: the image excludes `.git`, so without
it the scorecard cannot name the commit that produced it.

### If something goes wrong

| Symptom | Cause and fix |
|---|---|
| `GEMINI_API_KEY not set` | No `.env`, or the key line is empty. `cp .env.example .env` and fill it in. |
| `Model 'x' not found on this key` | Model availability differs per account. The error lists the ids your key actually has — copy one into `GEMINI_MODEL` in `.env`. Any Gemini vision model works; `gemini-3.1-flash-lite` is what the committed results used. |
| `run_eval` says "only CACHED predictions can be scored" | You have no key configured. That is a working path, not an error: it re-scores the committed predictions. `--no-cache` is what needs a provider. |
| `503 ... high demand` | Gemini capacity spike. One retry is automatic; if it persists, wait a minute. The run continues and reports the field as `missed`, never as a guess. |
| `429 rate limit` | Free-tier quota. Not retried on purpose — wait, or set `LLM_FALLBACK_PROVIDER=ollama`. |
| `OCR unavailable` on EMAS | `brew install tesseract tesseract-lang`. Without it EMAS still extracts, but page selection, grounding and the FX rate degrade — and the run says so. |
| Docker healthcheck never passes | `docker compose logs api`. Usually a missing `.env`, which makes `env_file` fail the whole project. |

---

## Where to look

The code is about 4,000 lines across `src/` and `scripts/`. If you have ten minutes, these are the parts worth the
time, each of which exists because something went wrong:

| Read | Why it is interesting |
|---|---|
| [*Ask for components, not conclusions*](#ask-for-components-not-conclusions) | Three balance-sheet rows all read "Utang bank". The fix was to stop asking the model to choose. |
| [*Confidence is computed, not self-reported*](#confidence-is-computed-not-self-reported) | The model never grades its own work; the score comes from signals the system can check. |
| [*What this number does not cover*](#what-this-number-does-not-cover) | Why 40/40 is weaker evidence than it looks. |
| [*Run against three issuers it was never developed on*](#run-against-three-issuers-it-was-never-developed-on) | Where the real engineering is: each new filer broke a different inherited assumption. |
| [*The first real failure, and what it cost*](#the-first-real-failure-and-what-it-cost) | An upstream 503 during a real run, and what the system did about it. |
| [*The harness found an error in the ground truth*](#the-harness-found-an-error-in-the-ground-truth) | The labels were wrong twice, and the tooling caught it. |
| [*Not built yet*](#not-built-yet) | What is missing, stated plainly. |

Committed artifacts, so nothing has to be taken on trust:

| File | What it is |
|---|---|
| `output/scorecard_gemini_gemini-3.1-flash-lite_image.json` | the 40/40 run, in process |
| `output/scorecard_gemini_gemini-3.1-flash-lite_image_api.json` | the same, scored through the containerised API |
| `output/scorecard_container_2026-09-03_upstream_503.json` | a **39/40** run, kept because it is the only real failure on record |
| `output/scorecard_baseline_2026-09-03_leaked_prompt.json` | an older run, so `compare_runs.py` can be demonstrated immediately |
| `data/ground_truth/CORRECTIONS.md` | every label changed after entry, with the evidence |
| `Checkpoint.md` | the development log for the serving layer |

```bash
# see the regression gate work, no API key needed
python scripts/compare_runs.py output/scorecard_container_2026-09-03_upstream_503.json \
                               output/scorecard_gemini_gemini-3.1-flash-lite_image_api.json
```

---

## Reading the output

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

### Running it entirely on your own machine

No key, no network, no per-token cost — a local model through Ollama instead:

```bash
ollama serve
ollama pull qwen3-vl:8b
LLM_PROVIDER=ollama python src/extract.py data/raw/Q1_2022_ARCI.pdf
```

Slower and weaker, but it is the path that proves the provider layer is not a Gemini
wrapper. `LLM_FALLBACK_PROVIDER=ollama` also makes it the automatic fallback when the
hosted provider is rate limited.

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

Three further issuers are in `data/raw/` and are used to test generalisation rather
than accuracy, because none of them is labelled yet:

| Issuer | Filings | What it adds that ARCI does not have |
|---|---|---|
| **JPFA** | Q1–Q4 2022, 171 pages | Rupiah, millions scale; share capital split into two classes; current portion of long-term loans filed under the current-liabilities heading |
| **CPIN** | Q1–Q4 2022, 120 pages | Rupiah, millions scale; a text layer that splits `14.406` into `1 4.406` |
| **EMAS** | Q3 2025, 97 pages | US Dollars; **no usable text layer at all** (subset fonts with no ToUnicode CMap); English digit grouping (`80,322,232`); an exchange rate quoted per 10,000 Rupiah to two decimals |

## Schema

Ten scored fields, mapped to spreadsheet rows by `EXCEL_ROWS` in `src/schema.py`
so the sheet stays the single source of naming:

`aset` · `total_aset_lancar` · `kas` · `liabilitas` · `utang_bank` · `ekuitas` ·
`pendapatan` · `laba_bersih` · `kas_dari_aktivitas_operasi` · `total_share`

`period_end_date` is extracted and checked against the period being evaluated, but
it is not one of the scored rows — a mismatch prints a warning rather than counting
against the accuracy figure.

Plus metadata (`currency`, `reporting_scale`, `statement_scope`) and five
**component fields** the model is asked for instead of the values they combine into
— see *Ask for components, not conclusions* below.

---

## Architecture

```
PDF (97-171 pages)
   │
   ├─ pdftext.py        the ONE place that decides "is this text real?"
   │                    text layer where usable; OCR where it is not
   │                    (empty, or Private Use Area glyph ids) — cached to disk
   │
   ├─ page_select.py    keyword scan of each page's title region (first 250 chars)
   │                    → 8 pages   [93.4% fewer pages]
   │                    → grouped: balance_sheet / income / cash_flow
   │                    → + the share-capital note, only if no page carries it
   │
   ├─ extract.py        one call PER STATEMENT, asking only for that
   │                    statement's fields
   │      ├─ image mode → render pages, send all of a group's images together
   │      └─ text mode  → text layer, condensed, page markers preserved
   │
   ├─ llm.py            provider layer: Gemini (REST) | Ollama (local)
   │                    JSON forced at the API level, not just requested
   │
   ├─ numfmt.py         694.671.337 or 80,322,232 — grouping convention decided
   │                    per value, from its shape
   │
   ├─ derive_fields()   utang_bank  = short-term + current-maturity components
   │                    ekuitas     = total equity − non-controlling interest
   │                    total_share = sum of the per-class share counts
   │                    + balance-sheet identity check
   │
   └─ normalize.py      scale (FULL/THOUSANDS/…) × FX rate read FROM THE FILING
                        → full Rupiah
```

Two of those modules exist only because a second and third issuer were tried.
`pdftext.py` and `numfmt.py` are the shape the code had to take once "the text layer
is readable" and "a dot separates thousands" stopped being true.

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

#### Issuers do not write that row the same way

EMAS prints the same disclosure with a different unit, a different decimal mark, and
the numbers *before* the label — and its page has to be OCR'd first, which drops the
leading zero:

```
ARCI   1.000 Rupiah        0,0697 0,0701 0,0686        → 1000 / 0.0697   = 14,347.20
EMAS   .61 0.62 Indonesian Rupiah 10,000 ("Rp")        → 10000 / 0.61    = 16,393.44
```

A regex tuned to either one silently misses the other, so the row is read in pieces:
find the Rupiah unit, remove it, read the first plausible figure from what remains,
and accept the result only if it lands between 8,000 and 25,000 IDR/USD. Outside that
band it is not a rate, and nothing is invented in its place.

Two things this surfaced, both now reported as warnings on every conversion:

- **The comparative column is right there.** That row carries the prior periods too.
  Taking the first column is correct, but the others are named in the output so the
  choice is checkable rather than assumed.
- **Precision is not a constant.** ARCI quotes four decimals — 0.07% uncertainty.
  EMAS quotes two: **0.8%**, eighty times the evaluator's tolerance. Every converted
  figure inherits it, so it is stated once, up front, instead of surfacing later as
  an unexplained mismatch.

The OCR resolution matters more than it looks. At 200 dpi tesseract read EMAS's
current-period column as `S2` while the comparative column beside it came out clean —
which would have produced a confident rate **from the wrong period**. The default is
300 dpi for that reason, paid once per filing and cached.

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

**Grounding is the anti-hallucination test.** Every number is re-rendered the way a
filing would print it (`694671337` → `694.671.337` *and* `694,671,337`, negatives as
`(76.732)`) and searched for in the page text. A figure the document does not contain
was invented.

This works in image mode too, and is *stronger* there: the extractor reads pixels,
the verifier reads characters, so agreement is genuine corroboration rather than the
same read performed twice.

**Its failure mode is a false negative, and that is expensive.** Two real cases:
CPIN's text layer splits `14.406` into `1 4.406`, and EMAS groups digits with commas
rather than dots. In both, correctly extracted figures read as absent, and abstention
then *discarded right answers* — for CPIN it took the non-controlling interest and,
because equity is derived from it, equity with it. Grounding now repairs spacing
between digits and checks both grouping conventions before concluding that a number
is not there. Neither repair loosens the test: a comma-grouped string does not occur
in a dot-grouped document, so the extra form cannot match a different number.

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

  **With one honest caveat.** ARCI's labels were entered by reading the filing in
  USD and converting with the rate the filing itself discloses — the same rate
  `normalize.py` uses. The converted comparison therefore cannot fail on a rate
  error: both sides share the rate, which is why every relative error in the ARCI
  scorecard sits at float noise (~1e-13). Only the as-printed leg measures anything
  on this issuer. Conversion is instead exercised by the cross-check against Bank
  Indonesia's middle rates above, and by the guard tests. An IDR-reporting issuer
  (JPFA, CPIN) has no conversion step at all, so its labels would not have this
  property.
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
- **The sheet must name the issuer it is for.** These workbooks are made by copying an
  existing one and overwriting the columns, and a copy that was never re-labelled
  scores one issuer's extraction against another's figures — every field wrong, for a
  reason that appears nowhere in the output. `load_ground_truth` reads the ticker out
  of cell `D1` and refuses to run when it disagrees with `--ticker`.

### Results

`gemini-3.1-flash-lite`, image mode, Q1–Q4 2022:

```
correct   40      wrong   0      missed   0
accuracy  100%  (40/40)
```

Reproduced after the prompt was rewritten to remove ARCI's own figures from its
examples (see *Agentic development*), so the score is not the model copying numbers
it was shown. Latency is in the scorecard: 18–29 s per filing, three or four calls
each.

#### What this number does not cover

Stated plainly, because a clean scorecard is the easiest thing in this repo to
over-read:

- **One issuer.** 40 cells = ARCI × four periods × ten fields. JPFA, CPIN and EMAS
  are extracted and self-checked, not scored, because they have no labels yet.
- **ARCI has never failed**, so its `failure_kinds` and `abstained` are empty in every
  period. A 100% run on the template the system was built against is weak evidence, and
  reading it as strong is the mistake this section exists to prevent. JPFA is where the
  guards were first exercised by something nobody staged — see its scorecard, where
  three fields are abstained and none is wrong.
- **The converted leg is not independent**, for the reason given above.

The single highest-value addition is not another guard: it is labels for one JPFA
period, which would turn three of those four caveats into measurements.

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
the right guard fires — 25 tests, runnable with or without pytest:

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
PASS  test_scale_is_read_from_the_header_not_guessed
PASS  test_printed_scale_overrides_the_model
PASS  test_older_balance_sheet_wording_is_still_found
PASS  test_unmatched_section_headings_warn_instead_of_passing_silently
PASS  test_bank_sections_resolve_for_a_second_issuer        ARCI and JPFA wording
PASS  test_missing_long_term_section_does_not_crash
PASS  test_grounding_survives_a_broken_text_layer           CPIN's "1 4.406"
PASS  test_indonesian_number_strings_are_parsed_correctly
PASS  test_balance_check_needs_total_equity_to_run
PASS  test_missing_currency_refuses_rather_than_assuming_idr
PASS  test_ground_truth_sheet_must_match_the_ticker
PASS  test_share_capital_split_across_classes_is_summed_and_not_punished
PASS  test_an_invented_share_class_is_still_caught
PASS  test_a_derived_field_cannot_outlive_an_abstained_component
25/25 passed
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

## API surface

`src/api.py` is transport and nothing else. No handler parses a figure, scores a field
or converts a currency — the moment one does, the extractor has been forked in two, and
the copy behind the HTTP boundary is the one the evaluation harness cannot test.

| Endpoint | Returns |
|---|---|
| `GET /health` | status, provider, model, input mode, git commit. **Shallow by default**; `?deep=true` also contacts the provider, cached 30s |
| `GET /schema` | the field contract, generated from `FIELDS` / `EXCEL_ROWS` / `DERIVED_FROM` so it cannot drift from the code |
| `POST /extract` | one filing: values as printed, per-field confidence, abstentions, validation issues, usage |
| `POST /extract/batch` | many filings, bounded concurrency, **per-document failure isolation** |

```jsonc
// POST /extract  -F file=@Q1_2022_ARCI.pdf     (trimmed)
{
  "filename": "Q1_2022_ARCI.pdf",
  "pages_selected": [5, 6, 7, 8, 9, 10, 11, 12],
  "extraction": { "aset": 694671337.0, "utang_bank": 102357484.0, "currency": "USD", ... },
  "confidence": { "aset": {"confidence": 1.0, "grounded": true, "abstained": false} },
  "abstained": [],
  "issues": [],
  "usage": {
    "llm_calls": 3,
    "tokens": {"input": 18019, "output": 982},
    "latency_ms": {"select_pages": 5769, "read_text": 295, "extract": 16414, "assess": 4},
    "cost": {"amount": null, "reason": "no price configured for gemini-3.1-flash-lite"}
  }
}
```

Four decisions worth defending:

**Values come back as printed, not normalised.** Converting to Rupiah needs the filing's
own disclosed rate and reporting scale, and `normalize.py` already does that for the
harness. Doing it again behind an HTTP boundary would give two implementations that
agree right up until they do not — and the one the harness cannot reach is the one that
would drift.

**Batch isolates failure per document.** Fifty filings with one corrupt PDF return
forty-nine results and one explanation, each entry carrying its own `status`. A batch
that gives up wholesale makes the caller work out which document poisoned it and resend
the rest. A rate limit is treated differently *in kind*: `LLMUnavailable` means the
provider is gone, so the remaining documents fail immediately rather than each spending a
call to rediscover it.

**Abstentions are returned explicitly**, as a list and as a flag, even though the value
is already `null`. A caller cannot otherwise distinguish "the filing does not report
this" from "we read something and did not trust it", and those call for opposite
responses: the first is a fact about the document, the second is an invitation to look at
the page.

**A partial extraction is a result, not an error.** A per-page `LLMError` returns 200
with the fields that were read and `issues` populated. Eight of ten fields plus an
explanation is worth more than a 500. What does *not* return 200: a non-PDF upload (400,
checked by magic bytes rather than by a filename the client controls), an oversized
upload (413), and a provider outage (503, naming the provider).

**Trade-off: the API is synchronous.** A request holds a connection for 20–60 seconds
while the model works. That is the right shape at this size — no queue to operate, no job
store, no polling protocol, and the caller gets the answer or the reason in one round
trip. It becomes the wrong shape at three specific points: when documents take minutes
rather than seconds (EMAS's first OCR pass takes ~2), when callers cannot hold a
connection that long (browsers, API gateways with 30-second timeouts), or when retrying
one failed document in a fifty-document batch means re-uploading all fifty. At that point
`/extract` should return a job id and the result should be fetched separately — but
building that before any of those three is true would be paying for a problem this system
does not have.

## Production notes

### Optimisations, with measured impact

| Change | Effect |
|---|---|
| Page selection by title keyword | 122 pages → 8 (**93.4% fewer**) |
| One call per statement, narrowed field list | local model **10/14 → 18/18 fields** |
| Group pages into one call (image mode) | **8 requests → 3** per document |
| Drop rotated pages, keep only number-bearing lines + neighbours | text **−25%** (18,467 → 13,857 chars) |
| Size `num_ctx` to the actual input | KV cache **16,384 → 8,192** |
| Batch concurrency, 1 → 2 workers | two filings **50.0 s → 33.4 s (−33%)** |

The second row is the one that mattered. A 7B local model given 18 fields across 7
pages answered the first few and quietly dropped the rest; given 4–13 fields across
2–3 pages it answered all of them. The fix was scope per call, not a bigger model.

### Cost

Tokens are recorded from the provider's own accounting, never estimated: Gemini reports
`usageMetadata`, Ollama reports `prompt_eval_count`/`eval_count`. A four-period ARCI run,
image mode:

| | Per run (4 filings) | Per filing |
|---|---:|---:|
| LLM calls | 13 | 3–4 |
| Input tokens | 75,151 | ~18,800 |
| Output tokens | 4,085 | ~1,020 |
| Cost | *unpriced* | *unpriced* |

Input dominates by 18:1, which is the number that decides where optimisation effort
goes: the output is a small fixed JSON object, so every saving has to come from what is
sent. That is what makes page selection (122 pages → 8) the single largest cost lever in
the system, and why image mode is the expensive choice — an image page costs roughly
10–20× its text equivalent.

**Cost reads "unpriced" on purpose.** `config/pricing.json` ships with no cloud rates:
prices change and differ per account, so an unpriced model reports real tokens and a null
cost carrying the reason. A wrong price would be worse than none, because it would be
quoted with the same confidence as a measured one. Filling in the rate turns every figure
above into money without touching code. Locally served models *are* priced — at zero,
which is true, and which keeps a cloud-versus-local comparison from reading as missing
data.

### Latency

Recorded per filing and per stage. Four ARCI periods through the API, image mode:
**25–40 s per filing (mean 31 s)**; in-process the same run spanned 24–65 s. The stage
split is what makes it actionable — from a single `/extract`:

```
select_pages 5.8s | read_text 0.3s | extract 16.4s | assess 0.0s
```

Page selection is a third of the wall clock on a clean filing and considerably more on
one that must be OCR'd, which a single total would have charged to the model.

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
- **A missing currency stops normalisation.** It used to fall through to "assume IDR",
  which turns a deliberate abstention into a silent ~14,000x understatement on a USD
  filer. Refusing is the only defensible behaviour: the abstention already said the
  value was not worth asserting.
- **An unreadable text layer is detected, not inherited.** Pages that extract as glyph
  ids or as nothing are OCR'd rather than passed downstream as empty evidence, which
  is what turned "every field abstained" into a working extraction on EMAS.
- **A capacity spike is retried once; a rate limit is not.** These read alike in a
  status table and behave nothing alike. A `503` says the service is briefly
  oversubscribed — its own message invites a retry — so one more attempt follows after a
  short backoff. A `429` says *we* are over our allowance, and retrying spends another
  unit of the thing we just ran out of, so it abandons the provider immediately. This
  distinction was not theoretical: see below.
- **Known limit:** type checking at the JSON boundary. `from_dict` accepts any type,
  so a hand-edited or stale cache file can raise inside `validate()` rather than being
  rejected with a clear message. Listed under *Not built yet*.


### The first real failure, and what it cost

Every resilience claim above was, until this run, demonstrated only by fault injection.
Then a containerised evaluation hit a genuine one. Gemini answered one call of one
filing with:

```
[cash_flow] pages [11, 12], 2 image(s), 794 KB
  ✗ LLMError: Gemini HTTP 503: "This model is currently experiencing high demand.
     Spikes in demand are usually temporary. Please try again later."
✓ 17/19 fields
```

The system behaved as designed, and the design was right about the important part and
wrong about a smaller one.

**Right:** the failure was classified as `LLMError`, not `LLMUnavailable`, so the other
statement groups still ran; the API returned a partial result with HTTP 200 rather than a
500; and the evaluator scored the lost field **`missed`, not `wrong`**. Nothing was
invented to fill the gap. The scorecard read 39/40 and said exactly which field and why.

**Wrong:** the field was recoverable. The model could read that page perfectly well —
the service was briefly busy and said so. One bounded retry now follows a `503`, and the
regression tool shows the difference precisely:

```
$ python scripts/compare_runs.py output/scorecard_container_2026-09-03_upstream_503.json \
                                 output/scorecard_gemini_gemini-3.1-flash-lite_image_api.json
changes in the other direction
  Q1 kas_dari_aktivitas_operasi         missed -> correct
              baseline  candidate   delta
  correct           39         40      +1
  missed             1          0      -1
```

Both scorecards are committed. The 39/40 is kept deliberately: a repository in which
nothing has ever gone wrong is a repository that has not been run enough, and this is the
only evidence here of the abstention-versus-invention distinction holding under a failure
nobody staged.

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

What worked better still was pointing it at the repo's own claims. An audit pass
found four things no test was covering, each verified by probing the code rather than
reading it:

- **The prompt contained ARCI's own figures as its formatting examples** — the same
  values the scorecard then graded the model on. Grounding could not catch it, since
  those numbers genuinely are printed in the filing. The prompt now uses placeholder
  digits, and the score survived the change: still 40/40.
- **The committed scorecard had been generated from stale caches**, so every
  `confidence` field in it was `null` — the artifact demonstrating the confidence
  layer demonstrated nothing about it.
- **`_coerce_numbers` misread a single dot group**: `"694.671"` became `694.671`, a
  thousandfold understatement, and `"(76.732)"` came back positive.
- **A ternary precedence bug** made the balance-sheet check drop `liabilitas` whenever
  total equity was missing, reporting sound filings as unbalanced.

The general lesson: the artifacts a project is proudest of are the ones least likely
to be re-examined. Asking an agent to attack its own scorecard is cheaper than having
a reviewer do it.

**Custom extension:** `.claude/skills/label-groundtruth/SKILL.md`, a repo-local skill
that encodes the ground-truth labelling rules — where the labels live and how the
sheet is shaped, the parent-attributable subtotal rule that caused the one logged
correction, and the rule that the model under evaluation must never pre-fill its own
labels. Its column-selection warning ("check the column header, not the row
position") is exactly the failure the extractor hit later, and its no-self-labelling
rule is the same principle the prompt leak violated.

---

## Generalising to other issuers

The system was developed against one issuer, so anything matched on ARCI's exact
wording is a place it would quietly stop working. Those were found by audit and
loosened:

| Was | Now |
|---|---|
| Prompt named the issuer and said "usually USD" | Issuer-neutral; currency and scale read from the document |
| One label per field (`"Total Aset"`) | Variants listed (`Total Aset` \| `Jumlah Aset` \| `Total Assets`) |
| Balance sheet titled only "Laporan Posisi Keuangan" | Also `Neraca`, `Balance Sheet`, comprehensive-income wordings |
| Bank sections matched ARCI's exact phrase | Matched on distinguishing words; `Kewajiban` accepted alongside `Liabilitas` |
| Scale taken from the model alone | Read from the printed header, which **overrides** the model |
| Eval periods hard-coded to 2022 | Discovered from `data/raw/*_<TICKER>.pdf` |

Two of these deserve emphasis.

**Scale is now read, not asked for.** A missed "dalam ribuan" multiplies every figure
by a thousand, and the wording sits in plain text a fixed distance from the title.
`detect_scale()` reads it directly and, on disagreement, overrides the model with a
warning. ARCI reports in full units, so this path was untested until JPFA and CPIN,
both of which report in millions — it now runs on real filings.

**A guard that cannot run now says so.** If an issuer words its liability headings
differently, `_bank_rows_by_section()` returns an empty map and every wrong-row check
is skipped. Previously that was silent: the guard switched itself off while
confidence stayed high. It now raises `section_map_incomplete`.

### Run against three issuers it was never developed on

Claims about generalisation are worth little until the code meets a document it was
not written for, so the pipeline was run on **JPFA Q1 2022** (171 pages), **CPIN Q1
2022** (120 pages) and **EMAS Q3 2025** (97 pages).

No ground truth exists for any of them yet, but a filing checks a lot of its own work:

| Check | JPFA | CPIN | EMAS |
|---|---|---|---|
| Balance sheet identity (`aset = liabilitas + total ekuitas`) | holds | holds | holds |
| Scale read from the printed header | `MILLIONS` | `MILLIONS` | `FULL` |
| Currency read from the header | `IDR` | `IDR` | `USD` |
| Every extracted figure grounded in the document | yes | yes | yes |
| Bank-debt section map resolved | yes | yes | no bank debt reported |
| Fields returned | 18/18 | 17/18 | 17/18 |

Each one broke something different, and each break is worth more than the passes.

**Share capital is not always one line.** JPFA issues two classes and prints a count
for each — `8.814.985.201` Seri A and `2.911.590.000` Seri B — and never their total.
ARCI issues one class and prints it whole, so the extractor had only ever needed to
copy a number. The model correctly returned nothing rather than guessing, which cost
a field. It is now asked for `total_share_components`, a count per class, and the sum
is computed in `derive_fields()` — the same "components, not conclusions" treatment
`utang_bank` and `ekuitas` already get, and for the same reason: the sum is nowhere
in the filing, so grounding it verbatim would abstain on the right answer. The
computed total, `11.726.575.201`, matches the figure JPFA's own note states as its
listed share count on a different page — independent corroboration.

**A number split by the text layer is still printed.** CPIN's layer breaks `14.406`
into `1 4.406`, which read as absent and abstained on a correctly extracted
non-controlling interest — and since equity is derived from it, took equity with it.
Grounding now repairs spacing between digits before deciding a figure is missing.

**A text layer can exist and still be unreadable.** EMAS was the sharpest case, and
it broke four things at once:

| What | Why it broke | Fix |
|---|---|---|
| Every figure read as ungrounded, all fields abstained | Text layer is subset fonts with no ToUnicode CMap — 100% of characters are Private Use Area glyph ids, versus 0% for ARCI and JPFA | `src/pdftext.py`: one place decides whether text is real, and OCRs the page when it is not (cached to `output/ocr_cache/`) |
| "no exchange rate is disclosed" | The rate is on page 23, in that unreadable layer | The same OCR path; `extract_fx_rate` now reads through `pdftext` |
| The rate row itself did not match | EMAS quotes per **10,000** Rupiah with a decimal point, numbers before the label | Rate row read in pieces rather than by one regex — see *The exchange rate comes from the filing* |
| Grounding still failed after OCR | EMAS groups digits with commas (`80,322,232`), not dots | `src/numfmt.py`: grouping convention decided per value; grounding checks both forms |

The failure the user actually saw was the second one — an error message blaming the
filing for omitting something it plainly states on page 23. That is worth noting as a
diagnostic lesson: three subsystems read the text layer independently, so one broken
layer produced three unrelated-looking symptoms and one misleading message. Putting
the "is this text real?" decision in a single module is what makes the next such
filing report *one* problem instead of three.

Also loosened, by audit rather than by failure:

| Was | Now |
|---|---|
| Prompt named the issuer and said "usually USD" | Issuer-neutral; currency and scale read from the document |
| Prompt's examples were ARCI's own figures | Placeholder digits that cannot be copied as an answer |
| One label per field (`"Total Aset"`) | Variants listed (`Total Aset` \| `Jumlah Aset` \| `Total Assets`) |
| Balance sheet titled only "Laporan Posisi Keuangan" | Also `Neraca`, `Balance Sheet`, comprehensive-income wordings |
| Bank sections matched ARCI's exact phrase | Matched on distinguishing words; `Kewajiban` accepted alongside `Liabilitas` |
| Scale taken from the model alone | Read from the printed header, which **overrides** the model |
| Share count assumed to sit on a statement page | Located anywhere in the document when no selected page carries it |
| A dot separates thousands | Convention decided per value; both are read |
| The text layer is what the PDF says it is | Checked, and OCR'd when it is not |
| Eval periods hard-coded to 2022 | Discovered from `data/raw/*_<TICKER>.pdf` |

### Honest confidence

| Case | Confidence | Why |
|---|---|---|
| ARCI, other years | High | Same template, four periods score 40/40 |
| Another IDX filer, IDR, millions | Medium-high | JPFA and CPIN extract cleanly and self-consistently — but neither is scored against labels |
| Filer reporting in thousands | Medium | Same deterministic reader as millions, which now works on real filings; the thousands branch itself is still untested |
| Filer with a broken or absent text layer | Medium | EMAS works end to end through OCR, but on one filing, and OCR quality is the new dependency |
| Filer with no disclosed FX rate, reporting in USD | Refuses | By design; it raises rather than guessing a rate |
| Filer quoting its rate to two decimals | Works, with a caveat | 0.8% rounding uncertainty, reported on every conversion rather than hidden |

Grounding does not depend on the issuer at all, and neither do the balance-sheet
identity or containment rules. A new issuer is therefore more likely to produce
**abstentions and validation errors** than confident wrong numbers — which is what
both new issuers did: JPFA declined `total_share` rather than inventing one, and EMAS
abstained on everything rather than asserting figures it could not verify.

That behaviour is the design working, but it is also the honest limit of what has
been shown: **the gap that remains is labels.** JPFA, CPIN and EMAS are extracted but
not *scored*, so "correct" for them rests on the filing's own internal consistency,
not on measurement. Labelling one JPFA period — ten cells, the workflow in
`.claude/skills/label-groundtruth/SKILL.md` — is the single highest-value next step in
this repository.

## Not built yet

Stated plainly because the brief asks for them:

- **Calibration of the confidence scores.** The weights are reasoned, not fitted; the
  threshold has not been swept against the eval set to find where precision and
  coverage actually trade off.
- **Cross-provider agreement as a fourth signal.** Running two models and scoring
  disagreement is the obvious next input to confidence, and the provider layer
  already supports it.
- **A scored second issuer.** Three are extracted, none is labelled, so the scorecard
  still covers one. This remains the largest gap in the whole repository.
- **A priced cost figure.** Tokens are measured; money needs a rate in
  `config/pricing.json`.
- **Asynchronous extraction.** The API holds the connection for the length of the job.
  See the trade-off note under *API surface* for the three conditions that would make
  that the wrong choice.

## With more time

1. **Label one JPFA period** (ten cells) and score it. That converts three of the four
   caveats under *What this number does not cover* from disclaimers into measurements,
   and it is perhaps an hour's work.
2. **Calibrate the abstention threshold** by sweeping it against the eval set and
   plotting precision against coverage, instead of choosing 0.55 by argument.
3. **Sweep the retry policy.** One attempt on a `503` recovered the field it was added
   for, but one observation is not a policy: how often capacity spikes happen, and
   whether a second attempt ever helps, is unmeasured.
4. **The layout-aware text path.** `extract_text(layout=True)` preserves the
   indentation that distinguishes the three `Utang bank` rows; it costs +28% tokens
   and was not needed once components were extracted separately, but it is the next
   lever if another issuer's labels prove less regular.

---

## Repo layout

```
src/
  api.py           HTTP transport: /health /schema /extract /extract/batch
  api_models.py    pydantic response models — the contract callers write against
  usage.py         tokens, cost and per-stage latency for one document
  pdftext.py       decides whether a text layer is real; OCRs the pages that are not
  numfmt.py        parses a printed figure under either grouping convention
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
  raw/             ARCI, JPFA, CPIN (Q1-Q4 2022) and EMAS (Q3 2025)
  ground_truth/    ARCI.xlsx (the only labelled issuer), TLDN.xlsx, JSON template
                   CORRECTIONS.md — every label changed after entry, with evidence
config/
  pricing.json     token rates, empty of cloud prices by design
Dockerfile         api + eval image (written, not yet built)
docker-compose.yml `up` serves the API; `run --rm eval` scores it
output/
  scorecard_*.json committed results from real runs, including a baseline to diff
  predictions/     cached per provider and mode
  ocr_cache/       OCR text per filing; derived, safe to delete
.claude/skills/    label-groundtruth (custom agent skill)
```
