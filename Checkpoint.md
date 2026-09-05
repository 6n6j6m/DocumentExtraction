# Checkpoint

Development log for the serving layer — the three items the brief's Technical Notes ask
for that the README listed under *Not built yet*: an HTTP API brought up by
`docker compose up`, evaluation as a one-shot command in the same compose project running
against that API, and cost visibility alongside the latency that was already reported.

One entry per development instruction completed. Question-and-answer exchanges are not
logged.

---

## Stage 1 — Type validation at the boundary, and usage accounting

**Done**

- `src/schema.py`: `from_dict` now rejects values of the wrong type instead of accepting
  anything. Every offending field is named in one message; `int` is accepted where a
  `float` is declared and normalised; `bool` is rejected explicitly, because it subclasses
  `int` in Python and `{"aset": true}` would otherwise have become the figure `1.0`.
  `SchemaTypeError` subclasses `ValueError`, so existing handlers keep working while the
  API layer can still map it to a 400. `strict=False` preserves the old behaviour for
  callers that have already coerced their input.
- `src/usage.py`: a per-document accumulator recording LLM calls, input/output tokens and
  per-stage latency, with prices looked up from `config/pricing.json`.
- `config/pricing.json`: ships with **no cloud prices**. Locally served models are priced
  at zero, which is true and keeps a cloud-versus-local comparison from looking like
  missing data.
- `src/llm.py`: both providers record their own reported token counts —
  Gemini's `usageMetadata`, Ollama's `prompt_eval_count`/`eval_count`. The accumulator is
  passed into `complete()` rather than stored on the provider, so a batch running several
  documents through one provider cannot interleave two documents' counters.
- `src/extract.py`: threads the accumulator through both the text and image paths, times
  `select_pages` / `read_text` / `extract` / `assess` separately, attaches the result, and
  prints it in the CLI.
- `tests/test_usage.py`: 13 tests covering both halves.

**Verified**

`python -m pytest tests/ -q` → **37 passed** (24 existing guards unchanged, 13 new).

A real run, `python src/extract.py data/raw/Q1_2022_ARCI.pdf`:

```
=== USAGE ===
  3 LLM call(s) | select_pages 5.9s, read_text 0.3s, assess 0.0s, extract 9.9s
  tokens in 18019 / out 982
  cost - (no price configured for gemini-3.1-flash-lite - add it to config/pricing.json)
```

Page selection costs about a third of the wall clock on this filing, which a single total
would have hidden behind the model.

**Open**

- Cost is `null` by design until a tariff is configured. Tokens are real.
- Usage is not yet in the scorecard — that lands with the evaluation path in stage 3.

---

## Stage 2 — HTTP API

**Done**

- `src/api_models.py`: pydantic response models. The API is the contract callers write
  code against, and a typed response fails here when a field is renamed rather than at
  the caller's parser a week later.
- `src/api.py`: `GET /health`, `GET /schema`, `POST /extract`, `POST /extract/batch`.
  FastAPI is transport only — no parsing, no scoring, no arithmetic on a figure in any
  handler. `/extract` returns values **as printed**; conversion to Rupiah stays in
  `normalize.py` where the harness can reach it.
- `/health` is shallow by default and contacts the provider only on `?deep=true`,
  cached 30s. A compose healthcheck every 10s would otherwise spend ~8,600 provider
  calls a day to say "I am alive".
- `/schema` is generated from the extractor's own definitions (`FIELDS`, `EXCEL_ROWS`,
  `DERIVED_FROM`, `FIELD_TYPES`), so the published contract cannot drift from the code.
- Batch isolates failure per document and bounds concurrency with
  `API_MAX_CONCURRENCY` (default 2).
- Uploads are validated by magic bytes, not by filename or content type, and deleted
  after the request.
- Structured JSON-line logs per request.
- `tests/test_api.py`: 11 tests against a stubbed provider — no network, no key.

**Found and fixed while testing**

`test_provider_unavailable_is_503` failed with 422. `extract_from_pdf` was catching
`LLMUnavailable` per provider and ending with a generic `LLMError("Every provider
failed")`, so the API told the caller their *request* was bad when the truth was that
the provider was rate limited — and the provider's own message was lost. The reason each
provider gave up is now carried out of the loop, and `LLMUnavailable` is re-raised
naming every provider that failed. A caller now gets 503 and knows to retry rather than
to go looking for a fault in their PDF.

**Verified**

`python -m pytest tests/ -q` → **48 passed**.

Live against the real model, `uvicorn api:app --app-dir src`:

```
GET /health          {"status":"ok","provider":"gemini:gemini-3.1-flash-lite",
                      "provider_reachable":null,"checked":"shallow"}
GET /health?deep=true {"provider_reachable":true,"checked":"deep"}
POST /extract        Q1_2022_ARCI.pdf → pages [5..12], aset 694,671,337,
                     utang_bank 102,357,484, abstained [], issues 0,
                     3 LLM calls, 18,019 in / 982 out
POST /extract (bad)  HTTP 400 "fake.pdf: not a PDF (expected a %PDF header,
                     got b'# Financ')"
POST /extract/batch  count 3, ok 2, failed 1 — the corrupt file returned its own
                     error and the two filings still returned their figures
```

Concurrency measured rather than assumed, same two filings through `/extract/batch`:

| `API_MAX_CONCURRENCY` | Wall clock |
|---|---|
| 1 | 50.0 s |
| 2 | 33.4 s (**−33%**) |

**Open**

- Batch-level `cost` is null and points at the per-document reports; only per-document
  costs are priced.
- `run_eval.py` cannot target the API yet — stage 3.

## Stage 3 — Evaluation through the API

**Done**

- `scripts/run_eval.py` takes `--api-url` (defaulting to `$EVAL_TARGET`). Empty means
  the in-process path, which stays the default so the tests need no container.
  `extract_via_api` posts the filing and returns the same `FinancialStatementExtraction`
  the library would have produced; **everything after that is the same code** —
  normalising to Rupiah, comparing, classifying failures. There is no second scoring
  implementation to keep in step.
- The API run is tagged `..._api` in the scorecard and prediction-cache names. Without
  it the two runs overwrite each other and the comparison meant to prove they agree
  becomes a run compared with itself — the same trap the input mode is already in that
  name to prevent.
- When targeting a service, the provider is read from its `/health` rather than from
  this process's environment, which would otherwise mislabel the run with the client's
  configuration.
- Usage totals per period and per run land in the scorecard and the CLI summary.

**Verified** — both paths, `--no-cache`, four ARCI periods:

```
in-process             40/40   13 LLM calls   75,151 in / 4,085 out   24-65s (mean 45s)
http://localhost:8077  40/40   13 LLM calls   75,151 in / 4,085 out   25-40s (mean 31s)
```

`compare_runs.py` between them: **no regressions**. And cell by cell, which is the
stronger claim:

```
sel dibandingkan: 40
sel berbeda     : 0   (status, as-printed value and IDR value identical in all 40)
```

**Open**

- The latency difference between the two runs is not a property of the API: the
  in-process run OCR'd nothing but paid page selection cold, and per-document times vary
  by filing. Not reported as a speed-up, because one pair of runs cannot support that.

## Stage 4 — Docker

**Done and verified.** Docker installed via Colima; everything below is real output.

```
docker compose build            → Successfully tagged idx-extraction:latest   (608 MB)
docker compose up -d            → healthy after 9s
curl localhost:8000/health      → {"status":"ok","provider":"gemini:gemini-3.1-flash-lite",
                                   "git_commit":"…","checked":"shallow"}
docker compose run --rm eval    → 40/40, written to /app/output → ./output on the host
```

The build needed no fixes. Two things did:

**`git_commit` came back null inside the container**, because `.dockerignore` excludes
`.git` — correctly, but it cost the scorecard the one field that makes two runs
comparable. The build now takes a `GIT_COMMIT` arg and both `api.py` and `run_eval.py`
fall back to it when there is no git to ask.

**The first containerised run scored 39/40.** Gemini answered one call with a 503
"experiencing high demand". The system did the right thing — partial result, HTTP 200,
scored `missed` rather than `wrong`, nothing invented — but the field was recoverable, so
a bounded retry now follows a 503. A 429 still is not retried: a capacity spike invites a
retry, a throttle spends the allowance we have just exhausted. The 39/40 scorecard is
committed as `output/scorecard_container_2026-09-03_upstream_503.json`; `compare_runs.py`
between it and the current run shows `Q1 kas_dari_aktivitas_operasi missed -> correct`.

Tests 48 → 51 (retry recovers a 503, a 429 is not retried, retries are bounded).

## Stage 5 — Artifacts

**Done.** In `output/`:

| File | What it is |
|---|---|
| `scorecard_gemini_gemini-3.1-flash-lite_image.json` | in-process run, 40/40 |
| `scorecard_gemini_gemini-3.1-flash-lite_image_api.json` | the containerised run against the service, 40/40 |
| `scorecard_container_2026-09-03_upstream_503.json` | the 39/40 run, kept as evidence |
| `scorecard_baseline_2026-09-03_leaked_prompt.json` | pre-de-leak baseline, so the regression gate is demonstrable |
| `predictions/<provider>_<mode>[_api]/` | per-document results |

