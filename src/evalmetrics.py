#!/usr/bin/env python3
"""
What the scored cells mean, once there are enough of them to mean anything.

Accuracy alone answers one question -- of the cells we scored, how many matched -- and
hides four that matter more:

  * **How much did it answer at all?** A system that withdraws half its fields can post a
    high accuracy and be useless. `coverage()` makes every labelled cell land in exactly
    one bucket, including the one today's `both_absent` quietly absorbs.
  * **Was withdrawing right?** `abstention()` asks what the withheld figure WOULD have
    scored. That is the only number that justifies a confidence layer, and it is the one
    that decays silently when a prompt changes.
  * **Does confidence mean anything?** `calibration()` compares stated confidence with
    observed accuracy, bucket by bucket.
  * **Where is it wrong?** `by_slice()` cuts by issuer, field, year, currency, scale,
    text-layer quality and answering model, each with its n, so a four-cell slice cannot
    be read as a result.

Everything here is pure arithmetic over cells and per-filing usage dicts: no model, no
network, no PDF. That is what lets the metrics be tested by hand and recomputed from a
committed scorecard.
"""

import random
from statistics import mean


def _get(cell, name, default=None):
    """Cells arrive either as evalkit.Cell objects or as dicts read back from JSON."""
    if isinstance(cell, dict):
        return cell.get(name, default)
    return getattr(cell, name, default)


def _labelled(cells):
    return [c for c in cells if _get(c, "status") in ("correct", "wrong", "missed")]


def coverage(cells) -> dict:
    """Where every cell went, with nothing absorbed silently.

    `both_absent` -- no label, and no answer -- is the bucket that hides things. An
    abstention on an unlabelled cell lands there and disappears from both the numerator
    and the denominator, so a system that withdrew a field nobody had labelled looked
    exactly like a system that was never asked. The two are separated here.
    """
    labelled = _labelled(cells)
    abstained_on_labelled = [c for c in labelled
                             if _get(c, "status") == "missed" and _get(c, "abstained")]
    unlabelled = [c for c in cells if _get(c, "status") in ("no_truth", "both_absent")]
    answered = [c for c in labelled if _get(c, "status") in ("correct", "wrong")]
    return {
        "cells": len(cells),
        "labelled": len(labelled),
        "answered": len(answered),
        "correct": sum(1 for c in labelled if _get(c, "status") == "correct"),
        "wrong": sum(1 for c in labelled if _get(c, "status") == "wrong"),
        "abstained_on_labelled": len(abstained_on_labelled),
        "missed_not_abstained": sum(1 for c in labelled
                                    if _get(c, "status") == "missed"
                                    and not _get(c, "abstained")),
        "unlabelled_answered": sum(1 for c in unlabelled
                                   if _get(c, "status") == "no_truth"),
        "unlabelled_abstained": sum(1 for c in unlabelled if _get(c, "abstained")),
        "unlabelled_silent": sum(1 for c in unlabelled
                                 if _get(c, "status") == "both_absent"
                                 and not _get(c, "abstained")),
        "answer_rate": (len(answered) / len(labelled)) if labelled else None,
    }


def accuracy(cells) -> dict:
    """Two accuracies, because they answer different questions.

    `accuracy` counts a withdrawal as a failure to answer -- what a user of the CSV
    experiences. `accuracy_on_answered` is the quality of what it does assert. A change
    that trades the first for the second is a real trade-off and must stay visible.
    """
    labelled = _labelled(cells)
    correct = sum(1 for c in labelled if _get(c, "status") == "correct")
    wrong = sum(1 for c in labelled if _get(c, "status") == "wrong")
    missed = sum(1 for c in labelled if _get(c, "status") == "missed")
    scored = correct + wrong + missed
    answered = correct + wrong
    return {
        "scored": scored, "correct": correct, "wrong": wrong, "missed": missed,
        "accuracy": (correct / scored) if scored else None,
        "accuracy_on_answered": (correct / answered) if answered else None,
    }


SLICES = {
    "ticker": lambda c: _get(c, "ticker") or "unknown",
    "field": lambda c: _get(c, "field") or "unknown",
    "year": lambda c: str(_get(c, "year") or "unknown"),
    "quarter": lambda c: _get(c, "quarter") or "unknown",
    "currency": lambda c: _get(c, "currency") or "unknown",
    "reporting_scale": lambda c: _get(c, "reporting_scale") or "unknown",
    "text_layer": lambda c: _get(c, "text_layer") or "unknown",
    "model": lambda c: _get(c, "model") or "unknown",
}


def by_slice(cells, key) -> dict:
    """{slice_value: accuracy + answer_rate + n}. Every row carries its n on purpose."""
    groups = {}
    for cell in cells:
        groups.setdefault(key(cell), []).append(cell)
    out = {}
    for name, group in sorted(groups.items()):
        numbers = accuracy(group)
        numbers["answer_rate"] = coverage(group)["answer_rate"]
        numbers["filings"] = len({_get(c, "key") for c in group})
        out[name] = numbers
    return out


