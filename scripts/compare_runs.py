#!/usr/bin/env python3
"""
Compare two scorecards and fail if the newer one regressed.

Aggregate accuracy hides the thing that matters before a release: a change that
fixes three fields and breaks two looks like a net gain, but shipping it means two
fields that used to be right are now wrong. So the comparison is per field, per
period, and ANY correct -> not-correct transition is a regression regardless of the
totals.

A count of changed cells answers "did anything break". It does not answer "is this
better", because a corpus of 2,000 cells moves by a few cells on noise alone. So the
accuracy delta is reported with a bootstrap interval, resampled by FILING rather than
by cell: ten cells from one filing share a page selection, a scale reading and an FX
rate, and treating them as ten independent draws reports an interval about half as wide
as the truth.

Cost is gated too, on tokens and seconds per filing rather than dollars, because
`config/pricing.json` ships empty and a null cost must never read as a pass.

Exit codes: 0 = no regression, 1 = regression found. Suitable as a release gate.

Usage:
    python scripts/compare_runs.py output/scorecard_A.json output/scorecard_B.json
    python scripts/compare_runs.py baseline.json candidate.json --fail-on-new-abstention
    python scripts/compare_runs.py baseline.json candidate.json \
        --max-tokens-increase 0.10 --max-latency-increase 0.20
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from evalmetrics import bootstrap_delta   # noqa: E402

RANK = {"correct": 3, "missed": 2, "wrong": 1, "no_truth": 0, "both_absent": 0}


def load(path: Path) -> dict:
    """Both scorecard shapes.

    A schema-2 scorecard carries a flat `cells` list, which is the only form that
    survives a corpus run keyed "ARCI Q1 2022" rather than "Q1". Older scorecards are
    walked through `periods`, so a baseline recorded before the corpus existed still
    compares.
    """
    data = json.loads(Path(path).read_text())
    cells, flat = {}, data.get("cells")
    if flat:
        for cell in flat:
            cells[(cell.get("key"), cell.get("field"))] = cell
    else:
        for period, info in data.get("periods", {}).items():
            for field, row in (info.get("fields") or {}).items():
                cells[(period, field)] = row
    return {"meta": data, "cells": cells, "list": list(cells.values())}


def _cells_for_bootstrap(loaded: dict) -> list:
    """Cells in the shape evalmetrics expects: each carrying its own filing key."""
    return [{**row, "key": key, "field": field}
            for (key, field), row in loaded["cells"].items()]


def _budget(name: str, base_value, cand_value, allowed, unit="") -> tuple:
    """Compare one cost-ish number. Returns (line, failed).

    A metric missing from either run is reported and never failed on: absence is not
    evidence of improvement, and a gate that passes because a number was not recorded
    is worse than no gate.
    """
    if base_value in (None, 0) or cand_value is None:
        return (f"  {name:24} {'—':>12} (not recorded in both runs)", False)
    change = (cand_value - base_value) / base_value
    verdict = ""
    failed = False
    if allowed is not None and change > allowed:
        verdict = f"  ✗ over the {allowed:+.0%} budget"
        failed = True
    return (f"  {name:24} {base_value:>12,.1f} -> {cand_value:,.1f}{unit} "
            f"({change:+.1%}){verdict}", failed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--fail-on-new-abstention", action="store_true",
                    help="treat correct -> abstained as a regression too")
    ap.add_argument("--bootstrap", action=argparse.BooleanOptionalAction, default=True,
                    help="report the accuracy delta with a confidence interval")
    ap.add_argument("--bootstrap-iters", type=int, default=10000)
    ap.add_argument("--max-tokens-increase", type=float,
                    help="fail if input tokens per filing rise by more than this "
                         "fraction (e.g. 0.10)")
    ap.add_argument("--max-latency-increase", type=float,
                    help="fail if median seconds per filing rise by more than this")
    ap.add_argument("--min-abstention-precision", type=float,
                    help="fail if the share of withdrawals that were right falls below "
                         "this. A confidence layer decays by withholding good answers "
                         "long before accuracy notices.")
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

    budget_failures = []
    if args.bootstrap:
        for cluster in ("filing", "ticker"):
            result = bootstrap_delta(_cells_for_bootstrap(base), _cells_for_bootstrap(cand),
                                     iters=args.bootstrap_iters, cluster=cluster)
            if result["delta"] is None:
                print("\n  accuracy delta   — (no cells in common)")
                break
            label = ("filings" if cluster == "filing" else "issuers")
            print(f"\n  accuracy delta   {result['delta']*100:+.2f}pp   "
                  f"95% CI [{result['lo']*100:+.2f}, {result['hi']*100:+.2f}]   "
                  f"({result['n_clusters']} {label}, {result['n_cells']} cells, "
                  f"seed {result['seed']})")
            if cluster == "filing":
                # The two questions are different: clustering by filing asks whether the
                # change helped THESE filings, clustering by issuer asks whether it would
                # hold for a new one. The second interval is much wider, and honestly so.
                print("                   the wider line below answers 'would this hold "
                      "for an issuer not in the corpus?'")

    metrics_b = (base["meta"].get("metrics") or {})
    metrics_c = (cand["meta"].get("metrics") or {})
    cost_b = metrics_b.get("cost_latency") or {}
    cost_c = metrics_c.get("cost_latency") or {}
    if cost_b or cost_c:
        print("\ncost and latency")
        for name, base_value, cand_value, allowed, unit in (
            ("tokens in / filing", (cost_b.get("tokens_per_filing") or {}).get("input"),
             (cost_c.get("tokens_per_filing") or {}).get("input"),
             args.max_tokens_increase, ""),
            ("LLM calls / filing", cost_b.get("calls_per_filing"),
             cost_c.get("calls_per_filing"), args.max_tokens_increase, ""),
            ("seconds / filing (p50)", (cost_b.get("seconds_per_filing") or {}).get("p50"),
             (cost_c.get("seconds_per_filing") or {}).get("p50"),
             args.max_latency_increase, "s"),
        ):
            line, failed = _budget(name, base_value, cand_value, allowed, unit)
            print(line)
            if failed:
                budget_failures.append(name)

    agent_b = metrics_b.get("agent") or {}
    agent_c = metrics_c.get("agent") or {}
    if agent_b.get("filings") or agent_c.get("filings"):
        # Descriptive only. A release decision turns on accuracy, tokens, latency and
        # abstention precision; how many steps a loop took is context for those, not a
        # gate of its own.
        print("\nagent behaviour (not gated)")
        for label, path in (("steps / filing (p50)", ("steps_per_filing", "p50")),
                            ("tool-call error rate", ("tool_error_rate",)),
                            ("images / filing", ("images_per_filing", "mean")),
                            ("budget exhausted", ("budget_exhausted_rate",))):
            def reach(source):
                value = source
                for key in path:
                    value = (value or {}).get(key) if isinstance(value, dict) else None
                return value
            before, after = reach(agent_b), reach(agent_c)
            fmt = (lambda v: "—" if v is None else f"{v:,.2f}")
            print(f"  {label:24} {fmt(before):>12} -> {fmt(after)}")

    withdrawal_b = (metrics_b.get("abstention") or {}).get("precision")
    withdrawal_c = (metrics_c.get("abstention") or {}).get("precision")
    if withdrawal_b is not None or withdrawal_c is not None:
        print(f"\n  abstention precision   "
              f"{'—' if withdrawal_b is None else f'{withdrawal_b:.0%}'} -> "
              f"{'—' if withdrawal_c is None else f'{withdrawal_c:.0%}'}")
        if (args.min_abstention_precision is not None and withdrawal_c is not None
                and withdrawal_c < args.min_abstention_precision):
            print(f"  ✗ below the {args.min_abstention_precision:.0%} floor")
            budget_failures.append("abstention precision")

    if regressions:
        print(f"\n✗ {len(regressions)} regression(s) - do not ship")
        return 1
    if budget_failures:
        print(f"\n✗ within accuracy, but over budget on: {', '.join(budget_failures)}")
        return 1
    print("\n✓ no regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
