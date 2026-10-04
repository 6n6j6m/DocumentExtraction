#!/usr/bin/env python3
"""
Promote a scorecard to the baseline everything else is measured against.

The baseline is the one artifact in this repo that must never move by accident. It is
what CI compares each change to, so a baseline promoted from an unreproducible run turns
the gate into a comparison with a number nobody can recreate.

Two rules follow, and both are enforced here rather than written down and hoped for:

  * the run must name a commit, and the tree must have been clean when it ran;
  * promotion is a deliberate human act, with a reason, recorded in a changelog.

It lives in `evals/baselines/` and not in `output/`, because `output/` is what every run
overwrites.

Usage:
    python scripts/promote_baseline.py output/corpus_scorecard_<tag>.json \\
        --reason "first full-corpus pass after the shareholder-table rewrite"
"""

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINES = ROOT / "evals" / "baselines"
CHANGELOG = BASELINES / "CHANGELOG.md"


def main() -> int:
    ap = argparse.ArgumentParser(description="Make a scorecard the baseline.")
    ap.add_argument("scorecard")
    ap.add_argument("--reason", required=True,
                    help="why this run should become the thing everything is compared to")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="promote a run made with uncommitted changes anyway. Use only "
                         "to bootstrap the very first baseline.")
    args = ap.parse_args()

    path = Path(args.scorecard)
    if not path.exists():
        print(f"no scorecard at {path}")
        return 2
    scorecard = json.loads(path.read_text())
    run = scorecard.get("run") or {}
    provider = scorecard.get("provider")
    if not provider:
        print("this scorecard does not name a provider; it cannot be filed")
        return 2

    if not run.get("git_commit") or run.get("git_dirty"):
        state = ("no commit recorded" if not run.get("git_commit")
                 else f"commit {run['git_commit']} with uncommitted changes")
        if not args.allow_dirty:
            print(f"refusing: this run was made from {state}, so it cannot be reproduced "
                  f"from the repository.\n"
                  f"  commit the tree, re-run the eval, and promote that. "
                  f"(--allow-dirty to bootstrap the first baseline anyway)")
            return 2
        print(f"⚠ promoting a run made from {state}, because --allow-dirty was passed")

    metrics = scorecard.get("metrics") or {}
    accuracy = (metrics.get("accuracy") or {})
    target = BASELINES / provider / ("corpus_scorecard.json" if scorecard.get("corpus")
                                     else f"scorecard_{scorecard.get('ticker')}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(target.read_text()) if target.exists() else None
    shutil.copyfile(path, target)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    accuracy_text = ("—" if accuracy.get("accuracy") is None
                     else f"{accuracy['accuracy']:.1%} ({accuracy['correct']}/{accuracy['scored']})")
    previous_text = ""
    if previous:
        before = ((previous.get("metrics") or {}).get("accuracy") or {}).get("accuracy")
        previous_text = f", was {before:.1%}" if before is not None else ", replacing an earlier run"

    if not CHANGELOG.exists():
        CHANGELOG.write_text(
            "# Baseline changelog\n\n"
            "Every promotion, with the reason a person gave for it. A baseline that moves\n"
            "without an entry here is a gate that was quietly lowered.\n\n"
            "| date | provider | commit | prompt | accuracy | reason |\n"
            "|---|---|---|---|---|---|\n")
    with CHANGELOG.open("a") as log:
        log.write(f"| {stamp} | {provider} | `{run.get('git_commit', '—')}` | "
                  f"`{run.get('prompt_sha256', '—')}` | {accuracy_text}{previous_text} | "
                  f"{args.reason} |\n")

    print(f"baseline: {target.relative_to(ROOT)}")
    print(f"accuracy: {accuracy_text}")
    print(f"logged in {CHANGELOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