def abstention(cells) -> dict:
    """Was withdrawing the right call?

    Only labelled cells count. A withdrawal whose withheld figure was never recorded --
    a prediction cached before `assess()` started keeping it -- is EXCLUDED rather than
    assumed either way, and counted in `unknown_withheld`, because assuming would turn
    an unknown into whichever number flatters the layer.

      caught       the withheld figure would NOT have matched the label -> a save
      thrown_away  the withheld figure WOULD have matched -> the cost of caution
      precision    caught / (caught + thrown_away)
      recall       caught / (caught + wrong)   -- of everything that would have been
                   wrong, how much did the layer actually catch
    """
    labelled = _labelled(cells)
    withdrawn = [c for c in labelled if _get(c, "abstained")]
    known = [c for c in withdrawn if _get(c, "would_have_been") in ("correct", "wrong")]
    caught = sum(1 for c in known if _get(c, "would_have_been") == "wrong")
    thrown_away = sum(1 for c in known if _get(c, "would_have_been") == "correct")
    silent_errors = sum(1 for c in labelled if _get(c, "status") == "wrong")
    return {
        "withdrawn": len(withdrawn),
        "withdrawn_known": len(known),
        "unknown_withheld": len(withdrawn) - len(known),
        "caught": caught,
        "thrown_away": thrown_away,
        "silent_errors": silent_errors,
        "precision": (caught / len(known)) if known else None,
        "recall": (caught / (caught + silent_errors)) if (caught + silent_errors) else None,
    }


# The first edge is the abstain threshold, so the table reads against the decision that
# threshold actually makes: everything in the first bucket was withheld by definition.
CALIBRATION_EDGES = (0.0, 0.55, 0.65, 0.75, 0.85, 0.95, 1.0001)


def calibration(cells, edges=CALIBRATION_EDGES) -> dict:
    """Stated confidence against observed accuracy, on the cells that were answered.

    A layer that says 0.9 should be right about nine times in ten. `gap` is the signed
    difference (accuracy - mean confidence): negative means overconfident. `ece` is the
    n-weighted mean absolute gap -- one number for "can these confidences be believed".
    """
    answered = [c for c in _labelled(cells)
                if _get(c, "status") in ("correct", "wrong")
                and _get(c, "confidence") is not None]
    buckets = []
    total = len(answered)
    error = 0.0
    for low, high in zip(edges, edges[1:]):
        group = [c for c in answered if low <= _get(c, "confidence") < high]
        if not group:
            buckets.append({"range": [low, min(high, 1.0)], "n": 0,
                            "mean_confidence": None, "accuracy": None, "gap": None})
            continue
        observed = sum(1 for c in group if _get(c, "status") == "correct") / len(group)
        stated = mean(_get(c, "confidence") for c in group)
        buckets.append({"range": [low, min(high, 1.0)], "n": len(group),
                        "mean_confidence": stated, "accuracy": observed,
                        "gap": observed - stated})
        error += len(group) * abs(observed - stated)
    return {"buckets": buckets, "n": total, "ece": (error / total) if total else None}


def failure_taxonomy(cells) -> dict:
    kinds = {}
    for cell in cells:
        kind = _get(cell, "failure_kind")
        if kind:
            kinds[kind] = kinds.get(kind, 0) + 1
    return dict(sorted(kinds.items(), key=lambda kv: -kv[1]))


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def cost_latency(filings) -> dict:
    """Run-level cost and latency, from the per-filing usage dicts.

    `filings` is a list of {"elapsed_s": float|None, "usage": Usage.to_dict()|None}.
    Cost stays None unless every filing was priced: a partial sum reads as a total and
    understates the run. `src/usage.py` carries the reason, and the report prints it
    rather than printing zero.
    """
    used = [f for f in filings if f.get("usage")]
    if not used:
        return {"documents": 0}
    usages = [f["usage"] for f in used]
    tokens_in = [u.get("tokens", {}).get("input") for u in usages]
    tokens_out = [u.get("tokens", {}).get("output") for u in usages]
    tokens_in = [t for t in tokens_in if t is not None]
    tokens_out = [t for t in tokens_out if t is not None]
    priced = [u.get("cost", {}).get("amount") for u in usages]
    priced_known = [p for p in priced if p is not None]
    seconds = [f["elapsed_s"] for f in filings if f.get("elapsed_s") is not None]

    stages = {}
    for usage in usages:
        for stage, milliseconds in (usage.get("latency_ms") or {}).items():
            stages.setdefault(stage, []).append(milliseconds)

    documents = len(used)
    return {
        "documents": documents,
        "llm_calls": sum(u.get("llm_calls", 0) for u in usages),
        "tokens": {"input": sum(tokens_in) if tokens_in else None,
                   "output": sum(tokens_out) if tokens_out else None},
        "tokens_per_filing": {
            "input": (sum(tokens_in) / len(tokens_in)) if tokens_in else None,
            "output": (sum(tokens_out) / len(tokens_out)) if tokens_out else None},
        "calls_per_filing": sum(u.get("llm_calls", 0) for u in usages) / documents,
        "cost": {
            "amount": round(sum(priced_known), 6) if len(priced_known) == documents else None,
            "currency": usages[0].get("cost", {}).get("currency", "USD"),
            "reason": None if len(priced_known) == documents
                      else usages[0].get("cost", {}).get("reason"),
        },
        "seconds_per_filing": {
            "min": min(seconds) if seconds else None,
            "p50": _percentile(seconds, 0.50),
            "mean": (sum(seconds) / len(seconds)) if seconds else None,
            "p95": _percentile(seconds, 0.95),
            "max": max(seconds) if seconds else None,
        },
        "stage_ms": {name: {"total": sum(values), "mean": sum(values) / len(values)}
                     for name, values in sorted(stages.items())},
    }