## Stage 6 — README

**Done.** Quick start now leads with `docker compose up` / `docker compose run --rm eval`
and the local path follows. New *API surface* section with the four defensible decisions
and the synchronous trade-off. *Cost* table beside *Latency*, both from real runs. New
*The first real failure, and what it cost* under Resilience. *Not built yet* keeps
calibration, cross-provider agreement, a scored second issuer, a priced cost figure and
async extraction.

## Stage 7 — Self-review against the PDF's Evaluation Criteria

| Aspect | Standing | The thin part |
|---|---|---|
| Evaluation Rigor | Partial | One labelled issuer. The failure taxonomy has now seen one real failure (an upstream 503) but still no real *extraction* error. |
| Extraction Quality | Strong | Four issuers, three unseen during development; multi-page, tables, absent fields, nothing invented. Only ARCI is measured. |
| LLM/VLM Engineering | Strong | Confidence computed from checkable signals; abstention removes the value. Weights reasoned, not calibrated. |
| Production-Readiness | Strong | API, batch with per-document isolation, compose up + one-shot eval, cost and latency per stage, a retry added because of an observed failure. Cost is unpriced by choice. |
| Agentic Development | Good | One skill, genuinely used; an audit trail of what verification found that reasoning had missed. |
| Code Quality & Communication | Strong | 51 tests, none touching the network. `src/` still uses flat imports rather than being a package. |

---

## Stage 8 — Reading method over label matching, and a cheaper scan

Prompted by testing against a 65-file corpus (ARCI, CPIN, EMAS, GTRA, JPFA — five
issuers, 2022 to 2026) where misses and misreadings appeared.

**Prompts rewritten around meaning, not wording.** Each field is now described by what
it MEANS, where it structurally SITS, how to DISAMBIGUATE it from neighbouring lines,
and the TRAP actually observed. Wordings are illustrations, marked non-exhaustive. Two
cases show why: equity attributable to the parent is a bare `Sub total` for ARCI and a
named section total elsewhere, so it is now identified by the property *this figure +
non-controlling interest = total equity*; and bank debt is `Utang bank` for ARCI but
`Pinjaman` for EMAS, so the prompt describes the concept and its section rather than the
noun. The model is also asked to check its reading against the statement's own
identities before answering.

Verified against a filing annotated by hand: **10/10**, including both traps in it —
the share count for the current date rather than the parenthesised earlier one
(25.235.000.000, not 24.835.000.000), and `Sub total` rather than `Total Ekuitas`.
Across five issuers and four years every extraction balances: `aset − liabilitas −
ekuitas` equals the non-controlling interest in each.

**Page selection now reads title regions, not pages.** Selection matches on statement
titles, which are printed at the top of a page; reading whole pages to find them cost
three minutes on a 97-page filing whose text layer is glyph ids. Unreadable pages are
now OCR'd cropped to the top 35% at 120 dpi instead of full-page at 300 — about a
twentieth of the pixels. The share-capital search was reordered to look in the selected
pages first, since those must be read in full anyway, and only widen when none carries a
count. **3:00 → 1:01**, identical pages selected.

**Three real defects the corpus exposed**

- *GTRA total assets was abstained away.* Its text layer splits the leading digit from
  the separator — `1.092.421.914.566` extracts as `1 .092.421.914.566` — and the
  existing repair only closed gaps between two digits. The most basic field in the
  filing was discarded on a balance sheet that balanced to the rupiah.
- *Nil and missing were the same answer.* EMAS reports borrowings but none from a bank,
  so the truthful answer is 0; the model returned null. For a leverage ratio those are
  wrong in opposite directions, so the prompt now distinguishes them and treats a dash
  in a numeric column as the value nil.
- *A zero was position-checked.* CPIN has no separate current-portion bank row, so 0 is
  correct — but the wrong-row guard, using a fallback added for JPFA, compared that zero
  against the short-term row and abstained on two correct extractions. A zero says the
  row does not exist; asking which row it came from is a category error.

**Verified**: 56 tests (27 guards). The three files above re-run clean at 10/10.

**Open**

- Prompt grew from ~2,400 to ~5,000 tokens; input per filing ~18,000 → ~28,000.
- The corpus is unlabelled apart from ARCI and JPFA, so "correct" for the other three
  rests on the balance-sheet identity and grounding, not on measurement.
