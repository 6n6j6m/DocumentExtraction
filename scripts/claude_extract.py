#!/usr/bin/env python3
"""
The PDF -> Excel pipeline with Claude Code as the extraction model.

Everything is the existing code (scripts/pdf_to_excel.py and src/); the only difference
is the provider: LLM_PROVIDER=claude-code turns every model call into a request file that
a Claude session answers (see src/claudecode.py). Rows go to <t>.csv and the
workbook to <T>.xlsx -- Claude is the project's extractor since 2026-11-17 (.env
LLM_PROVIDER=claude-code). `--variant claude` writes <t>_claude.csv instead, for a
side-by-side comparison.

    python scripts/claude_extract.py run --ticker TRIN --only Q4_2025      # round 1, 2, ...
    python scripts/claude_extract.py pending --ticker TRIN                  # what to answer
    python scripts/claude_extract.py check <...>.answer.json                # one answer
    python scripts/claude_extract.py memory lint                            # memory health
    python scripts/claude_extract.py memory record --ticker TRIN            # log an eval

`run` takes every option of pdf_to_excel.py (--inbox, --only, --refresh, --retry-partial,
--compare-gt, --dry-run, ...). It exits 3 while answers are pending; run it again after
answering until it exits 0 or 1 (1 = finished with blanks or partial rows).
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

MEMORY_DIR = ROOT / "memory" / "extraction"
RUN_LOG = ROOT / "output" / "claude_memory_runs.jsonl"
EVAL_DIR = ROOT / "output" / "evaluation"

# Budgets for the injected layer. Small on purpose: every line reaches every request.
MAX_INDEX_LINES = 60
MAX_PAGE_LINES = 80
MAX_TOTAL_CHARS = 24_000
_NOTE = re.compile(r"^- \((verified|hipotesis) (\d{4}-\d{2}-\d{2}); bukti: [^)]+\) \S")


def _setup_env(variant: str) -> None:
    os.environ["LLM_PROVIDER"] = "claude-code"
    os.environ["LLM_FALLBACK_PROVIDER"] = ""        # never hand a filing to Ollama
    os.environ["PIPELINE_VARIANT"] = variant


def cmd_run(argv: list) -> int:
    # Claude is the project's extractor (2026-11-17): rows go to the main <t>.csv and
    # <T>.xlsx. --variant claude keeps a side-by-side copy for comparisons.
    variant = ""
    if "--variant" in argv:
        i = argv.index("--variant")
        variant = argv[i + 1]
        del argv[i:i + 2]
    _setup_env(variant)
    import importlib.util
    spec = importlib.util.spec_from_file_location("pdf_to_excel",
                                                  ROOT / "scripts" / "pdf_to_excel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.argv = ["pdf_to_excel.py", *argv]
    return module.main()


def cmd_pending(argv: list) -> int:
    from claudecode import pending_requests
    ticker = argv[argv.index("--ticker") + 1] if "--ticker" in argv else None
    items = pending_requests(ticker)
    if "--json" in argv:
        print(json.dumps(items, indent=1))
        return 0
    if not items:
        print("no pending requests")
        return 0
    by_filing = {}
    for item in items:
        by_filing.setdefault(item["filing"], []).append(item)
    print(f"{len(items)} request(s) in {len(by_filing)} filing(s)")
    for filing, group in by_filing.items():
        print(f"  {filing}")
        for item in group:
            extra = f", {item['images']} image(s)" if item["images"] else ""
            print(f"    {item['request']}  [{', '.join(item['fields'])}{extra}]")
    return 0


def cmd_check(argv: list) -> int:
    from claudecode import check_answer
    worst = 0
    for path in argv:
        problems = check_answer(Path(path))
        print(f"{'✓' if not problems else '✗'} {path}")
        for problem in problems:
            print(f"    {problem}")
        worst = max(worst, 1 if problems else 0)
    return worst


# --- memory -----------------------------------------------------------------------------

def memory_digest() -> str:
    from claudecode import memory_digest as digest
    return digest()


def _run_digests(ticker: str, files: list) -> list:
    """The memory digests the evaluated filings' requests were written with."""
    from claudecode import exchange_dir
    digests = set()
    for name in files:
        for meta in (exchange_dir() / Path(name).stem).glob("*.meta.json"):
            digests.add(json.loads(meta.read_text()).get("memory_digest") or "unknown")
    return sorted(digests)


def _label_values(ticker: str = None) -> set:
    """Every figure in the label workbooks (one issuer's, or all): memory must hold none."""
    from labelaudit import read_columns
    paths = ([ROOT / "data" / "ground_truth" / f"{ticker}.xlsx"] if ticker else
             sorted((ROOT / "data" / "ground_truth").glob("*.xlsx")))
    values = set()
    for path in paths:
        if not path.exists():
            continue
        columns, _ = read_columns(path)
        for fields in columns.values():
            for value in fields.values():
                if value is not None and abs(value) >= 1_000_000:
                    values.add(round(abs(value)))
    return values


