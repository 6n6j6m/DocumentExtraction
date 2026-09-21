# Financial Statement Extraction — IDX Quarterly Filings

Pulls a fixed schema of ten financial figures out of Indonesian Stock Exchange filings —
100 to 170 page bilingual PDFs — normalises them to full Rupiah, scores the result
against hand-labelled ground truth, and **declines to answer when it is not confident**
rather than guessing.

## Why this exists

This is not a problem found for the exercise. It is freelance work I do with a friend who
analyses Indonesian listed companies, combining qualitative judgement with the numbers. He
does the judgement; my job has been collecting the quantitative side — opening each
quarterly filing, finding the four primary statements somewhere inside a hundred-odd
pages, and copying ten figures per period into a spreadsheet so he can compute the ratios
he actually reasons with.

It is slow, and slow in the least interesting way: the work is almost entirely locating
and transcribing. It also fails badly rather than gracefully — a single misread row
quietly poisons every ratio built on top of it, and nothing downstream can tell. Per
issuer it is tolerable. Across a watchlist, and repeated every quarter, it is the reason
this repository exists.

So the question behind this repository is a practical one — **can this be automated
without becoming untrustworthy?** Automation that is right most of the time is worse than
useless here, because a wrong figure looks exactly like a right one once it is in the
spreadsheet. That is why so much of what follows is about the system knowing when it is
unsure, refusing rather than guessing, and being measurable enough that we could tell.

Two consequences worth knowing before reading further:

