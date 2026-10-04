#!/usr/bin/env python3
"""
Score the label auditor, rather than believe it.

Two answer keys, neither of which the auditor has seen:

  HEAD        the committed workbooks still carry label errors that were later found by
              hand and fixed in the working tree -- GTRA's two-column shift, GTRA `J8`
              counted twice, JPFA's stale share count. Every cell that differs between
              HEAD and the working tree is a known label error, with a known cause.

  injected    a copy of the working-tree labels with errors of known kinds planted in
              known cells: a neighbouring period's value, x1000, x2, two columns
              swapped, a share count from another period.

The blind reading is independent of the labels, so both keys are scored from the SAME
cached reading at no token cost. `--adjudicate` additionally runs phase two on the
disagreements each key produces, which costs tokens and is cached per (field, label).

Pre-registered: the auditor is not useful if recall on the HEAD key is below 80%, if it
raises alarms on more than 5% of untouched cells, if it cannot judge more than 20% of
labelled cells, or if it does not name GTRA's errors a period shift.

    python scripts/audit_benchmark.py --tickers GTRA JPFA ADMR PTBA
    python scripts/audit_benchmark.py --tickers GTRA JPFA --adjudicate
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import audit_labels as al                                            # noqa: E402
from labelaudit import (AUDIT_FIELDS, INJECTION_KINDS, adjudication_key,  # noqa: E402
                        cell_status, diff_columns, final_status, inject_errors)

# The cause each known HEAD error should be given. From CORRECTIONS.md.
EXPECTED_HEAD_CAUSE = {"GTRA": "period_shift", "JPFA": "stale_value"}
EXPECTED_HEAD_OVERRIDES = {("GTRA", "Q2", 2024, "utang_bank"): "double_count"}
ACCEPTABLE_INJECTED_CAUSE = {
    "previous_period": {"comparative_column", "period_shift", "stale_value"},
    "times_1000": {"scale"},
    "times_2": {"double_count"},
    "swap_columns": {"period_shift", "comparative_column"},
    "share_from_other_period": {"stale_value", "period_shift"},
}
THRESHOLDS = {"recall_head": 0.80, "false_alarm": 0.05, "unjudgeable": 0.20}


def statuses(filings, columns_by_ticker, out_dir):
    """{(ticker, quarter, year, field): (phase-one status, final status, verdict)}."""
    from auditagent import evidence_from_record
    out = {}
    for filing in filings:
        record = al.load_record(out_dir, filing)
        if not record or "read" not in record:
            continue
        evidence = evidence_from_record(record["read"])
        columns = columns_by_ticker.get(filing.ticker, {})
        for name in AUDIT_FIELDS:
            label = columns.get(filing.period, {}).get(name)
            if label is None:
                continue
            first = cell_status(label, evidence.get(name))
            final, verdict = final_status(label, evidence.get(name),
                                          record.get("adjudications"))
            out[(filing.ticker, filing.quarter, filing.year, name)] = (first, final, verdict)
    return out


def score(key: dict, observed: dict, expected_cause) -> dict:
    """Recall on planted/known cells, alarms on the rest, and cause accuracy."""
    planted = [k for k in key if k in observed]
    untouched = [k for k in observed if k not in key]
    flagged = [k for k in planted if observed[k][0] == "disputed"]
    judged_wrong = [k for k in planted if observed[k][1] == "label_wrong"]
    adjudicated = [k for k in planted if observed[k][1] not in ("unadjudicated",)
                   and observed[k][0] == "disputed"]
    alarms = [k for k in untouched if observed[k][0] == "disputed"]
    alarms_final = [k for k in untouched if observed[k][1] == "label_wrong"]
    cause_hits = [k for k in judged_wrong
                  if (observed[k][2] or {}).get("cause") in expected_cause(k)]
    unjudgeable = [k for k in observed if observed[k][0] in ("unverifiable", "not_found")]
    return {
        "planted_auditable": len(planted),
        "recall_flagged": len(flagged) / len(planted) if planted else None,
        "recall_confirmed": (len(judged_wrong) / len(planted)
                             if planted and adjudicated else None),
        "adjudicated": len(adjudicated),
        "cause_accuracy": len(cause_hits) / len(judged_wrong) if judged_wrong else None,
        "untouched": len(untouched),
        "alarm_rate": len(alarms) / len(untouched) if untouched else None,
        "alarm_rate_after_adjudication": (len(alarms_final) / len(untouched)
                                          if untouched else None),
        "unjudgeable_rate": len(unjudgeable) / len(observed) if observed else None,
        "missed": [" ".join(map(str, k)) + f" -> {observed[k][0]}"
                   for k in planted if k not in flagged][:30],
        "alarms": [" ".join(map(str, k)) for k in alarms][:30],
    }


def by_kind(key, observed):
    out = {}
    for kind in INJECTION_KINDS:
        cells = {k: v for k, v in key.items() if v == kind}
        planted = [k for k in cells if k in observed]
        flagged = [k for k in planted if observed[k][0] == "disputed"]
        out[kind] = {"planted": len(planted),
                     "recall_flagged": len(flagged) / len(planted) if planted else None}
    return out


def adjudicate(filings, corpus, columns_by_ticker, predictions, out_dir):
    labels = {t: (c, {}, None) for t, c in columns_by_ticker.items()}
    return al.phase_adjudicate(filings, corpus, labels, predictions, out_dir)


def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="+", required=True)
    ap.add_argument("--corpus-root", nargs="+", default=al.DEFAULT_ROOTS)
    ap.add_argument("--revision", default="HEAD")
    ap.add_argument("--per-kind", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--adjudicate", action="store_true",
                    help="run phase two on the disagreements (costs tokens)")
    ap.add_argument("--out", default=str(ROOT / "output" / "label_audit"))
    args = ap.parse_args()

    out_dir = Path(args.out) / al.auditor_tag()
    scratch = Path(args.out) / "_revisions"
    corpus = al.discover_corpus(args.corpus_root, args.tickers)
    tickers = sorted(corpus)
    head = al.load_labels(tickers, args.revision, scratch)
    work = al.load_labels(tickers, "worktree", scratch)
    filings = [al.Filing(t, q, y, pdf) for t in tickers for (q, y), pdf in corpus[t].items()]
    read = [f for f in filings if (al.load_record(out_dir, f) or {}).get("read")]
    print(f"{len(read)}/{len(filings)} filing(s) have a cached reading "
          f"({al.auditor_tag()})")
    if not read:
        print("Nothing to score yet: run scripts/audit_labels.py --tickers ... first.")
        return 1

    # --- key 1: what HEAD got wrong and the working tree fixed -------------------------
    head_cols = {t: head[t][0] for t in head}
    key_head = {}
    for t in tickers:
        for (q, y, f), _ in diff_columns(head_cols.get(t, {}), work.get(t, ({},))[0]).items():
            key_head[(t, q, y, f)] = EXPECTED_HEAD_OVERRIDES.get(
                (t, q, y, f), EXPECTED_HEAD_CAUSE.get(t, "other"))

    # --- key 2: planted in a copy of the working tree ----------------------------------
    injected_cols, key_injected = {}, {}
    for i, t in enumerate(tickers):
        corrupted, key = inject_errors(work[t][0], per_kind=args.per_kind,
                                       seed=args.seed + i)
        injected_cols[t] = corrupted
        key_injected.update({(t,) + k: v for k, v in key.items()})

    predictions = al.load_predictions(al.DEFAULT_PREDICTIONS, read)
    if args.adjudicate:
        adjudicate(read, corpus, head_cols, predictions, out_dir)
        adjudicate(read, corpus, injected_cols, predictions, out_dir)

    obs_head = statuses(read, head_cols, out_dir)
    obs_injected = statuses(read, injected_cols, out_dir)
    result_head = score(key_head, obs_head, lambda k: {key_head[k]})
    result_inj = score(key_injected, obs_injected,
                       lambda k: ACCEPTABLE_INJECTED_CAUSE[key_injected[k]])
    result_inj["by_kind"] = by_kind(key_injected, obs_injected)

    gtra = [k for k in key_head if k[0] == "GTRA" and k in obs_head
            and obs_head[k][1] == "label_wrong"]
    gtra_shift = [k for k in gtra if (obs_head[k][2] or {}).get("cause") == "period_shift"]
    verdicts = {
        "recall_head": (result_head["recall_flagged"], THRESHOLDS["recall_head"], ">="),
        "false_alarm": (result_inj["alarm_rate_after_adjudication"]
                        if args.adjudicate else result_inj["alarm_rate"],
                        THRESHOLDS["false_alarm"], "<="),
        "unjudgeable": (result_head["unjudgeable_rate"], THRESHOLDS["unjudgeable"], "<="),
    }
    lines = [f"# Label auditor benchmark — {al.auditor_tag()}", "",
             f"{len(read)} filings with a cached reading, of {len(filings)} "
             f"for {', '.join(tickers)}.", "",
             "## Pre-registered checks", "", "| check | value | threshold | |",
             "|---|---:|---:|---|"]
    for name, (value, bound, op) in verdicts.items():
        ok = None if value is None else (value >= bound if op == ">=" else value <= bound)
        lines.append(f"| {name} | {_pct(value)} | {op} {_pct(bound)} | "
                     f"{'—' if ok is None else ('PASS' if ok else 'FAIL')} |")
    lines.append(f"| GTRA named period_shift | {len(gtra_shift)}/{len(gtra)} confirmed "
                 f"errors | majority | "
                 f"{'—' if not gtra else ('PASS' if len(gtra_shift) * 2 > len(gtra) else 'FAIL')} |")
    for title, r in (("Known errors (HEAD vs working tree)", result_head),
                     ("Injected errors", result_inj)):
        lines += ["", f"## {title}", "",
                  f"- auditable planted cells: {r['planted_auditable']}",
                  f"- recall, flagged by the blind reading: **{_pct(r['recall_flagged'])}**",
                  f"- recall, confirmed as label_wrong after adjudication: "
                  f"{_pct(r['recall_confirmed'])} ({r['adjudicated']} adjudicated)",
                  f"- cause named correctly: {_pct(r['cause_accuracy'])}",
                  f"- alarms on {r['untouched']} untouched cells: {_pct(r['alarm_rate'])} "
                  f"flagged, {_pct(r['alarm_rate_after_adjudication'])} after adjudication "
                  f"— an alarm here is a false alarm OR a real label error nobody has "
                  f"found yet; check it in the audit report before counting it against "
                  f"the auditor",
                  f"- cells the auditor could not judge: {_pct(r['unjudgeable_rate'])}"]
        if r.get("by_kind"):
            lines += ["", "| kind | planted | recall (flagged) |", "|---|---:|---:|"]
            lines += [f"| {k} | {v['planted']} | {_pct(v['recall_flagged'])} |"
                      for k, v in r["by_kind"].items()]
        if r["missed"]:
            lines += ["", "Missed:", ""] + [f"- {m}" for m in r["missed"]]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark.md").write_text("\n".join(lines) + "\n")
    (out_dir / "benchmark.json").write_text(json.dumps(
        {"head": result_head, "injected": result_inj,
         "verdicts": {k: list(v) for k, v in verdicts.items()},
         "gtra_period_shift": [len(gtra_shift), len(gtra)]}, indent=1, default=str))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
