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

Not started.

## Stage 3 — Evaluation through the API

Not started.

## Stage 4 — Docker

Blocked: Docker is not installed on this machine (`docker: command not found`). Nothing
about containers will be written into the README as working until it has actually been
built and run here.

## Stage 5 — Artifacts

Not started.

## Stage 6 — README

Not started.
