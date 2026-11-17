---
name: pdf-to-excel
description: Run the end-to-end pipeline that turns IDX financial-statement PDFs into an issuer's ratio workbook (~/FinancialReport/<TICKER>/<TICKER>.xlsx) - file new downloads, extract every filing with Claude (extraction-reader subagents answer the pipeline's prompts), fetch share prices, write the Excel with ratio formulas, and report every blank cell with its reason. Use when the user asks to process, extract, update or "jadikan Excel" the financial reports of one or more tickers, says new reports were downloaded, or asks to rebuild or refresh an issuer's workbook.
---

# PDF -> Excel pipeline

One command does the whole job: `scripts/pdf_to_excel.py`. This skill is how to run
it, read what it says, and report back without breaking the rules of this repo.

Read `docs/CHECKPOINT.md` first if this session has not (CLAUDE.md requires it). Reply to
the user in Indonesian.

## What the script does

| Step | What | Where it comes from |
|---|---|---|
| 1. File | new downloads -> `~/FinancialReport/<T>/<Q>_<YYYY>_<T>.pdf` (period read from the PDF's content, duplicates caught by SHA-1, never moves or replaces) | `organize_filings.plan` |
| 2. Extract | each PDF not yet in `<t>.csv` -> one row (full Rupiah, abstentions, issues) | `pdf_to_csv.extract_row` |
| 3. Price | close on 17 Jun / 17 Aug / 17 Nov / 17 May (next year), nearest session | `fetch_share_prices.collect` |
| 4. Excel | `<T>.xlsx`: rows 4-13 figures, 14 price, 15-22 ratio formulas, sheet `Catatan` | this script |

Extraction is incremental: a filing already in the CSV is never re-sent to the model
unless `--retry-partial`, `--refresh` or `--force` asks for it. A value typed by hand
into the workbook is kept (coloured orange, the pipeline's reading in the cell comment)
unless `--overwrite`. A blank cell is coloured red with the reason as a comment.

## Steps

1. **Work out the request.** Ticker(s); whether there are new downloads (usually
   `~/Downloads/idx`) -> `--inbox`; whether filings must be re-extracted (after a code
   fix: `--refresh Q1_2023 ...`; rows that came back partial: `--retry-partial`).

2. **Preflight.** From the repo root, with `source .venv/bin/activate`:
   - The workbook must be closed in Excel (the script refuses if `~$<T>.xlsx` exists).
   - **The extraction model is Claude** (user's decision 2026-11-17): `.env` has
     `LLM_PROVIDER=claude-code` and no fallback. Do not switch back to Gemini or Ollama
     unless the user asks. No API key is needed for extraction.

3. **Dry run first, always:**
   ```bash
   python scripts/pdf_to_excel.py --ticker TRUK --inbox ~/Downloads/idx --dry-run
   ```
   It lists what would be filed (`copy` / `skip` / `conflict`) and which PDFs would be
   extracted. Tell the user how many filings (about 5 requests and one reader subagent
   each). A `conflict` is never forced: report it, and leave
   `organize_filings.py --overwrite` to the user's decision. For a big batch, use
   `--only Q1_2023 ...` to go in chunks.

4. **Run it in rounds** (the `claude-extract` skill has the details):
   ```bash
   python scripts/pdf_to_excel.py --ticker TRUK --inbox ~/Downloads/idx --compare-gt --no-prices
   ```
   - Exit code **3** = filings wait for answers. `python scripts/claude_extract.py
     pending --ticker TRUK` lists them. Spawn one `extraction-reader` subagent per filing
     (in parallel), brief = the filing folder + request file names, nothing else. Never
     answer the requests in the main session.
   - Run the same command again; repeat until the exit code is not 3. Then run once
     without `--no-prices` so prices and the workbook are written.
   - The CSV is saved after every finished filing; answers are cached by prompt, so an
     interrupted run loses nothing.

5. **Read the output and report** (numbers only from the run, never estimated):
   - per ticker: periods, filings extracted this run, `ok` / `partial` / `error`;
   - every `blank:` line with its reason (comment in the cell, `abstention_details` in
     the CSV);
   - every `≠ ... kept the hand-entered value` line;
   - prices marked `PROVISIONAL` (the 17th has not arrived): a rerun after that date
     replaces them automatically, because the pipeline owns those cells;
   - `--compare-gt` differences, if the issuer has a label workbook;
   - the workbook path, as a link.

6. **Evaluate the run - always.** Spawn the `extraction-evaluator` subagent (it follows
   the `evaluate-extraction` rules and then consolidates `memory/extraction/` -
   "dreaming"); review its memory diff with `git diff memory/`. It runs
   `python scripts/evaluate_output.py --ticker <T>`, decides every flagged cell against
   the PDF (extractor wrong / label wrong / convention / filing issue), fix the extractor
   and rerun the affected periods with `--refresh` (a refresh reuses cached answers
   when the prompt is unchanged: delete that filing's `*.answer.json` in
   `output/claude_exchange/` to have it read again), propose label corrections for the
   user's approval, and report the scorecard before and after. A blank or a difference
   is investigated, never filled: do not type a figure into a CSV or workbook by hand to
   make it go away.

7. **Close out.** Add a checkpoint entry to `docs/CHECKPOINT.md` and update "Status
   sekarang" / "Pekerjaan tertunda" if anything meaningful changed. Do not commit.

## Options

| Flag | Use |
|---|---|
| `--inbox DIR` | file new downloads first |
| `--only Q1_2023 ...` | extract only these periods this run |
| `--retry-partial` | re-ask filings whose row is partial or error |
| `--refresh Q1_2023 ...` | re-extract named periods |
| `--force` | re-extract everything (expensive: confirm with the user first) |
| `--excel-only` | rebuild the workbook from the CSV, no model calls |
| `--no-prices` | skip Yahoo; keep the prices the workbook has |
| `--overwrite` | replace hand-entered workbook values (confirm with the user first) |
| `--compare-gt` | read-only diff against `data/ground_truth/<T>.xlsx` |
| `--archive DIR` | another archive root (default `~/FinancialReport`) |
| `--dry-run` | show, write nothing |

## Rules that do not bend

- **Never write `data/ground_truth/`.** Those are the eval labels; filling them from the
  extractor makes the scorecard measure the model agreeing with itself. The script
  refuses to, and so does this skill. Label changes go through `label-groundtruth`,
  with the user's approval and a `CORRECTIONS.md` entry.
- **Quota or rate limit: stop.** The script stops at the first quota error and keeps
  what it has. Tell the user and rerun later. No other API key, account or project.
- **IDX downloads are done by the user in a browser.** IDX sits behind a bot check;
  do not try to script or bypass it.
- **Do not commit or stage** unless the user asks; no AI attribution in commits.
- Backups: the previous CSV is kept as `<t>.csv.bak` and the previous workbook as
  `<T>.xlsx.bak` on every run that changes them.
