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

Blocked: Docker is not installed on this machine (`docker: command not found`). Nothing
about containers will be written into the README as working until it has actually been
built and run here.

## Stage 5 — Artifacts

Not started.

## Stage 6 — README

Not started.
