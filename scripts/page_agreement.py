#!/usr/bin/env python3
"""
Backfill, into each agent prediction, the pages the deterministic selector would have
chosen — so the two page choices can be compared afterwards.

This is a separate script, run after a pass, for one reason: computing it inside the
agent would charge the agent for the baseline's work. Page selection is a third of the
pipeline's wall clock on a clean filing and minutes on one that must be OCR'd, and
latency is the headline the experiment turns on. Running it here, offline, keeps the
agent's measured cost the agent's own.

It calls no model and needs no key. It does read the filings, but page selection's OCR
is disk-cached and the pipeline has usually populated that cache already.

Usage:
    python scripts/page_agreement.py output/predictions/<agent_tag>
    python scripts/page_agreement.py output/predictions/<agent_tag> --corpus-root ~/FinancialReport
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from evalkit import discover_corpus                      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Record what the deterministic selector would have chosen.")
    ap.add_argument("predictions", help="a directory of cached predictions")
    ap.add_argument("--corpus-root", nargs="+",
                    help="where the filings live (default: data/raw, plus $EVAL_CORPUS_ROOT)")
    ap.add_argument("--force", action="store_true",
                    help="recompute even where it is already recorded")
    args = ap.parse_args()

    directory = Path(args.predictions)
    if not directory.is_dir():
        print(f"no such directory: {directory}")
        return 2

    roots = [Path(r).expanduser() for r in args.corpus_root] if args.corpus_root else (
        [ROOT / "data" / "raw"]
        + [Path(r).expanduser()
           for r in os.getenv("EVAL_CORPUS_ROOT", "").split(os.pathsep) if r.strip()])
    corpus = discover_corpus(roots)

    from page_select import select_statement_pages

    written = skipped = missing = 0
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text())
        trajectory = payload.get("_agent")
        if not trajectory:
            skipped += 1                       # a pipeline prediction; nothing to compare
            continue
        if trajectory.get("deterministic_pages") and not args.force:
            skipped += 1
            continue

        # The cache stem is <TICKER>_<Q>_<YEAR>; the filing it came from is
        # <Q>_<YEAR>_<TICKER>.pdf, so the same three parts in a different order.
        parts = path.stem.split("_")
        if len(parts) < 3 or not parts[2].isdigit():
            print(f"  ? {path.name}: not a <TICKER>_<Q>_<YEAR> prediction")
            missing += 1
            continue
        ticker, quarter, year = parts[0], parts[1], parts[2]

        pdf = (corpus.get(ticker.upper()) or {}).get((quarter.upper(), int(year)))
        if pdf is None:
            print(f"  ? {path.name}: no filing found for {ticker} {quarter} {year}")
            missing += 1
            continue

        started = time.time()
        selection = select_statement_pages(str(pdf))
        trajectory["deterministic_pages"] = [p + 1 for p in selection.pages]
        trajectory["deterministic_method"] = selection.method
        payload["_agent"] = trajectory
        path.write_text(json.dumps(payload, indent=2, default=str))
        written += 1
        print(f"  ✓ {path.name}: selector chose {len(selection.pages)} page(s) "
              f"({selection.method}) in {time.time() - started:.0f}s")

    print(f"\n{written} updated, {skipped} skipped, {missing} without a filing")
    print("re-score with --cached-only to fold these into the report")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