_BIG_NUMBER = re.compile(r"\d{1,3}(?:[.,]\d{3}){2,}|\d{7,}")


def lint_memory() -> list:
    """Problems that make memory unsafe or too costly to inject. [] = healthy."""
    problems = []
    if not MEMORY_DIR.exists():
        return [f"{MEMORY_DIR} does not exist"]
    total = 0
    all_labels = None
    for path in sorted(MEMORY_DIR.rglob("*.md")):
        rel = path.relative_to(MEMORY_DIR.parent)
        text = path.read_text(encoding="utf-8")
        total += len(text)
        lines = text.splitlines()
        limit = MAX_INDEX_LINES if path.name == "MEMORY.md" else MAX_PAGE_LINES
        if len(lines) > limit:
            problems.append(f"{rel}: {len(lines)} lines > {limit}; consolidate")
        for number, line in enumerate(lines, 1):
            if line.startswith("- (") and not _NOTE.match(line):
                problems.append(f"{rel}:{number}: note without '(verified|hipotesis "
                                f"YYYY-MM-DD; bukti: ...)'")
        # Contamination: a figure equal to a label would let the extractor copy the
        # answer it is scored against.
        ticker = path.stem if path.parent.name == "issuers" else None
        if ticker is None and all_labels is None:
            all_labels = _label_values()
        labels = _label_values(ticker) if ticker else all_labels
        for number, line in enumerate(lines, 1):
            for match in _BIG_NUMBER.finditer(line):
                value = int(re.sub(r"[.,]", "", match.group(0)))
                if any(abs(value - label) <= 1 or abs(value * 1000 - label) <= 1000
                       for label in labels):
                    problems.append(f"{rel}:{number}: {match.group(0)} is a label value; "
                                    f"memory may describe WHERE a figure is, never the figure")
    if total > MAX_TOTAL_CHARS:
        problems.append(f"memory is {total:,} chars > {MAX_TOTAL_CHARS:,}; consolidate")
    return problems


def _latest_eval(ticker: str, variant: str):
    pattern = f"{ticker}_{variant}_*.json" if variant else f"{ticker}_2???-??-??.json"
    files = sorted(EVAL_DIR.glob(pattern))
    return files[-1] if files else None


def cmd_memory(argv: list) -> int:
    action = argv[0] if argv else "lint"
    if action == "lint":
        problems = lint_memory()
        for problem in problems:
            print(f"✗ {problem}")
        print("memory ok" if not problems else f"{len(problems)} problem(s)")
        print(f"digest {memory_digest()}")
        return 1 if problems else 0
    if action == "record":
        ticker = argv[argv.index("--ticker") + 1].upper()
        variant = argv[argv.index("--variant") + 1] if "--variant" in argv else ""
        path = _latest_eval(ticker, variant)
        if not path:
            print(f"no evaluation of {ticker} in {EVAL_DIR}; run evaluate_output.py "
                  f"--ticker {ticker}" + (f" --variant {variant}" if variant else "")
                  + " first")
            return 1
        result = json.loads(path.read_text())
        cells = result["cells"]
        labelled = [c for c in cells if c["label"] is not None]
        entry = {
            "date": date.today().isoformat(), "ticker": ticker, "variant": variant,
            "evaluation": str(path.relative_to(ROOT)),
            "memory": os.getenv("CLAUDE_MEMORY", "on"),
            # The memory the run USED (from its requests), and the memory after dreaming.
            "memory_digest_used": _run_digests(
                ticker, [f["file"] for f in result.get("filings", []) if f.get("file")]),
            "memory_digest_now": memory_digest(),
            "answer_model": os.getenv("CLAUDE_CODE_MODEL", "session"),
            "labelled": len(labelled),
            "correct": sum(1 for c in labelled if c["status"] == "correct"),
            "filled": sum(1 for c in cells if c["pred"] is not None), "cells": len(cells),
        }
        if RUN_LOG.exists() and any(
                json.loads(line).get("evaluation") == entry["evaluation"]
                for line in RUN_LOG.read_text().splitlines() if line.strip()):
            print(f"already recorded: {entry['evaluation']}")
            return 0
        RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RUN_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        print(json.dumps(entry))
        return 0
    print(f"unknown memory action {action!r} (lint | record)")
    return 2


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    command, argv = sys.argv[1], sys.argv[2:]
    handlers = {"run": cmd_run, "pending": cmd_pending, "check": cmd_check,
                "memory": cmd_memory}
    if command not in handlers:
        print(f"unknown command {command!r}; see --help")
        return 2
    return handlers[command](argv)


if __name__ == "__main__":
    raise SystemExit(main())