def worst_cells(cells, limit: int = 25) -> list:
    """The wrong answers worth reading first.

    Sorted by relative error, ties broken by confidence descending: a confidently wrong
    figure is a worse defect than a hesitant one, because nothing downstream will doubt it.
    """
    wrong = [c for c in cells if _get(c, "status") == "wrong"]
    wrong.sort(key=lambda c: (-(_get(c, "rel_error") or 0), -(_get(c, "confidence") or 0)))
    return wrong[:limit]


def _correct_by_cell(cells) -> dict:
    """{(filing key, field): 1/0} over labelled cells only."""
    return {(_get(c, "key"), _get(c, "field")): 1 if _get(c, "status") == "correct" else 0
            for c in _labelled(cells)}


def bootstrap_delta(base_cells, candidate_cells, iters: int = 10000, seed: int = 0,
                    cluster: str = "filing") -> dict:
    """Is the accuracy difference between two runs bigger than the noise?

    Paired over the cells both runs scored, and resampled by CLUSTER rather than by
    cell. Ten cells from one filing share a page selection, a scale reading and an FX
    rate; treating them as ten independent draws reports an interval roughly half as
    wide as the truth and turns noise into a finding.

      cluster="filing"  the default -- the unit an extraction succeeds or fails as
      cluster="ticker"  the stricter question: does this hold for a NEW issuer? With
                        fourteen issuers the interval is much wider, and honestly so.
    """
    base = _correct_by_cell(base_cells)
    candidate = _correct_by_cell(candidate_cells)
    shared = sorted(set(base) & set(candidate))
    if not shared:
        return {"delta": None, "lo": None, "hi": None, "n_cells": 0, "n_clusters": 0,
                "iters": iters, "seed": seed, "cluster": cluster,
                "p_improvement": None}

    def cluster_of(key):
        filing = key[0] or ""
        return filing.split(" ")[0] if cluster == "ticker" else filing

    groups = {}
    for key in shared:
        groups.setdefault(cluster_of(key), []).append(key)
    names = sorted(groups)

    def delta_over(chosen):
        pairs = [k for name in chosen for k in groups[name]]
        if not pairs:
            return 0.0
        return (sum(candidate[k] for k in pairs) - sum(base[k] for k in pairs)) / len(pairs)

    observed = delta_over(names)
    rng = random.Random(seed)
    samples = sorted(delta_over([rng.choice(names) for _ in names]) for _ in range(iters))
    lo = samples[int(0.025 * (len(samples) - 1))]
    hi = samples[int(0.975 * (len(samples) - 1))]
    better = sum(1 for s in samples if s > 0) / len(samples)
    return {"delta": observed, "lo": lo, "hi": hi, "n_cells": len(shared),
            "n_clusters": len(names), "iters": iters, "seed": seed,
            "cluster": cluster, "p_improvement": better}


def _spread(values) -> dict:
    values = [v for v in values if v is not None]
    if not values:
        return {"mean": None, "p50": None, "p95": None, "max": None}
    return {"mean": sum(values) / len(values), "p50": _percentile(values, 0.50),
            "p95": _percentile(values, 0.95), "max": max(values)}