- **The schema is his, not mine.** The ten fields are whatever his ratios need — see
  [Schema, and why these ten fields](#schema-and-why-these-ten-fields). I did not choose
  them to be convenient to extract, and two of them are genuinely awkward.
- **The ground truth is the real working spreadsheet**, Indonesian labels and all, with
  his ratio formulas still in the rows beneath the extracted figures. It was not built for
  this evaluation; the evaluation was fitted to it.

---

## Where it stands

**Two issuers are scored**, and they say different things:

| Issuer | Result | What it is |
|---|---|---|
| **ARCI** | **40/40** (100%) | USD, full units. The issuer this was developed against. |
| **JPFA** | **36/36**, and **33/36** once | Rupiah, millions. Never seen during development. Three runs, two answers. |

JPFA is the more informative row, and the disagreement is the reason. Three runs of the
same code over the same filings scored 36/36, 33/36 and 36/36. **Nothing was `wrong` in
any of them.** In the middle one the model misread a figure on JPFA's annual report, the
balance sheet stopped balancing, and the system withdrew the three implicated fields
rather than publishing them — the abstention machinery firing on something nobody staged.

All three scorecards are committed. Reporting only the 36/36 would describe a system that
is more reliable than this one is; reporting only the 33/36 would describe one that is
worse. Together they say what is actually true: on an issuer it has never been tuned for,
the extractor occasionally cannot read the hardest period, and when that happens it says
so instead of guessing. **One period out of four is where the variance lives**, and one
more clean run is not evidence that it has gone away.

**90 tests**, of which 52 break one specific thing each and assert the right guard fires.

**What is still not scored.** CPIN and EMAS are extracted and checked against what each
filing says about itself, but they have no labels. The distinction is kept sharp
throughout: a filing that validates is not a filing that was measured.

### What this README covers

The brief asks a README to cover run commands, the dataset, schema and approach with the
reasoning, the architecture, key trade-offs, eval results, the agentic-development note,
and what more time would buy. In order:

| | |
|---|---|
| Run commands | [Start here](#start-here) · [Batch a folder into one CSV](#3-batch-a-folder-into-one-csv) · [Reading the output](#reading-the-output) |
| Why the problem | [Why this exists](#why-this-exists) |
| Dataset, and why | [Dataset, and why this one](#dataset-and-why-this-one) |
| Schema, and why | [Schema, and why these ten fields](#schema-and-why-these-ten-fields) |
| Approach, and why | [Architecture](#architecture) · [Why a single well-designed call per statement, not an agent](#why-a-single-well-designed-call-per-statement-not-an-agent) |
| Architecture | [Architecture](#architecture) · [API surface](#api-surface) |
| Key trade-offs | [Key decisions and trade-offs](#key-decisions-and-trade-offs) |
| Eval results | [Evaluation](#evaluation) · [Results](#results) · [What these numbers do not cover](#what-these-numbers-do-not-cover) |
| Agentic development | [Agentic development](#agentic-development) |
| With more time | [Not built yet](#not-built-yet) · [With more time](#with-more-time) |

---

## Start here

Four ways in, in increasing order of what they need from you. Everything the commands
below refer to — the filings, the labels, the committed results — is in the repository, so
none of it has to be taken on trust.

| | Needs | Takes | Shows |
|---|---|---|---|
| **1. Run the tests** | Python only — **no API key** | ~90 s | That the guards, the confidence layer and the abstention logic do what this README says |
| **2. Extract one filing** | A free Gemini key | ~25 s | The system reading a real 122-page filing end to end |
| **3. Batch a folder into one CSV** | The key | ~30 s per filing | The thing this project exists for: a directory of PDFs becomes a spreadsheet |
| **4. Score it** | The key | ~4 min | Both issuers re-scored from scratch |
| **5. Docker** | Docker + the key | ~6 min | `compose up` serving the API, then **one command** that scores both issuers **against that API** |

### 1. Run the tests — no key required

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -q
```

```
90 passed
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
  tokens in 28306 / out 1125

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

### 3. Batch a folder into one CSV

This is the step the project exists for. The manual workflow it replaces produced a
spreadsheet — one column per period, ten figures down it — and every other entry point
stops one short of that: the CLI prints, the API returns JSON, the harness writes a
scorecard. `scripts/pdf_to_csv.py` closes the gap. **One filing becomes one row. A folder
becomes one row per filing, in the same file, in the order given.**

```bash
# one file
python scripts/pdf_to_csv.py data/raw/Q1_2022_ARCI.pdf -o output/arci.csv

# several files
python scripts/pdf_to_csv.py data/raw/Q1_2022_ARCI.pdf data/raw/Q1_2022_JPFA.pdf -o output/two.csv

# an entire folder
python scripts/pdf_to_csv.py --dir data/raw -o output/all.csv

# a folder, one issuer only — matches *_<TICKER>.pdf
python scripts/pdf_to_csv.py --dir data/raw --ticker JPFA -o output/jpfa.csv
```

`--dir` reads one directory, not a tree. An archive kept as one folder per issuer
(`~/FinancialReport/ADMR`, `.../AADI`, …) is either flattened by the shell into a single
CSV, or walked issuer by issuer so that each one lands in its own file and a batch
interrupted halfway keeps everything already finished:

```bash
# every filing in every issuer folder -> one CSV
python scripts/pdf_to_csv.py ~/FinancialReport/*/*.pdf -o ~/FinancialReport/all.csv

# one CSV per issuer, named after the folder (zsh; ${t:l} lowercases it)
caffeinate -i -w $$ & for d in ~/FinancialReport/*/; do t=$(basename "$d"); \
  python scripts/pdf_to_csv.py --dir "$d" --ticker "$t" -o "${d}${t:l}.csv"; done
```

`caffeinate -i -w $$` keeps the Mac awake for as long as that shell lives; it cannot
prefix a `for` loop directly, which is why it is backgrounded rather than wrapped around
it. Measured on the 215-filing archive: roughly **40–60 s and 4–5 calls per filing** —
about three hours, and around 36k input / 1.5k output tokens each.

It reports as it goes, and flushes after every row, so a long batch is readable — and
usable — while it is still running:

```
[2/2] Q1_2022_JPFA.pdf

📄 Selecting pages from Q1_2022_JPFA.pdf...
  Pages: [4, 5, 6, 7, 8] (1-indexed)
  Reduction: 5/171 pages (97.1% reduction)

🔍 gemini:gemini-3.5-flash-lite [image]...
    +13 field(s)   +2 field(s)   +1 field(s)   +1 field(s)
    ⚠ model said total_share=11,717,366,360, 2 share class(es) sum to 11,726,575,201 - using classes
  ✓ 19/19 fields
  -> ok: 10/10 fields

2 row(s) -> output/two.csv
  ok 2 | partial 0 | error 0
```

| Flag | What it does |
|---|---|
| `--dir DIR` | take every PDF in `DIR` as well as any paths given |
| `--ticker XXXX` | with `--dir`, only files named `*_XXXX.pdf` |
| `-o`, `--out` | where the CSV goes (default `output/extractions.csv`) |
| `--append` | add to an existing CSV instead of replacing it — a batch split across several runs still reads as one table |
| `--as-printed` | keep the filing's own currency and scale; no conversion to Rupiah |

Exit code **0** when every row is complete, **1** when any row is partial or failed. A
caller scripting this should not have to parse the CSV to find out.

#### What a row actually contains

Thirty-three columns: identity, then the ten figures, then everything needed to judge them. A
reader who trusts the row can stop after the figures; a reader who does not has the
grounds for their doubt on the same line.

```
file             Q1_2022_JPFA.pdf      status           ok
ticker           JPFA                  fields_filled    10/10
period_end_date  2022-03-31            abstained
currency         IDR                   issues
reporting_scale  MILLIONS              notes
unit             IDR full              fx_rate / fx_source / fx_page
aset             30134349000000        pages_selected   4 5 6 7 8
...                                    model            gemini:gemini-3.5-flash-lite
                                       llm_calls        4
total_share      11726575201           tokens_in/out    25734 / 1083
                                       seconds          38.8
                                       error
```

Four conventions, because a CSV hides its own assumptions:

- **Figures are in full Rupiah by default.** The filings arrive in whatever currency and
  scale the issuer chose — ARCI in US Dollars at full units, JPFA in Rupiah at millions —
  and a column mixing those is worse than no column. `--as-printed` turns it off when the
  question is what the page said.
- **An empty cell means "not asserted", never zero.** A field can be blank because the
  filing does not report it, or because the system read something and refused to trust
  it. Those are different facts, so `abstained` names the fields withdrawn on purpose and
  `status` separates a clean row from a partial one.
- **A failed document still gets a row.** Fifty filings with one unreadable PDF produce
  forty-nine rows of figures and one row saying what went wrong — not a traceback and no
  file. Verified on a batch whose middle file was not a PDF: two rows of figures, one
  carrying `No /Root object! - Is this really a PDF?`, exit code 1, the other two
  documents unaffected.
- **Whole numbers are written without a trailing `.0`.** Share counts are carried as
  floats internally, so `total_share` used to reach the CSV as `11627669901.0`. A
  spreadsheet set to an Indonesian locale reads `.` as a thousands separator and keeps
  that cell as *text*, while the integer money columns beside it stay numbers — the one
  column the ratios divide by, silently not a number.
- **`reporting_scale` is the scale that was actually applied**, which is not always the
  one the model reported, and `notes` says why in words:

  ```
  model said scale THOUSANDS, header says FULL - using FULL
  Rate row also carried 15,408, 15,015 IDR/USD (comparative periods); took the first column, 16,420.
  ```

  Labelling a converted row with a multiplier that was never used is how a thousandfold
  error travels unnoticed — see
  [*The scale field was the one the guards could not see*](#the-scale-field-was-the-one-the-guards-could-not-see).

#### The one figure that is not in the filing

`Harga saham rupiah` feeds PBV and PE, and no balance sheet contains it — it is what the
market paid. `scripts/fetch_share_prices.py` reads the close from Yahoo Finance's chart
endpoint (`CPIN.JK`; no key, no account), pricing a quarter on the date by which its
report is public rather than on the period end:

| | | | |
|---|---|---|---|
| Q1 → 17 June | Q2 → 17 August | Q3 → 17 November | Q4 → 17 May of the *following* year |

Q4 moves forward because the annual report is audited and reaches the market in spring,
not in December. `--q4-same-year` if your convention differs.

```bash
python scripts/fetch_share_prices.py --ticker ARCI                 # show what it would write
python scripts/fetch_share_prices.py --ticker ARCI --write-xlsx    # fill the row (close Excel first)
python scripts/fetch_share_prices.py --ticker ARCI -o output/prices.csv
python scripts/fetch_share_prices.py --all --write-xlsx            # every workbook in data/ground_truth
```

`--all` takes one ticker per `<TICKER>.xlsx`, so every workbook is priced in one
command. A workbook that cannot be read or written is **skipped and named at the end**
rather than ending the run: the most common reason is a file still open in Excel, which
leaves a `~$NAME.xlsx` lock beside it, and stopping there would leave every issuer after
it unpriced.

**A price already in the sheet is left alone.** Only empty cells are filled, and a cell
whose value disagrees with Yahoo is printed instead of replaced — TLDN's sheet holds 472
for Q1 2026 where Yahoo closed at 530, and ten of its cells disagree like that. Which is
right is a decision about ground truth, not something a fetch script should settle, so
`--overwrite` is the way to say it. Across the other thirteen workbooks every value
already entered matched Yahoo exactly (CPIN 26, JPFA 26, ARCI 21, GTRA 15, EMAS 4), and
the cells Yahoo cannot price — periods before an issuer listed — stay as they are.

The 17th is frequently closed — 17 August is Independence Day every year, so Q2 never
lands on an open market — so the close of the **nearest** trading day is used, before or
after the 17th (the earlier one at equal distance, never a day that has not happened yet),
and the date actually taken is printed on every row. A period with no session within 12
days either side stays blank and says why; one whose pricing date has not arrived yet says
that instead.

Two details that were silent bugs until they were not. The workbooks head their annual
column `TAHUNAN 2024` rather than `Q4 2024` — every year but 2025 — so both spellings are
read as the same period; without that, the fourth quarter of five years was never priced,
with no error, just empty cells. And the **close** is used rather than Yahoo's
`adjclose`: adjusted prices are restated for later splits and dividends, and this price is
divided by a book value taken from the filing as it stood at the time, so an adjusted
numerator would silently mismatch its own denominator.

#### The whole sheet, including the ratios

`scripts/build_dataset.py` joins the two above and adds the eight derived rows, so the
output is what the manual workflow was actually producing rather than an intermediate
that still needs a spreadsheet wrapped around it:

```bash
# end to end: extract, price, compute
python scripts/build_dataset.py --dir data/raw --ticker ARCI -o output/arci_dataset.csv

# reuse an extraction you already paid for — no API calls
python scripts/build_dataset.py --from-csv output/arci.csv -o output/arci_dataset.csv

# skip the network; price, PBV and PE stay blank
python scripts/build_dataset.py --dir data/raw --ticker GTRA --no-prices
```

```
  period        harga       BVPS       EPS     PBV      PE      ROE
  Q1 2022      5025.0    1605.47    72.647 3.12992 69.1701 0.0452496
  Q2 2022      5700.0    1571.98   147.395 3.62601 38.6715 0.0937643
  Q3 2022      5750.0    1618.74    194.28 3.55215 29.5965  0.120019
```

The ratios are transcribed from the workbook, not reinvented — `ekuitas/total_share`,
`total_aset_lancar - liabilitas`, `laba_bersih/aset`, `laba_bersih/ekuitas`,
`harga/BVPS`, `harga/EPS`, `laba_bersih/total_share`, `liabilitas/ekuitas` — and checked
against the labelled ARCI Q1 2022 column, which they match to the rupiah. No extraction
or pricing logic lives in this file; `extract_row` and `collect` are imported from the
two scripts that own them, so there is no second copy to drift.

**A ratio is blank unless every input is present.** A field the extractor abstained on is
not zero, so a ratio built on it is not a number — it is a guess wearing a decimal point.
Blanking propagates: a missing share count takes BVPS and EPS, and through them PBV and
PE. `ratios_blank` names each one and why, so an empty cell traces back to the field that
caused it instead of looking like a bug. `test_a_ratio_is_blank_when_any_input_is` holds
that line.

Interim quarters are **not** annualised, exactly as the workbook does it: a Q1 ROE is
roughly a quarter of the annual figure. Annualising is a modelling decision, and this
file does not make those.

### 4. Score it — the full evaluation

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
    tokens              100878 in / 3765 out
    latency             21-36s per document (mean 28s)
```

The `usage` block is measured, not estimated: both providers report their own token
counts. `cost` reads *unpriced* by design — see [*Cost*](#cost).

Exit codes are meant for CI: **0** if nothing is wrong, **1** if any field is `wrong`,
**2** if the run could not be performed at all (no provider, no filings, a ground-truth
sheet labelled for a different issuer).

### 5. Docker, exactly as the brief describes

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
| The cache-only run took minutes and billed you | Predictions are cached per **model**. If `GEMINI_MODEL` in your `.env` is not `gemini-3.1-flash-lite`, every lookup misses and the run silently calls the API instead. Pin the model, or accept that you are doing a fresh extraction. |
| `503 ... high demand` | Gemini capacity spike. One retry is automatic; if it persists, wait a minute. The run continues and reports the field as `missed`, never as a guess. |
| `429 rate limit` | Gemini has three limits behind one code: requests per minute (RPM), tokens per minute (TPM), requests per day (RPD). A per-minute limit cools down and retries automatically (`LLM_RATE_LIMIT_WAIT_S`, default 70s). A per-**day** quota is not waited out — sleeping cannot clear it — so it fails fast. Limits are counted per model, so `GEMINI_FALLBACK_MODELS` hands a throttled document to another Gemini model at once, and `LLM_FALLBACK_PROVIDER=ollama` takes over only when every Gemini model is out. |
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
| [*What this number does not cover*](#what-these-numbers-do-not-cover) | Why 40/40 is weaker evidence than it looks. |
| [*Run against three issuers it was never developed on*](#run-against-three-issuers-it-was-never-developed-on) | Where the real engineering is: each new filer broke a different inherited assumption. |
| [*The first real failure, and what it cost*](#the-first-real-failure-and-what-it-cost) | An upstream 503 during a real run, and what the system did about it. |
| [*The harness found an error in the ground truth*](#the-harness-found-an-error-in-the-ground-truth) | The labels were wrong twice, and the tooling caught it. |
| [*Not built yet*](#not-built-yet) | What is missing, stated plainly. |

Committed artifacts, so nothing has to be taken on trust:

| File | What it is |
|---|---|
| `output/scorecard_ARCI_gemini_gemini-3.1-flash-lite_image.json` | ARCI 40/40, in process |
| `output/scorecard_ARCI_gemini_gemini-3.1-flash-lite_image_api.json` | ARCI 40/40, through the containerised API |
| `output/scorecard_JPFA_gemini_gemini-3.1-flash-lite_image_api.json` | JPFA **36/36**, through the API |
| `output/scorecard_JPFA_gemini_gemini-3.1-flash-lite_image.json` | JPFA **33/36** — the same code, three abstentions. The pair is the point |
| `output/scorecard_container_2026-09-03_upstream_503.json` | a **39/40** run, kept because it is the only real failure on record |
| `output/scorecard_baseline_2026-09-03_leaked_prompt.json` | an older run, so `compare_runs.py` can be demonstrated immediately |
| `data/ground_truth/CORRECTIONS.md` | every label changed after entry, with the evidence |
| `Checkpoint.md` | the development log for the serving layer |

```bash
# see the regression gate work, no API key needed
python scripts/compare_runs.py output/scorecard_container_2026-09-03_upstream_503.json \
                               output/scorecard_ARCI_gemini_gemini-3.1-flash-lite_image_api.json
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

Public IDX filings, downloaded as published — the same documents the manual workflow this
replaces already used. They were not chosen for being tractable, and they are awkward in
ways that matter:

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

Three further issuers are in `data/raw/`. **JPFA is labelled and scored**; CPIN and EMAS
are extracted and self-checked but have no labels, so they test generalisation rather
than accuracy:

| Issuer | Filings | What it adds that ARCI does not have |
|---|---|---|
| **JPFA** | Q1–Q4 2022, 171 pages | Rupiah, millions scale; share capital split into two classes; current portion of long-term loans filed under the current-liabilities heading |
| **CPIN** | Q1–Q4 2022, 120 pages | Rupiah, millions scale; a text layer that splits `14.406` into `1 4.406` |
| **EMAS** | Q3 2025, 97 pages | US Dollars; **no usable text layer at all** (subset fonts with no ToUnicode CMap); English digit grouping (`80,322,232`); an exchange rate quoted per 10,000 Rupiah to two decimals |

## Schema, and why these ten fields

Ten scored fields, mapped to spreadsheet rows by `EXCEL_ROWS` in `src/schema.py`
so the sheet stays the single source of naming:

`aset` · `total_aset_lancar` · `kas` · `liabilitas` · `utang_bank` · `ekuitas` ·
`pendapatan` · `laba_bersih` · `kas_dari_aktivitas_operasi` · `total_share`

**They are not a sample of interesting figures. They are exactly the inputs to a fixed
set of valuation ratios**, which the ground-truth workbook computes in the rows below
them — BVPS, ROA, ROE, PBV, PE, EPS, DER. The schema was chosen by working backwards
from those:

| Ratio | Needs |
|---|---|
| Book value per share, EPS | `ekuitas`, `laba_bersih`, `total_share` |
| ROE, ROA | `laba_bersih`, `ekuitas`, `aset` |
| DER, net debt | `liabilitas`, `utang_bank`, `kas` |
| Liquidity | `total_aset_lancar`, `kas` |
| Margin, cash quality | `pendapatan`, `laba_bersih`, `kas_dari_aktivitas_operasi` |
| PBV, PE | the above, plus a share price — **market data, never extracted from a filing** |

That origin explains three choices that otherwise look arbitrary:

- **Everything is parent-attributable**, per the workbook's own header, `(HANYA YANG BISA
  DIATRIBUSIKAN KE ENTITAS INDUK SAJA)`. Per-share metrics belong to the parent's
  shareholders, so equity and profit exclude the non-controlling interest — which is why
  `ekuitas` is derived rather than read, and why a negative NCI makes the right answer
  *larger* than the printed total.
- **`utang_bank` is bank debt only**, not total liabilities. Leverage measures
  interest-bearing debt; trade payables are not that. This is also the hardest field in
  the schema, because three balance-sheet rows carry the label and only one section
  heading tells them apart.
- **`total_share` is a count, not money.** It is a denominator in five of the seven
  ratios, so scaling or FX-converting it would corrupt every one of them by a factor of
  around 14,000. It is carried through `normalize.py` untouched, by name.

`period_end_date` is extracted and checked against the period being evaluated, but it is
not one of the scored rows — a mismatch prints a warning rather than counting against the
accuracy figure.

Plus metadata (`currency`, `reporting_scale`, `statement_scope`) and five **component
fields** the model is asked for instead of the values they combine into — see *Ask for
components, not conclusions* below.

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

### Teach the reading method, not the labels

The first version of the extraction prompt was a list of labels to match: `"Total Aset"
| "Jumlah Aset" | "Total Assets"`. That is the part which does not survive a new
issuer. Every filer states the same accounting concepts in its own words, and a
label-matching extractor gets the first issuer right and then fails silently on the
second — returning a well-formed number from the wrong row, which is worse than an
error.

So each field is now described by what it **means** and where it **structurally sits**,
with wordings given as illustrations and explicitly marked non-exhaustive:

| | |
|---|---|
| MEANING | the accounting concept, independent of any wording |
| POSITION | where that concept sits in the statement's hierarchy |
| DISAMBIGUATE | how to tell it from the lines around it that look similar |
| TRAP | the specific mistake that has actually been observed |

Two examples of why the distinction is not academic:

**Equity attributable to the parent** is printed as a bare `Sub total` by ARCI, as a
named section total by others, and not at all by some. No label list covers that. What
does cover it is the arithmetic property: *this figure plus non-controlling interest
equals total equity*. The prompt now states that property and lets the model find
whichever row satisfies it.

**Bank debt due within a year** is `Utang bank` for ARCI and `Pinjaman` for EMAS. The
concept — interest-bearing borrowings from a bank, falling due within twelve months —
is the same, and the prompt describes the concept and the section it lives in rather
than the noun the issuer chose.

The prompt also asks the model to check its own reading against the identities the
statement must satisfy before answering. On a test across five issuers and four years,
every extraction now balances: `aset − liabilitas − ekuitas` equals the non-controlling
interest in each case.

**Trade-off:** the prompt roughly doubled in size, from ~2,400 to ~5,000 tokens, and it
is sent on every per-statement call. Input tokens per filing went from ~18,000 to
~28,000. That is the price of the accuracy, and it is paid on the cheaper side of the
bill.

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
- **Per-issuer, per-provider, per-mode scorecards.**
  `scorecard_<TICKER>_<provider>_<model>_<mode>.json`. Each element of that name earns
  its place by having been missing once: without the mode, a text run and an image run
  overwrite each other; without the ticker, the second issuer's first run overwrote the
  first issuer's committed result, which is exactly what happened when JPFA was added.
  The prediction cache carries the ticker for the same reason — `Q1` means one thing for
  ARCI and another for JPFA, and reading the wrong one scores an issuer against another
  issuer's labels.
- **The sheet must name the issuer it is for.** These workbooks are made by copying an
  existing one and overwriting the columns, and a copy that was never re-labelled
  scores one issuer's extraction against another's figures — every field wrong, for a
  reason that appears nowhere in the output. `load_ground_truth` reads the ticker out
  of cell `D1` and refuses to run when it disagrees with `--ticker`.

### Results

`gemini-3.1-flash-lite`, image mode, Q1–Q4 2022, both scored issuers:

```
ARCI    correct 40   wrong 0   missed 0                accuracy 100%   (40/40)
JPFA    correct 36   wrong 0   missed 0                accuracy 100%   (36/36)   ← via the API
JPFA    correct 33   wrong 0   missed 3 (abstained)    accuracy 91.7%  (33/36)   ← a second run
JPFA    correct 36   wrong 0   missed 0                accuracy 100%   (36/36)   ← current code
```

ARCI was reproduced after the prompt was rewritten to remove its own figures from the
examples (see *Agentic development*), so the score is not the model copying numbers it was
shown.

**The three JPFA rows are the same filings.** Where they differ, the model misread one
figure on the annual report, the balance-sheet identity failed, and the three implicated
fields were withdrawn rather than published.

The last row is this code, re-run after the prompt rewrite and the text-layer fixes below.
`compare_runs.py` against the 33/36 baseline reports the three Q4 fields moving
`missed → correct` and **no regressions in either direction**:

```
Q4 aset          missed -> correct
Q4 ekuitas       missed -> correct
Q4 liabilitas    missed -> correct
correct 33 -> 36   wrong 0 -> 0   missed 3 -> 0
```

**One run does not prove the JPFA variance is gone.** The same period produced
both answers before anything changed, so a single clean pass cannot distinguish "fixed"
from "lucky". What it does establish is that nothing that used to be right became wrong.
Quoting only the 36/36 would describe a more reliable system than this is; quoting only
the 33/36 would describe a worse one. What all three agree on is the part that matters:
**on an issuer it was never tuned for, this extractor has never yet published a wrong
figure.**

**The same prompt, a different model.** ARCI was also run end to end on
`gemini-3.5-flash-lite` with no prompt change: **40/40**, 13 calls, 100,878 in / 3,788 out,
15–25 s per document. One issuer on one model swap is thin evidence, but it is the right
kind: the prompt describes accounting concepts rather than a model's habits, so it should
travel — and where it does not, `compare_runs.py` between the two scorecards is the way to
find out rather than to guess.


#### What these numbers do not cover

Stated plainly, because a clean scorecard is the easiest thing in this repo to over-read:

- **Two issuers, not four.** 76 scored cells in total. CPIN and EMAS are extracted and
  self-checked, not scored, because they have no labels.
- **ARCI has never failed**, so its `failure_kinds` and `abstained` are empty in every
  period. A 100% run on the template the system was built against is weak evidence, and
  reading it as strong is the mistake this section exists to prevent.
- **No extraction has ever scored `wrong`** on either issuer. Every failure so far has
  been the system declining to answer, which is the behaviour it is designed for — but it
  means the failure taxonomy (`wrong_scale`, `wrong_near_miss`, `hallucinated` …) is still
  demonstrated only by fault injection, never by a real misread that survived the guards.
- **The converted leg is not independent** for ARCI, for the reason given above. JPFA
  reports in Rupiah and has no conversion step, so its labels do not share this problem.

The highest-value addition is not another guard: it is labels for a third issuer, and
EMAS is the one that would exercise the most untested code.

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
the right guard fires — 52 tests, runnable with or without pytest:

```
PASS  test_correct_extraction_passes_cleanly            no false positives
PASS  test_derived_field_is_not_punished_for_being_absent
PASS  test_hallucinated_value_is_caught                 invented figure -> abstained
PASS  test_wrong_but_real_row_is_caught                 wrong row, genuine number
PASS  test_unbalanced_balance_sheet_is_caught
PASS  test_containment_violation_is_caught
PASS  test_fractional_share_count_is_caught
PASS  test_fx_rate_comes_from_the_filing
PASS  test_share_count_is_never_converted
PASS  test_usd_without_a_rate_refuses_rather_than_guesses
PASS  test_scale_is_read_from_the_header_not_guessed
PASS  test_a_header_naming_only_a_currency_means_full_units   no scale word = FULL
PASS  test_no_header_at_all_is_still_unknown
PASS  test_printed_scale_overrides_the_model
PASS  test_the_header_also_overrides_a_scale_the_model_invented   ARCI's 1000x
PASS  test_pages_declaring_different_scales_say_so
PASS  test_a_text_layer_shredded_into_single_characters_is_not_trusted   GTRA
PASS  test_a_dense_ordinary_page_is_still_trusted        the detector's other half
PASS  test_a_bank_row_is_found_whatever_the_issuer_calls_it   "Pinjaman bank"
PASS  test_older_balance_sheet_wording_is_still_found
PASS  test_unmatched_section_headings_warn_instead_of_passing_silently
PASS  test_bank_sections_resolve_for_a_second_issuer     ARCI and JPFA wording
PASS  test_missing_long_term_section_does_not_crash
PASS  test_grounding_survives_a_broken_text_layer        CPIN's "1 4.406"
PASS  test_grounding_survives_a_digit_split_from_its_separator   GTRA's "1 .092"
PASS  test_indonesian_number_strings_are_parsed_correctly
PASS  test_balance_check_needs_total_equity_to_run
PASS  test_share_capital_split_across_classes_is_summed_and_not_punished
PASS  test_an_invented_share_class_is_still_caught
PASS  test_an_explicit_nil_is_not_position_checked
PASS  test_missing_currency_refuses_rather_than_assuming_idr
PASS  test_ground_truth_sheet_must_match_the_ticker
PASS  test_failure_kinds_are_distinguished
PASS  test_a_derived_field_cannot_outlive_an_abstained_component
PASS  test_an_annual_column_is_recognised_as_q4        "TAHUNAN 2024" is Q4
PASS  test_the_nearest_session_to_the_17th_prices_the_period  either side of the 17th
PASS  test_a_ratio_is_blank_when_any_input_is          abstention survives arithmetic
PASS  test_a_header_without_the_verb_is_still_a_header     "(Dalam jutaan Rupiah"
PASS  test_a_rate_quoted_directly_as_rupiah_per_dollar_is_read ITMG's rate format
PASS  test_share_count_search_reads_only_the_shareholder_table DSNG, EMAS, ADMR pages
PASS  test_only_the_shareholder_table_group_supplies_share_counts statements give no count
PASS  test_a_title_behind_the_translation_notice_is_still_found LSIP's titles
PASS  test_a_title_split_across_bilingual_columns_is_still_found TLDN's balance sheet
PASS  test_a_note_mentioning_a_statement_is_not_a_title    why widening was rejected
PASS  test_a_figure_found_under_no_heading_is_unverified_not_wrong PTBA's "Pinjaman bank 100"
PASS  test_cash_printed_as_sub_lines_is_summed_and_each_line_is_checked LSIP's cash parts
PASS  test_total_share_is_the_outstanding_count
PASS  test_a_computed_outstanding_count_is_graded_on_what_it_was_computed_from
PASS  test_a_computed_outstanding_figure_does_not_sink_a_total_its_inputs_support
PASS  test_the_shareholder_table_is_found_and_the_eps_note_is_not
PASS  test_treasury_shares_from_another_date_are_not_subtracted
PASS  test_a_total_from_the_comparative_table_is_replaced_by_the_current_one
52/52 passed
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
| Page selection reads title regions, not pages | scanned filing **3:00 → 1:01 (−66%)** |

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
| Input tokens | 100,878 | ~25,200 |
| Output tokens | 3,765 | ~940 |
| Cost | *unpriced* | *unpriced* |

Input was 75,151 before the prompt was rewritten from a list of labels into a reading
method. The extra ~25,000 tokens per run is that prompt, charged 13 times — a real and
deliberate cost, paid for the generalisation it buys across issuers.

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

Recorded per filing and per stage. In-process, image mode, current code:
**ARCI 21–36 s per filing (mean 28 s)**, **JPFA 23–50 s (mean 32 s)**. An earlier run of
the four ARCI periods *through the API* spanned 25–40 s (mean 31 s) — measured before the
prompt rewrite, so it is not directly comparable to the two figures above. The stage split
is what makes any of it actionable — from a single `/extract`:

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
  ids, as nothing, or as single characters with the columns interleaved are OCR'd rather
  than passed downstream as empty evidence. That is what turned "every field abstained"
  into a working extraction on EMAS, and 2/10 fields into 10/10 on GTRA — see
  [*A text layer can be present, readable-looking, and still useless*](#a-text-layer-can-be-present-readable-looking-and-still-useless).
- **Three failures that all arrive as one status code are told apart.** A `503` says the
  service is briefly oversubscribed — its own message invites a retry — so one more
  attempt follows after a short backoff. A `429` needs reading further: a **per-minute**
  limit refills on a clock, so it is waited out and retried (`LLM_RATE_LIMIT_WAIT_S`,
  default 70 s, lengthened by the provider's own `retryDelay` plus a margin but never
  shortened by it, because sleeping to the exact boundary races the reset); a
  **per-day** quota cannot be cleared by sleeping, so
  it abandons the provider immediately. Waiting out a per-minute limit costs a minute;
  failing on one costs the whole batch. The `503`/`429` distinction was not theoretical:
  see below.
- **A throttled or overloaded model hands over, and the rotation is remembered.** Gemini
  counts RPM, TPM and RPD per model, so each has its own allowance. The chain is
  `GEMINI_MODEL` → each of `GEMINI_FALLBACK_MODELS` → `LLM_FALLBACK_PROVIDER`. Every
  Gemini model but the last hands over at once on a `429` — or on a `503` or a read
  timeout that outlived its retry, which used to be swallowed per statement group and silently cost that
  group's fields — and only the last one cools down before the local fallback. A model
  that handed over rests for the cooldown, and since the chain is rebuilt per document,
  later documents start at the first model that is not resting instead of paying a
  wasted call to rediscover the same limit. The cheap models at the front of the queue can be made **patient**
  (`GEMINI_PATIENT_MODELS`): instead of handing over at once they wait out a per-minute
  limit and retry a `503`, `500` or timeout a few more times with a growing backoff, because
  what follows them costs three times as much and answers several times slower. A daily
  quota still hands over immediately. A document is extracted by one provider from
  start to finish, and the CSV's `model` column says which. Probed on this key:
  `gemini-3.6-flash` answered in 13.5 s against 2.4 s for `gemini-3.1-flash-lite`, and
  `gemini-3.7-flash` and `gemini-3.8-flash` each returned `503 high demand` before
  answering on a second attempt — which is the case the handover exists for.
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
                                 output/scorecard_ARCI_gemini_gemini-3.1-flash-lite_image_api.json
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
`detect_scale()` reads it directly and overrides the model **in both directions** — a
header naming a currency and no scale means full units, which is an answer rather than a
silence. Answering only "THOUSANDS" and never "FULL" left the expensive half of the
mistake uncaught for three ARCI filings; see
[*The scale field was the one the guards could not see*](#the-scale-field-was-the-one-the-guards-could-not-see).

**A guard that cannot run now says so.** If an issuer words its liability headings
differently, `_bank_rows_by_section()` returns an empty map and every wrong-row check
is skipped. Previously that was silent: the guard switched itself off while
confidence stayed high. It now raises `section_map_incomplete`.

### Run against three issuers it was never developed on

Claims about generalisation are worth little until the code meets a document it was
not written for, so the pipeline was run on **JPFA Q1 2022** (171 pages), **CPIN Q1
2022** (120 pages) and **EMAS Q3 2025** (97 pages).

JPFA is now labelled and scored (see *Evaluation*). For CPIN and EMAS there is still no
ground truth — but a filing checks a great deal of its own work:

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
| Scale taken from the model alone | Read from the printed header, which **overrides** the model in both directions |
| Share count assumed to sit on a statement page | Located anywhere in the document when no selected page carries it |
| A dot separates thousands | Convention decided per value; both are read |
| The text layer is what the PDF says it is | Checked, and OCR'd when it is not |
| A page is unreadable only if empty or glyph ids | Also when shredded into single characters |
| Bank-debt rows matched the literal `"Utang bank"` | Matched by concept: `Utang` / `Hutang` / `Pinjaman` / `Liabilitas` + `bank` |
| A row's amount was the first number after the label | Amounts read per column, so a note reference between them is skipped |
| Eval periods hard-coded to 2022 | Discovered from `data/raw/*_<TICKER>.pdf` |

### Sixty-five filings, five issuers, and four defects that were not the model's

The three-issuer run above was one filing each. The next step was the whole archive the
manual workflow actually covers: **65 filings, five issuers (ARCI, JPFA, CPIN, GTRA,
EMAS), 2022–2026**, through `scripts/pdf_to_csv.py`.

Two kinds of failure showed up, and neither was fixed by a better model. Both were fixed
in deterministic code.

#### The scale field was the one the guards could not see

ARCI prints the same header in all fourteen of its filings, word for word:

```
(Disajikan dalam Dolar Amerika Serikat,   (Expressed in United States Dollar,
kecuali dinyatakan lain)                   unless otherwise stated)
```

No scale word anywhere. The model still answered `THOUSANDS` on three of the fourteen,
and every figure in those rows came out a thousandfold too large — total assets recorded
as 13,503,189,704,433,**496** where the neighbouring quarter reads 12,882,307,892,235.

The model's variance is the smaller half of that story. `detect_scale()` could only
correct in **one direction**: it looked for "dalam ribuan", and finding it, overrode the
model. Finding nothing, it answered "unknown" and let the model stand. But a header that
names a currency and no scale is not silent — it is the filing saying *whole units*. The
header is the one place a scale is ever stated.

Worse, `reporting_scale` is the single field grounding **cannot** check, because a scale
is a word and grounding compares numbers. So the field that multiplies every other figure
was the one field with no independent verification at all.

It is now authoritative in both directions, and the warning it produces — which the
pipeline used to compute and then discard — is written into a `notes` column:

```
model said scale THOUSANDS, header says FULL - using FULL
```

Re-running ARCI Q2 2024 confirms it end to end: the model still says `THOUSANDS`
(reproduced under `gemini-3.5-flash-lite` as well, so this is not a capability gap that a
newer model closes), the header overrides it, and total assets come back
13,503,189,704,433.

#### A text layer can be present, readable-looking, and still useless

PT Grahaprima (GTRA) typesets some quarters so that every glyph is its own positioned
text run. pdfplumber returns the balance sheet one character at a time with the columns
interleaved:

```
T o ta l A s e t L a n c a r        2 0 .4 0 9 .3 0 1 .3
```

The page has thousands of characters, plenty of letters and no Private Use Area glyphs,
so all three existing usability tests passed it. The model, reading the image, extracted
the figures correctly. Then **grounding** — which verifies against the text layer —
found none of them, scored every field at zero and withdrew the lot.

The correlation across GTRA's fifteen filings is exact:

| Statement pages shredded | Result |
|---:|---|
| 0 | 10/10 |
| 2 | 9/10 |
| 3 | 8/10 |
| 6 | **2/10**, twelve fields withdrawn |

Measured over every page of all 65 filings, an ordinary page has ~0.12 single-character
tokens and a shredded one ~0.90. Two ratios have to agree before a page is called
shredded — single-character tokens **and** numbers reduced to lone digits — because
either alone has honest counter-examples: a note page of short bilingual labels scores
high on the first, a page of dates and note references on the second. 197 pages across
the archive are flagged; spot-checking the highest-scoring ones in each issuer found no
false positives.

A flagged page now goes down the OCR path that already existed for EMAS. Two further
defects surfaced on the way there and are fixed too:

- **`_is_garbled` threw the OCR'd page away again.** It called a page garbled when its
  lines were short — a proxy for "rotated page, carries nothing". But OCR returns a
  column layout as many short lines, so the page that had just been expensively
  recovered was discarded, and the figures on it failed grounding for want of anywhere
  to check them. It now tests the property directly: does this page carry figures?
- **The bank-debt validator had memorised one issuer's wording.** The prompt was
  rewritten to describe that row by *meaning* so `Utang bank`, `Pinjaman` and
  `Bank loans` all reach the same field — but `_bank_rows_by_section()` still matched
  the literal string `"Utang bank"`. GTRA writes `Pinjaman bank`, so the position check
  never ran for it: `section_map_incomplete` fired on all fifteen of its filings and
  nobody read it. A generalising prompt behind a memorising validator is not
  generalisation. The pattern now matches the concept, and the amounts are read per
  column so a note reference between label and figure (`Utang bank 2c,4 1.092.421.914.566`)
  no longer defeats it — which it had been doing on **every** issuer, silently.

#### Verified, not asserted

| Filing | Before | After |
|---|---|---|
| ARCI Q2 2024 | `aset` 13,503,189,704,433,496 | **13,503,189,704,433** |
| GTRA Q1 2026 | 2/10, twelve abstentions | **10/10, none** |
| CPIN Q1 2025 | 10/10 | 10/10, **byte-identical** |
| JPFA Q1 2023 | 9/10 | 9/10, unchanged |

GTRA Q1 2026's nine recovered figures match, to the rupiah, the ones that had been
collected by hand for that filing — an independent check rather than the system grading
itself.

The last two rows matter as much as the first two: a fix to the OCR and grounding path
is exactly the kind of change that quietly moves figures on documents that were already
working, and neither of these moved.

**Still open after all this:** GTRA Q1 2026 continues to raise
`section_map_incomplete`, because on an OCR'd page the section headings and the amounts
do not land on the same reconstructed line, so the position check genuinely cannot run.
The warning is correct. `pytesseract.image_to_data` returns per-word coordinates and
would rebuild those rows — the OCR path currently asks only for `image_to_string` and
throws the geometry away.

### Nine more issuers, and what their gaps actually were

The next round came from real use rather than from an audit: TOTL, LSIP, TLDN, TAPG,
DSNG, AADI, PTBA, ITMG and ADMR, 150 filings, with a backlog of what came back empty.
Every claim in that backlog was tested before anything was changed, and the finding
that shaped the rest was this: **almost none of the gaps were the model misreading a
page. The model was sent the wrong pages, or never asked the question.**

| Reported | Verified cause | Fixed by |
|---|---|---|
| ITMG never converts | The rate is on every one of its 18 reports, quoted directly — `Rupiah per AS$ 16,782` — and the reader only knew the `1.000 Rupiah = 0,0697` table form | A direct-quote reader |
| DSNG never has `total_share` | Authorised capital sits on the line beside the issued-capital phrase, so the page search stopped there; the count in issue is in a shareholder table 70 pages later | The share-page search (below) |
| PTBA `total_share` mostly empty | Counts printed English-style (`11,520,659,250`) — the share-count pattern only accepted dots | Either separator |
| PTBA "full error" | Not the documents: 10 of 11 errors were `429` rate limits from before cooldown and fallback existed | Already fixed; re-run 10/10 |
| TOTL scattered abstentions | Run-to-run variance caught by the guards; the same filing re-ran 10/10 | Nothing to fix |
| LSIP, TAPG, TLDN, PTBA Q4 gaps | Statement titles pushed past the title region by a translation notice, or split across bilingual columns | Title rules (below) |

**A direct rate quote is still the filing's own rate.** `_rate_from_direct_quote()` reads
`Rupiah per AS$`, `Rupiah per Dolar AS` and `US$1 = Rp…`, taking the first numeric column
as the current period and the rest as comparatives. It is anchored on the Rupiah side of
the phrase, so the `AS$ per Euro` row printed directly underneath is never mistaken for
it. All 18 ITMG filings now resolve — `14,349` for Q1 2022 through `17,856` for Q2 2026 —
and ITMG Q2 2026 extracts 10/10 in Rupiah. ADMR, AADI and ARCI read exactly the rates
they read before.

Those same dates are an independent check on ADMR and AADI, which only print a rounded
table (`Rupiah 10.000 = 0,56`). Across eighteen quarters their converted rate never differs
from ITMG's exact quotation by more than **0.7%**, inside the rounding the row's `notes`
already reports.

**The share count is looked for where it is unambiguous first.** Every one of the 14
issuers in the archive ends its shareholder table with a total row: the issued count
beside 100% of ownership. That row is the count in issue by construction, so it outranks
the older phrase search, which reaches a company's history first — DSNG's notes state
`1,844,700,000` shares at its listing, a figure that would misstate EPS and book value per
share fivefold while looking perfectly sourced. Three details each broke it once during
development and are now tested:

- **A percentage needs a mark.** `100,00`, `100%` or `100,000`, never a bare `100` — DSNG's
  history reads "Rp 100 (Rupiah penuh) per saham … 1,844,700,000 shares", a par value.
- **The table's heading may be on the page before its total**, as DSNG's is (77 and 78).
- **Authorised capital is recognised on its own line or under its label.** DSNG and five
  others print "Modal dasar:" above the count; ARCI prints the issued phrase above its
  count. The label line only disqualifies a count when neither line names issued capital.

Result: all 18 DSNG filings now reach `10.599.842.400`, and DSNG Q2 2025 extracts
10/10. PTBA Q1 2022 finds its count on page 114 and extracts 10/10.

**The note that was fetched for the count now decides the count.** That DSNG run first
came back 9/10 with the right page attached. The balance-sheet group had answered
`10.599.850.000` — issued capital divided by par value, printed nowhere, with a quoted
"evidence" line that does not exist — and because statements merge first, it beat the
`10.599.842.400` the note group read correctly. Grounding rejected the invention and the
correct answer went with it. `merge_group()` now lets the share-capital group override:
that page is only added when the statements were searched and found to print no count,
so a statement group's count is by construction not read. The prompt also forbids
computing a count from capital and par value. (Since superseded: statement groups are no
longer asked for any share count — see *total_share is the count outstanding*.)

**A scale header does not always start with a verb.** DSNG heads every statement
`(Dalam jutaan Rupiah, …)`, so the header reader found nothing and the model's scale went
unchecked. `(Dalam` and `(In` are now accepted — but only when the parenthesis names a
currency, because `(in accordance with PSAK 1)` read as a unit-less header would assert
full units over a correct `THOUSANDS`.

**LSIP prints no cash total at all.** Its balance sheet has "Kas dan setara kas" as a
heading over two amounts — related parties and third parties — and nothing on the heading
line itself:

```
Kas dan setara kas        5          Cash and cash equivalents
  Pihak berelasi      877.632   29   518.756    Related party
  Pihak ketiga      2.582.760      2.849.111    Third parties
```

Asked for `kas`, the model added them in its head and got it wrong on six of eighteen
filings — 3.460.442 for 3.460.392, off by between 2 and 128 — and grounding withdrew each
one, correctly, since that sum is printed nowhere. A higher image resolution (220 dpi)
fixed four of the six and left two wrong, which is what a symptom fix looks like. The
cause was asking for a conclusion, so the fix is the one `utang_bank`, `ekuitas` and
`total_share` already use: the model reports `kas_components`, the code adds them, and
each part is grounded on its own. Summed across all eighteen filings, the parts equal the
cash-flow closing balance exactly in all seventeen that print them.

Re-extracted at the default 150 dpi, checked against that closing balance:

| Filing | Before | After |
|---|---|---|
| LSIP Q1 2022, Q4 2022, Q1 2023, Q3 2023, Q4 2024, Q1 2025 | withdrawn | **correct, all six** |
| LSIP Q2 2022 (worked before) | correct | correct, now from parts |
| LSIP Q2 2026 (prints its own total) | correct | correct, read directly |
| TLDN Q1 2025 (receivable sub-lines directly under cash) | correct | correct, no parts taken |
| CPIN Q1 2025 | correct | correct |

The last two were the regression risk: a model that took the "Pihak berelasi / Pihak
ketiga" lines under *receivables* as cash would produce a total built from printed
numbers, and grounding would pass it. The prompt tells it to stop at the next heading,
and on both it did.

**The cash-flow statement repeats "Kas dan setara kas" too**, for different reasons. Its
labels wrap, so the net increase and the exchange-rate effect each leave the phrase alone
on a line beside a number. Those are movements and must not be taken or added; the prompt
names them as a trap, separately from the balance-sheet parts above, which must be.

#### Statement titles the page selector could not see

The remaining gaps were all one mechanism: the page selector recognises a statement by
its title in the first 250 characters of the page, and two layouts defeat that.

**A translation notice pushes the title out.** Many issuers open every page with "The
original consolidated financial statements included herein are in the Indonesian
language." and a bilingual company name. LSIP's titles then start at character 240–253,
TAPG's income statement at 236 — cut off mid-word. Every one of LSIP's 18 filings fell
back to its first ten pages, and for an annual report those are the cover, the directors'
statement and seven pages of auditor's report: Q4 extracted 1 field of 10. TAPG's income
statement was grouped as more balance sheet, a group that never asks for revenue.

**A two-column layout splits the title.** TLDN and PTBA print `LAPORAN POSISI` and
`KEUANGAN` on consecutive lines with the English column between them, so the phrase never
appears whole. TLDN's first balance-sheet page — the one carrying cash and current assets —
was left out; PTBA Q4 2025's balance sheet was never selected at all.

The obvious fix was measured and rejected. Widening the region to 300 characters repaired
LSIP and TAPG but moved the page span of ADMR, ITMG and PTBA filings that were already
correct, because note pages also mention the statements near their top. So eight
candidate rules were replayed against the saved title strips of all 215 filings, through
a harness first checked to reproduce the real selector with zero mismatches. The rule
adopted — remove the translation notice before measuring the region, and accept a title
split across lines — changed **only** the filings that were wrong (LSIP 18, TLDN 10,
TAPG 6, PTBA 2), plus two ARCI filings that gained a cash-flow continuation page they had
been missing. No filing in the archive falls back to its first pages any more, and none
is missing a balance sheet, income statement or cash flow.

Re-extracted on real filings:

| Filing | Before | After |
|---|---|---|
| LSIP Q4 2025 | 1/10 — cover and auditor's report | **10/10** |
| TAPG Q1 2024 | 8/10 — no revenue | **10/10** |
| TLDN Q1 2025 | 8/10 — no cash, no current assets | **10/10**, cash 821.851.671 as printed on page 5 |
| PTBA Q4 2025 | balance sheet never selected | **10/10** — after the bank-debt check below |
| ARCI Q1 2025 | 10/10 | 10/10 |

#### A position check must prove the wrong position

Once PTBA's balance sheet was selected, it came back 9/10 with `utang_bank` withdrawn by
`wrong_section`. The page prints its current portion of long-term bank borrowings as

```
Bagian jangka pendek dari
liabilitas jangka panjang:
Pinjaman bank  100  20  -
```

and the model reported 100 — correctly. The check disagreed for two reasons. `100` has no
thousands separator, so that row never entered the section map; and PTBA's heading says
"Bagian jangka pendek" where the pattern only knew "Bagian lancar". Unable to find 100
under the current-portion heading, the rule concluded the value had been copied from the
wrong row.

That conclusion was never supported. `wrong_section` asserts a figure was taken from
**another** heading's row, and that is only proven when the figure is found there. A
figure found under no heading at all is unverifiable, not misplaced. The rule now raises
its error only in the first case and a `section_map_incomplete` warning in the second, and
the heading pattern accepts PTBA's wording. The case the rule exists for — a long-term
figure reported as current — is still an error, in the same test. PTBA Q4 2025 now
extracts 10/10, with `utang_bank` 1.950.100 (short-term 1.950.000 plus current portion
100, in millions), exactly as printed.

#### total_share is the count outstanding

EPS, book value per share and PBV divide by the shares **outstanding**, not the shares
issued. Treasury shares — bought back and held by the issuer — share in neither profit nor
equity, and IAS 33 leaves them out of the EPS denominator. Three issuers in the archive
hold treasury shares, and each prints it differently:

| Issuer | As printed | Outstanding |
|---|---|---:|
| JPFA Q2 2025 | "Total saham beredar 11.627.669.901 (99,16%)" beside "Total 11.726.575.201 (100,00%)", page 112 | 11.627.669.901 |
| PTBA Q2 2025 | "Jumlah saham beredar 11,514,357,250 (99.95%)" beside issued 11,520,659,250, page 104 | 11.514.357.250 |
| EMAS Q4 2025 | treasury 1,448,866,615 (8.95%) and issued 16,180,232,675, **no outstanding total**, page 72 | 14.731.366.060 |

**The counts are read from one place only: the shareholder table in the notes.** The
share-capital line on the balance sheet and in the statement of changes in equity prints
the issued count and says nothing about what is outstanding, so it is no longer asked. The
equity statement, which was asked for nothing else, is no longer sent at all, and a count a
statement group volunteers anyway is dropped rather than merged. The table answers every
case:

| The table prints | `total_share` |
|---|---|
| a "Jumlah saham beredar" row (JPFA, PTBA) | that row |
| a treasury row and no outstanding row (EMAS Q4 2025) | the total less treasury |
| no treasury row (ARCI, CPIN, DSNG and most issuers) | the total — every share is outstanding |

The model reports the total row, `saham_beredar` and `saham_treasuri`; the code decides, and
keeps the total as `saham_ditempatkan` so the adjustment appears in the CSV. When an
outstanding figure agrees with the total less treasury, `total_share` is graded on those two
printed rows — EMAS's model once subtracted by itself and reported a `saham_beredar` printed
nowhere, which grounding rightly withdrew, and the total must not go with it.

**Why the table and not the phrase "saham beredar".** Every filing in the archive was searched
for the phrase and its English forms beside a share count. A figure outstanding *at the
reporting date* is printed only by JPFA and PTBA, and there it is a row of the shareholder
table. Everywhere else — TAPG, TLDN, TOTL, ARCI, CPIN, ITMG, EMAS — the phrase appears in the
EPS note as *weighted-average* shares outstanding: an average over the period, not the count
on the date, and the prompt names it as a trap. The shareholder table, by contrast, is printed
by every issuer, and it is where treasury shares are shown.

**Finding the table.** `find_shareholder_table_pages()` reads the text layer of every filing for
a total row — a share count beside 100% of ownership, on a page about shareholders — and takes
the first: the current date's table is printed before the comparative one. EMAS Q1 2026 prints
March 2026 on page 64 and December 2025, with its since-cancelled treasury shares, on page 65,
so only page 64 is sent. Details, each found by sweeping all 215 filings:

- **The count comes before the 100%.** ADMR Q2 and Q3 2025 list their subsidiaries as
  "100.00% 100.00% 1,069,356,077" — ownership, then total assets in dollars — on a page naming
  those subsidiaries' shareholders, and that page was found as the share table.
- **`100,0000` and a bare `100` are totals too** — TAPG Q3 2023, and ADMR Q1 2023's
  "Total 40,882,331,500 100 303,919,662". A bare 100 counts only on a line that opens with
  Total/Jumlah, so DSNG's "Rp 100 (Rupiah penuh) per saham" still does not.
- **A table split across pages brings its heading page along**, because the outstanding and
  treasury rows sit above the total.

Across the archive the table is found in the text layer of 203 filings, and each issuer's
total is stable from period to period. Twelve print it on an unreadable page; OCR'ing those
pages finds nine more (EMAS Q3 2025, GTRA Q1 2026, all five JPFA, TOTL Q3 2022 and Q3 2023),
at 44–63 s the first time and cached after. Three remain without: GTRA Q1 2024 and Q3 2025
print the table rotated, which neither the text layer nor page OCR can read, and TOTL Q1 2022.
Their `total_share` is empty rather than taken from the statements.

**The table prints two dates, so two guards remain**, both deterministic:

- **A total equal to a later 100% row is the comparative one** and is replaced by the first.
- **The balance sheet decides which date has treasury shares.** ITMG sold all its treasury
  shares in March and April 2022, but its Q2 2022 note still lists 33,369,100 of them under
  31 December 2021, on the same page as the current table. The balance sheet's current column
  prints a dash — `Saham treasuri 20  -  (19,211)` — and treasury and outstanding counts read
  from the note are then discarded. On the run below the model took that December row again,
  and this guard is what kept 1.129.925.000 right.
  A dash is only a nil in the amount column. From Q4 2024 JPFA prints
  `Saham treasuri - 98.905.300 saham (147.851) 2,24 (147.851)`, the dash separating label
  from count; read as a nil, it discarded a correct outstanding figure, leaving Q4 2024 and
  Q1 2026 empty and Q4 2025 at the issued 11.726.575.201. A dash followed by "N saham" is
  now punctuation. Replayed on the balance sheets of all 215 filings, that changed the
  verdict on exactly those three.

Re-extracted, all 14 JPFA filings now match their shareholder tables: 11.620.308.701 through
Q2 2023 (106.266.500 treasury), 11.627.669.901 from Q3 2023 to Q1 2026 (98.905.300), and
11.704.870.701 at Q2 2026 (21.704.500), four calls each.

Re-extracted with the table as the only source:

| Filing | `total_share` | From |
|---|---:|---|
| ITMG Q2 2022 | 1.129.925.000 | total; December 2021 treasury discarded by the guard |
| EMAS Q1 2026 | 14.731.366.060 | total, page 64 only |
| EMAS Q4 2025 | 14.731.366.060 | 16.180.232.675 less 1.448.866.615 treasury |
| JPFA Q2 2025 | 11.627.669.901 | printed outstanding row |
| PTBA Q2 2025 | 11.514.357.250 | printed outstanding row |
| ADMR Q2 2025 | 40.882.331.500 | total, page 77 (was the subsidiary table) |
| CPIN Q4 2025 | 16.398.000.000 | total, no treasury |
| DSNG Q2 2025 | 10.599.842.400 | total, no treasury |
| TAPG Q3 2023 | 19.852.540.000 | total printed as `100,0000` |

All nine at confidence 1.0, on `gemini-3.5-flash-lite` (ITMG was handed over from a
rate-limited `gemini-3.1-flash-lite`). The call count per filing is unchanged for a filing
whose selection includes an equity statement — that call is gone and the table's call
replaces it — but every filing now reads its text layer to find the table.

**This changes what the ground truth should say.** `JPFA.xlsx` labels `total share` as
11.726.575.201 in every period — the issued count — so JPFA's `total_share` will now score
as a miss until those labels are corrected per period. `EMAS.xlsx` has a separate problem:
its Q4 2025 label, 20.006.577.715, matches neither the issued count, the outstanding count
nor authorised capital printed in that filing.

### Honest confidence

| Case | Confidence | Why |
|---|---|---|
| ARCI, other years | High | Same template, four periods score 40/40 |
| Another IDX filer, IDR, millions | Medium-high | JPFA is scored: 36/36 on one run, 33/36 on another with three abstentions and nothing wrong. CPIN extracts cleanly but is unlabelled |
| Filer reporting in thousands | Medium | Same deterministic reader as millions, which now works on real filings; the thousands branch itself is still untested |
| Filer with a broken or absent text layer | Medium | Three distinct breakages now handled — glyph ids (EMAS), empty layers, single-character shredding (GTRA) — across 65 filings. OCR quality is the dependency this trades into, and it is not measured |
| Filer whose statement pages must be OCR'd | Medium-low | Figures and grounding recover, but the bank-debt position check cannot run: OCR does not preserve which heading a row sits under |
| Filer with no disclosed FX rate, reporting in USD | Refuses | By design; it raises rather than guessing a rate |
| Filer quoting its rate to two decimals | Works, with a caveat | 0.8% rounding uncertainty, reported on every conversion rather than hidden |

Grounding does not depend on the issuer at all, and neither do the balance-sheet
identity or containment rules. A new issuer is therefore more likely to produce
**abstentions and validation errors** than confident wrong numbers — which is what
both new issuers did: JPFA declined `total_share` rather than inventing one, and EMAS
abstained on everything rather than asserting figures it could not verify.

That behaviour is the design working, and JPFA has now shown it under measurement rather
than under fault injection: on the period whose balance sheet did not balance, three
fields were withdrawn and none was wrong.

**The gap that remains is still labels, one issuer further out.** CPIN and EMAS are
extracted but not *scored*, so "correct" for them rests on the filing's own internal
consistency rather than on measurement. Labelling either — the workflow is in
`.claude/skills/label-groundtruth/SKILL.md` — is the highest-value next step, and EMAS is
the more valuable of the two: its text layer is unreadable and its digits are grouped in
the English convention, so it exercises paths ARCI and JPFA never touch.

## Not built yet

Stated plainly because the brief asks for them:

- **Calibration of the confidence scores.** The weights are reasoned, not fitted; the
  threshold has not been swept against the eval set to find where precision and
  coverage actually trade off.
- **Cross-provider agreement as a fourth signal.** Running two models and scoring
  disagreement is the obvious next input to confidence, and the provider layer
  already supports it.
- **A third and fourth scored issuer.** CPIN and EMAS are extracted and self-checked but
  unlabelled. Two scored issuers is enough to have found real bugs; it is not enough to
  characterise the extractor.
- **Layout-aware OCR.** The OCR path asks tesseract for `image_to_string` and discards
  the geometry. `image_to_data` returns per-word coordinates, which would rebuild rows on
  an OCR'd page and let the bank-debt position check run there — the one guard still
  unable to work on a filing that had to be OCR'd. Measured at ~1 s per page, no new
  dependency.
- **A priced cost figure.** Tokens are measured; money needs a rate in
  `config/pricing.json`.
- **Asynchronous extraction.** The API holds the connection for the length of the job.
  See the trade-off note under *API surface* for the three conditions that would make
  that the wrong choice.

## With more time

1. **Label CPIN or EMAS.** JPFA was labelled during this work and immediately exposed two
   filename collisions and a hole in the abstention logic. A third issuer is the cheapest
   remaining source of that kind of finding — especially EMAS, whose text layer is
   unreadable and whose figures are grouped in the English convention.
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
  pdf_to_csv.py    unstructured PDF -> one structured CSV row per filing
  fetch_share_prices.py  market close per quarter; the one sheet input not in the filing
  build_dataset.py the three joined: figures + price + the eight ratios, one CSV
  run_eval.py      scorecard generation, failure classification
  compare_runs.py  regression gate between two scorecards
tests/
  test_guards.py   fault injection; proves each guard fires (and stays quiet)
data/
  raw/             ARCI, JPFA, CPIN (Q1-Q4 2022) and EMAS (Q3 2025)
  ground_truth/    six issuer workbooks; ARCI and JPFA are the two the eval scores
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
