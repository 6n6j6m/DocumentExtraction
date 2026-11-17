---
name: claude-extract
description: How Claude (this session's subagents) is the extraction model of the PDF -> Excel pipeline - the project's extractor since 2026-11-17, replacing Gemini; every other step (filing, page selection, prompts, guards, validation, IDR conversion, prices, workbook, evaluation) stays code - then evaluate the run and consolidate the extractor's memory ("dream") so the next run learns. Use with pdf-to-excel for every extraction, and when the user asks to answer pending requests, compare runs, or evaluate/consolidate the extractor's memory.
---

# Claude as the extraction model

Code does the whole flow; Claude only answers the prompts the pipeline would have sent
to Gemini. Read `docs/CHECKPOINT.md` first if this session has not. Reply in Indonesian.

```
claude_extract.py run   ->  pages selected, prompts written as request files   (code)
extraction-reader       ->  one subagent per filing writes <key>.answer.json    (Claude)
claude_extract.py run   ->  answers read back; follow-up prompts or the row     (code)
   ... repeat until exit code is not 3 ...
evaluate + dream        ->  extraction-evaluator subagent                       (Claude + code)
```

How it works: `LLM_PROVIDER=claude-code` (src/claudecode.py). A prompt is keyed by a hash
of exactly what a model would be sent; with no answer for that key the filing stops
(`AnswerPending`) and no row is written. Since 2026-11-17 `.env` has
`LLM_PROVIDER=claude-code`, so `scripts/pdf_to_excel.py` itself uses Claude and rows go to
the main `~/FinancialReport/<T>/<t>.csv` and `<T>.xlsx` (rows answered earlier by Gemini
keep their `model` column until refreshed). `claude_extract.py run` is the same with the
provider forced; `--variant claude` writes `<t>_claude.csv` / `<T>_claude.xlsx` beside
the main files for a comparison. Exchange files:
`output/claude_exchange/<Q>_<YYYY>_<T>/`.

## Steps

1. **Scope.** Ticker(s) and periods. Start small: `--only Q4_2025 ...` limits the run to
   those periods (otherwise every filing missing from the CSV is asked - about 5
   requests per filing). Say how many filings and requests before a large batch.

2. **Round 1** (repo root, `source .venv/bin/activate`):
   ```bash
   python scripts/claude_extract.py run --ticker TRIN --only Q4_2025 --no-prices
   ```
   Any pdf_to_excel option works (`--inbox`, `--refresh`, `--retry-partial`,
   `--compare-gt`, `--dry-run`). Exit code 3 = answers pending.

3. **Answer.** `python scripts/claude_extract.py pending --ticker TRIN` lists the
   requests per filing. Spawn one `extraction-reader` subagent per filing (if that agent
   type is not loaded in this session, use `general-purpose` and tell it to follow
   `.claude/agents/extraction-reader.md`). Several filings may run in parallel. The brief
   is only: the filing folder, the repo root, the request file names. Do NOT answer
   requests in the main session and do not give the reader labels, earlier results or
   your own reading - its independence is what the evaluation measures.

4. **Next round.** Run the same `run` command again. It reads the answers; a filing whose
   answers left fields null may produce follow-up requests (retries) - answer those the
   same way. Repeat until the exit code is 0 or 1. Then run once more without
   `--no-prices` (or let the last round fetch prices) to build the workbook.

5. **Evaluate and dream.** Spawn the `extraction-evaluator` subagent (or
   `general-purpose` told to follow `.claude/agents/extraction-evaluator.md`) with the
   tickers and periods. It runs `evaluate_output.py` (`--variant claude` for a side
   copy), decides each disagreement against the PDF, compares with the previous row
   (`<t>.csv.bak`, often Gemini's), consolidates
   `memory/extraction/` and logs the score with `memory record`. Check its memory diff
   yourself (`git diff memory/`) - a wrong note reaches every later request.

6. **Act on the result.** `reader` errors: re-ask after memory changed with
   `run ... --refresh <period>` (delete that filing's `*.answer.json` first, or the cached
   answers are reused). `selection`/`postprocess`: fix the code with a test, then rerun.
   `label`: propose a correction, apply only with the user's approval (as in
   `apply_label_corrections.py`, logged in `CORRECTIONS.md`).

7. **Report and close out.** Score before/after, cost in requests and subagents, memory
   changes. Add a `docs/CHECKPOINT.md` entry. Do not commit.

## Measuring whether memory helps

The article this follows (Anthropic, "components of agent memory") measures memory
against a stateless baseline. To do that here: same filings, a second exchange folder,
memory off, then compare the logged scores.
```bash
CLAUDE_MEMORY=off CLAUDE_EXCHANGE_DIR=output/claude_exchange_nomem \
  python scripts/claude_extract.py run --ticker TRIN --only Q4_2025 --variant claude_nomem
```
`output/claude_memory_runs.jsonl` holds every `memory record` with its digest. Claim an
effect only from paired runs on the same filings; n of a few filings is not a result.

## Rules

- Never write `data/ground_truth/`; never put a label or extracted figure in memory
  (`memory lint` refuses it).
- The reader never sees labels, CSVs, evaluation reports or the full PDF.
- Answers are cached by prompt hash: identical prompts are never re-asked. Delete the
  answer files to re-ask on purpose.
- Do not commit; no AI attribution.