def agent_behaviour(trajectories) -> dict:
    """What the loop actually did -- not whether it was right.

    A trajectory that is None is a filing the agent did not run (a pipeline row, or a
    prediction cached before the agent existed). Those are SKIPPED rather than counted
    as zero: a filing that recorded no trajectory is unmeasured, not efficient. Same
    discipline as cost_latency refusing to report a cost unless every filing was priced.
    """
    runs = [t for t in (trajectories or []) if t]
    if not runs:
        return {"filings": 0}

    steps = [t.get("steps_used", 0) for t in runs]
    errors = [e for t in runs for e in (t.get("tool_errors") or [])]
    calls = sum(len(t.get("steps") or []) for t in runs)
    counts, kinds, stops = {}, {}, {}
    for t in runs:
        for name, n in (t.get("tool_counts") or {}).items():
            counts[name] = counts.get(name, 0) + n
        stops[t.get("stop_reason", "unknown")] = stops.get(t.get("stop_reason", "unknown"), 0) + 1
    for error in errors:
        kind = error.get("kind", "unknown")
        kinds[kind] = kinds.get(kind, 0) + 1

    return {
        "filings": len(runs),
        "steps_per_filing": _spread(steps),
        "tool_calls": calls,
        "tool_calls_per_filing": _spread([len(t.get("steps") or []) for t in runs]),
        "tool_errors": len(errors),
        "tool_error_rate": (len(errors) / calls) if calls else None,
        "tool_errors_by_kind": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "tool_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "text_pages_per_filing": _spread([len(t.get("pages_opened_text") or []) for t in runs]),
        "images_per_filing": _spread([len(t.get("pages_rendered_image") or []) for t in runs]),
        "groups_reported_per_filing": sum(len(t.get("groups_reported") or [])
                                          for t in runs) / len(runs),
        "budget_exhausted_rate": sum(1 for t in runs if t.get("budget_exhausted")) / len(runs),
        "stop_reasons": dict(sorted(stops.items(), key=lambda kv: -kv[1])),
        "handovers_per_filing": sum(len(t.get("handovers") or []) for t in runs) / len(runs),
        "no_tool_call_rate": sum(t.get("no_tool_call_turns", 0) for t in runs) / max(1, calls),
    }


def page_selection_agreement(trajectories) -> dict:
    """How the agent's page choices differ from the deterministic selector's.

    NOT a correctness metric, and the wording matters. The selector is the thing being
    contested -- it needed four hand-written patches to reach its current state -- so it
    is a reference, not ground truth. Whether the agent chose BETTER is answered by the
    accuracy of the cells. This answers the different question of HOW it chose
    differently, which is what distinguishes an agent that found something from one that
    rediscovered the selector at three times the cost.

    `deterministic_pages` is backfilled offline by scripts/page_agreement.py; filings
    without it are excluded.
    """
    runs = [t for t in (trajectories or []) if t and t.get("deterministic_pages")]
    if not runs:
        return {"filings": 0}

    precisions, recalls, jaccards, agent_sizes, ref_sizes = [], [], [], [], []
    extra, missing = [], []
    for t in runs:
        chosen = {p for pages in (t.get("pages_reported") or {}).values() for p in pages}
        reference = set(t.get("deterministic_pages") or [])
        shared = chosen & reference
        agent_sizes.append(len(chosen))
        ref_sizes.append(len(reference))
        if chosen:
            precisions.append(len(shared) / len(chosen))
        if reference:
            recalls.append(len(shared) / len(reference))
        union = chosen | reference
        if union:
            jaccards.append(len(shared) / len(union))
        if chosen - reference:
            extra.append({"key": t.get("key"), "pages": sorted(chosen - reference)})
        if reference - chosen:
            missing.append({"key": t.get("key"), "pages": sorted(reference - chosen)})

    return {
        "filings": len(runs),
        "precision": (sum(precisions) / len(precisions)) if precisions else None,
        "recall": (sum(recalls) / len(recalls)) if recalls else None,
        "jaccard": (sum(jaccards) / len(jaccards)) if jaccards else None,
        "mean_pages_agent": sum(agent_sizes) / len(agent_sizes),
        "mean_pages_selector": sum(ref_sizes) / len(ref_sizes),
        "pages_only_the_agent_chose": extra[:20],
        "pages_only_the_selector_chose": missing[:20],
    }


def summarise(cells, filings, trajectories=None) -> dict:
    """Every metric, in the shape the scorecard stores under "metrics".

    `trajectories` defaults to None so every existing call site, every committed
    scorecard and every pipeline run behaves exactly as before: no "agent" key appears
    unless a loop actually ran.
    """
    summary = {
        "coverage": coverage(cells),
        "accuracy": accuracy(cells),
        "abstention": abstention(cells),
        "calibration": calibration(cells),
        "failure_kinds": failure_taxonomy(cells),
        "cost_latency": cost_latency(filings),
        "slices": {name: by_slice(cells, key) for name, key in SLICES.items()},
    }
    if any(trajectories or []):
        summary["agent"] = agent_behaviour(trajectories)
        agreement = page_selection_agreement(trajectories)
        if agreement.get("filings"):
            summary["page_agreement"] = agreement
    return summary
