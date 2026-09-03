#!/usr/bin/env python3
"""
Compare two scorecards and fail if the newer one regressed.

Aggregate accuracy hides the thing that matters before a release: a change that
fixes three fields and breaks two looks like a net gain, but shipping it means two
fields that used to be right are now wrong. So the comparison is per field, per
period, and ANY correct -> not-correct transition is a regression regardless of the
totals.

Exit codes: 0 = no regression, 1 = regression found. Suitable as a release gate.

Usage:
    python scripts/compare_runs.py output/scorecard_A.json output/scorecard_B.json
    python scripts/compare_runs.py baseline.json candidate.json --fail-on-new-abstention
"""

import argparse
import json
from pathlib import Path

RANK = {"correct": 3, "missed": 2, "wrong": 1, "no_truth": 0, "both_absent": 0}


def load(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    cells = {}
    for period, info in data.get("periods", {}).items():
        for field, row in (info.get("fields") or {}).items():
            cells[(period, field)] = row
    return {"meta": data, "cells": cells}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--fail-on-new-abstention", action="store_true",
                    help="treat correct -> abstained as a regression too")
    args = ap.parse_args()

    base, cand = load(args.baseline), load(args.candidate)
    print(f"baseline  {Path(args.baseline).name}  ({base['meta'].get('provider')})")
    print(f"candidate {Path(args.candidate).name}  ({cand['meta'].get('provider')})\n")

    # Before comparing scores, establish whether the two runs are comparable at all.
    # A score that moved because the prompt was edited is not a regression in the
    # extractor, and reporting it as one sends the reader hunting in the wrong file.
    br, cr = base["meta"].get("run", {}), cand["meta"].get("run", {})
    if br or cr:
        if br.get("prompt_sha256") != cr.get("prompt_sha256"):
            print(f"⚠ prompts differ: {br.get('prompt_sha256')} -> {cr.get('prompt_sha256')}")
        if br.get("git_commit") != cr.get("git_commit"):
            print(f"⚠ code differs: {br.get('git_commit')} -> {cr.get('git_commit')}")
        if br.get("git_dirty") or cr.get("git_dirty"):
            print("⚠ at least one run was made with uncommitted changes; "
                  "it cannot be reproduced from the repository")
        if br.get("tolerance") != cr.get("tolerance"):
            print(f"⚠ tolerance differs: {br.get('tolerance')} -> {cr.get('tolerance')} "
                  f"- statuses are not comparable")
        changed = {k: (br.get("config", {}).get(k), cr.get("config", {}).get(k))
                   for k in set(br.get("config", {})) | set(cr.get("config", {}))
                   if br.get("config", {}).get(k) != cr.get("config", {}).get(k)}
        for k, (a, b) in sorted(changed.items()):
            print(f"⚠ {k}: {a} -> {b}")
        if changed or br.get("prompt_sha256") != cr.get("prompt_sha256"):
            print()
    else:
        print("⚠ no run metadata; these scorecards predate provenance tracking\n")

    only_base = set(base["cells"]) - set(cand["cells"])
    only_cand = set(cand["cells"]) - set(base["cells"])
    if only_base or only_cand:
        # Comparing different field or period sets makes the totals incomparable;
        # say so rather than quietly averaging over a different denominator.
        print(f"⚠ coverage differs: {len(only_base)} cell(s) only in baseline, "
              f"{len(only_cand)} only in candidate\n")

    regressions, improvements, kind_changes = [], [], []
    for key in sorted(set(base["cells"]) & set(cand["cells"])):
        b, c = base["cells"][key], cand["cells"][key]
        bs, cs = b["status"], c["status"]
        if bs == cs:
            if bs == "wrong" and b.get("failure_kind") != c.get("failure_kind"):
                kind_changes.append((key, b.get("failure_kind"), c.get("failure_kind")))
            continue
        entry = (key, bs, cs)
        if RANK[cs] < RANK[bs]:
            if bs == "correct" and cs == "missed" and not args.fail_on_new_abstention:
                # Abstaining where it used to be right is a real loss of coverage,
                # but it is not a wrong answer shipped to a user. Reported either
                # way; only gates the build when asked.
                improvements.append((key, bs, cs, "abstained (coverage loss)"))
                continue
            regressions.append(entry)
        else:
            improvements.append(entry + ("",))

    width = 34
    if regressions:
        print("REGRESSIONS")
        for (period, field), bs, cs in regressions:
            print(f"  {period} {field:{width}} {bs} -> {cs}")
    if improvements:
        print("\nchanges in the other direction")
        for item in improvements:
            (period, field), bs, cs = item[0], item[1], item[2]
            note = item[3] if len(item) > 3 else ""
            print(f"  {period} {field:{width}} {bs} -> {cs} {note}")
    if kind_changes:
        print("\nstill wrong, but failing differently")
        for (period, field), old, new in kind_changes:
            print(f"  {period} {field:{width}} {old} -> {new}")

    bt = base["meta"].get("summary", {})
    ct = cand["meta"].get("summary", {})
    print(f"\n{'':12}{'baseline':>10}{'candidate':>11}{'delta':>8}")
    for key in ("correct", "wrong", "missed"):
        b, c = bt.get(key, 0), ct.get(key, 0)
        print(f"  {key:10}{b:>10}{c:>11}{c-b:>+8}")

    if regressions:
        print(f"\n✗ {len(regressions)} regression(s) - do not ship")
        return 1
    print("\n✓ no regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
