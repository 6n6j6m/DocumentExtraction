#!/usr/bin/env python3
"""
Audit the ground truth: read every filing again, independently, and say which labels the
filings do not support.

    # free: the deterministic screen, no model
    python scripts/audit_labels.py --corpus --phase screen

    # a pilot on named filings, then an estimate for the rest
    python scripts/audit_labels.py --filings GTRA_Q2_2024 JPFA_Q3_2023 ARCI_Q1_2022
    python scripts/audit_labels.py --corpus --estimate

    # the whole corpus; re-run the same command after a daily quota runs out
    python scripts/audit_labels.py --corpus

Phases (default: all of them, in order):

  screen      free checks over every labelled cell; sets the order filings are read in
  read        the blind reading, one conversation per filing, cached and resumable
  adjudicate  a second conversation for cells where a verified reading disagrees
  report      audit_report.md / .json and PROPOSED_CORRECTIONS.md

Nothing here writes a workbook. `--labels HEAD` audits the committed labels instead of
the working tree; the reading is shared, so that costs only adjudication.
"""

import argparse
import json
import os
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from labelaudit import (AUDIT_FIELDS, CONSEQUENCE, FINAL_STATUSES,   # noqa: E402
                        adjudication_key, bootstrap_rate, cell_status, final_status,
                        load_old_csv, read_columns, screen_columns, workbook_at)
from evalkit import discover_corpus, load_truth_sheet                # noqa: E402
from periods import sort_key                                         # noqa: E402
from schema import EXCEL_ROWS                                        # noqa: E402

GT_DIR = ROOT / "data" / "ground_truth"
DEFAULT_ROOTS = [str(ROOT / "data" / "raw"), "~/FinancialReport"]
DEFAULT_PREDICTIONS = "gemini_gemini-3.1-flash-lite_image"
EXIT_QUOTA = 3


# --- what there is to audit ------------------------------------------------------------

class Filing:
    def __init__(self, ticker, quarter, year, pdf):
        self.ticker, self.quarter, self.year, self.pdf = ticker, quarter, year, Path(pdf)

    @property
    def stem(self):
        return f"{self.ticker}_{self.quarter}_{self.year}"

    @property
    def period(self):
        return (self.quarter, self.year)


def load_labels(tickers, version, scratch):
    """{ticker: (columns, letters, problem)} for the chosen version of the labels."""
    out = {}
    for ticker in tickers:
        path = workbook_at(ticker, version, GT_DIR, scratch)
        if path is None:
            continue
        columns, letters = read_columns(path)
        problem = load_truth_sheet(path, ticker).problem
        out[ticker] = (columns, letters, problem)
    return out


def load_predictions(tag, filings):
    out = {}
    for f in filings:
        path = ROOT / "output" / "predictions" / tag / f"{f.stem}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
        except ValueError:
            continue
        values = ((payload.get("_derived") or {}).get("idr_values") or {})
        out.setdefault(f.ticker, {})[f.period] = {
            k: float(v) for k, v in values.items() if k in AUDIT_FIELDS and v is not None}
    return out


def input_tokens(usage):
    """Input tokens from a Usage.to_dict(), or None when the provider reported none."""
    return ((usage or {}).get("tokens") or {}).get("input")


def auditor_tag():
    from auditagent import AUDIT_MODEL
    return "audit_" + AUDIT_MODEL.replace(":", "_").replace("/", "_")


def cache_path(out_dir, filing):
    return out_dir / "filings" / f"{filing.stem}.json"


def load_record(out_dir, filing):
    path = cache_path(out_dir, filing)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None


def save_record(out_dir, filing, record):
    path = cache_path(out_dir, filing)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str))
    tmp.replace(path)          # never a half-written cache file after a kill


# --- phases ------------------------------------------------------------------------------

def phase_screen(filings, labels, predictions, archive_roots):
    flags = []
    for ticker, (columns, _letters, problem) in sorted(labels.items()):
        old = {}
        for root in archive_roots:
            folder = Path(root).expanduser() / ticker
            if folder.is_dir():
                old.update(load_old_csv(folder))
        flags += screen_columns(ticker, columns, predictions.get(ticker), old, problem)
    return flags


def priority(filings, flags):
    """Most suspicious first, so a run cut short by a quota covers the likely errors."""
    score = {}
    for flag in flags:
        if flag.kind == "equals_old_pipeline":
            continue
        key = (flag.ticker, flag.quarter, flag.year)
        score[key] = score.get(key, 0) + flag.severity
    return sorted(filings, key=lambda f: (-score.get((f.ticker, f.quarter, f.year), 0),
                                          f.ticker, sort_key(f.quarter, f.year)))


def related_filings(filing, corpus):
    return {f"{q} {y}": str(path) for (q, y), path in corpus.get(filing.ticker, {}).items()
            if (q, y) != filing.period}


def phase_read(filings, corpus, out_dir, refresh):
    from auditagent import (QuotaExhausted, TokenPacer, audit_models, daily_quota_gone,
                            new_state, read_filing)
    pacer = TokenPacer()
    todo = [f for f in filings
            if refresh or (load_record(out_dir, f) or {}).get("read", {}).get("status") != "done"]
    print(f"\n📖 read: {len(todo)} filing(s) to read, "
          f"{len(filings) - len(todo)} already cached")
    for n, filing in enumerate(todo, 1):
        if daily_quota_gone(audit_models()):
            print(f"\n⛔ daily quota used up on every audit model; {len(todo) - n + 1} "
                  f"filing(s) left pending. Run the same command tomorrow.")
            return False
        print(f"\n[{n}/{len(todo)}] {filing.stem}")
        state = new_state(filing.ticker, filing.quarter, filing.year, str(filing.pdf),
                          related=related_filings(filing, corpus))
        record = load_record(out_dir, filing) or {}
        try:
            read = read_filing(state, pacer=pacer)
        except QuotaExhausted as exc:
            print(f"\n⛔ {exc}; {len(todo) - n + 1} filing(s) left pending. "
                  f"Run the same command tomorrow.")
            return False
        record.update({"schema": 1, "ticker": filing.ticker, "quarter": filing.quarter,
                       "year": filing.year, "pdf": str(filing.pdf), "auditor": auditor_tag(),
                       "read": read})
        save_record(out_dir, filing, record)
        tokens = input_tokens(read.get("usage"))
        print(f"   {read['fields_verified']}/10 verified, {read['stop_reason']}, "
              f"{read['trajectory']['steps_used']} steps, {tokens or '?'} input tokens, "
              f"largest call ~{read['trajectory']['max_call_tokens_estimated']:,}")
    return True


def disputes_for(filing, record, labels):
    from auditagent import evidence_from_record
    columns = labels.get(filing.ticker, ({}, {}, None))[0]
    evidence = evidence_from_record(record.get("read"))
    out = {}
    for name in AUDIT_FIELDS:
        label = columns.get(filing.period, {}).get(name)
        if cell_status(label, evidence.get(name)) == "disputed":
            out[name] = label
    return out, evidence


def phase_adjudicate(filings, corpus, labels, predictions, out_dir):
    from auditagent import (QuotaExhausted, TokenPacer, adjudicate_filing, audit_models,
                            daily_quota_gone, new_state)
    pacer = TokenPacer()
    work = []
    for filing in filings:
        record = load_record(out_dir, filing)
        if not record or "read" not in record:
            continue
        disputes, evidence = disputes_for(filing, record, labels)
        done = record.get("adjudications") or {}
        open_ = {f: v for f, v in disputes.items() if adjudication_key(f, v) not in done}
        if open_:
            work.append((filing, record, open_, evidence))
    print(f"\n⚖️  adjudicate: {sum(len(w[2]) for w in work)} disputed cell(s) "
          f"in {len(work)} filing(s)")
    for n, (filing, record, disputes, evidence) in enumerate(work, 1):
        if daily_quota_gone(audit_models()):
            print(f"\n⛔ daily quota used up; {len(work) - n + 1} filing(s) pending.")
            return False
        print(f"\n[{n}/{len(work)}] {filing.stem}: {', '.join(sorted(disputes))}")
        state = new_state(filing.ticker, filing.quarter, filing.year, str(filing.pdf),
                          related=related_filings(filing, corpus))
        state.evidence = evidence
        try:
            result = adjudicate_filing(state, disputes,
                                       pipeline=predictions.get(filing.ticker, {})
                                       .get(filing.period, {}), pacer=pacer)
        except QuotaExhausted as exc:
            print(f"\n⛔ {exc}; {len(work) - n + 1} filing(s) pending.")
            return False
        record.setdefault("adjudications", {})
        for name, verdict in result["verdicts"].items():
            record["adjudications"][adjudication_key(name, disputes[name])] = verdict
            print(f"   {name}: {verdict['status']} ({verdict.get('cause')})")
        record.setdefault("adjudication_runs", []).append(
            {k: result[k] for k in ("stop_reason", "unsettled", "trajectory", "usage")})
        save_record(out_dir, filing, record)
    return True


# --- the report -----------------------------------------------------------------------------

def collect_cells(filings, labels, out_dir):
    from auditagent import evidence_from_record
    cells = []
    for filing in filings:
        record = load_record(out_dir, filing)
        columns, letters, _ = labels.get(filing.ticker, ({}, {}, None))
        if not record or "read" not in record:
            continue
        evidence = evidence_from_record(record["read"])
        for name in AUDIT_FIELDS:
            label = columns.get(filing.period, {}).get(name)
            status, verdict = final_status(label, evidence.get(name),
                                           record.get("adjudications"))
            ev = evidence.get(name)
            cells.append({"filing": filing.stem, "ticker": filing.ticker,
                          "quarter": filing.quarter, "year": filing.year, "field": name,
                          "cell": (f"{letters.get(filing.period, '?')}{EXCEL_ROWS[name][0]}"),
                          "label": label, "audited": ev.value if ev else None,
                          "status": status, "verdict": verdict,
                          "evidence": ev.to_dict() if ev else None,
                          "visual_only": bool(ev and ev.visual_only)})
    return cells


def summarise(cells, records):
    counts = {s: 0 for s in FINAL_STATUSES}
    for c in cells:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    judged = {"confirmed", "label_wrong", "label_confirmed_on_review", "needs_human"}
    wrong, upper = {}, {}
    for c in cells:
        if c["status"] in judged:
            wrong.setdefault(c["filing"], []).append(int(c["status"] == "label_wrong"))
            upper.setdefault(c["filing"], []).append(
                int(c["status"] in ("label_wrong", "needs_human")))
    labelled = sum(1 for c in cells if c["label"] is not None)
    causes = {}
    for c in cells:
        if c["status"] == "label_wrong":
            cause = (c["verdict"] or {}).get("cause") or "other"
            causes[cause] = causes.get(cause, 0) + 1
    by_ticker = {}
    for c in cells:
        t = by_ticker.setdefault(c["ticker"], {s: 0 for s in FINAL_STATUSES})
        t[c["status"]] += 1
    by_field = {}
    for c in cells:
        t = by_field.setdefault(c["field"], {s: 0 for s in FINAL_STATUSES})
        t[c["status"]] += 1
    tokens = [input_tokens((r.get("read") or {}).get("usage")) for r in records]
    tokens += [input_tokens(run.get("usage"))
               for r in records for run in r.get("adjudication_runs", [])]
    calls = [((r.get("read") or {}).get("usage") or {}).get("llm_calls") for r in records]
    return {
        "filings": len(records), "cells": len(cells), "labelled": labelled,
        "counts": counts,
        "verified_share_of_labelled": (sum(counts[s] for s in judged) +
                                       counts["unadjudicated"]) / labelled if labelled else None,
        "unverifiable_share_of_labelled": ((counts["unverifiable"] + counts["not_found"])
                                           / labelled if labelled else None),
        "label_error_rate": bootstrap_rate(wrong),
        "label_error_rate_upper": bootstrap_rate(upper),
        "causes": causes, "by_ticker": by_ticker, "by_field": by_field,
        "input_tokens_total": sum(t for t in tokens if t),
        "read_calls_total": sum(c for c in calls if c),
        "visual_only_cells": sum(1 for c in cells if c["visual_only"]),
    }


def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def render_report(summary, cells, version, tag):
    s = summary
    rate, upper = s["label_error_rate"], s["label_error_rate_upper"]
    lines = [f"# Label audit — {tag}, labels at `{version}`", "",
             f"{s['filings']} filings read, {s['labelled']} labelled cells.", "",
             "| status | cells |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in s["counts"].items() if v]
    lines += ["", "## Estimated label error rate", "",
              f"- **label_wrong / judged cells: {_pct(rate['rate'])}** "
              f"(95% CI {_pct(rate['lo'])}–{_pct(rate['hi'])}, bootstrap over "
              f"{rate['clusters']} filings, n={rate['n']})",
              f"- upper bound, counting `needs_human` as wrong: {_pct(upper['rate'])} "
              f"({_pct(upper['lo'])}–{_pct(upper['hi'])})",
              f"- cells the audit could not judge (unverifiable or not found): "
              f"{_pct(s['unverifiable_share_of_labelled'])}",
              f"- cells read only from a page image (no text layer to check against): "
              f"{s['visual_only_cells']}", ""]
    if s["causes"]:
        lines += ["## Causes of confirmed label errors", "", "| cause | cells |", "|---|---:|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(s["causes"].items(), key=lambda x: -x[1])]
        lines.append("")
    lines += ["## By issuer", "",
              "| ticker | confirmed | label_wrong | needs_human | unadjudicated | "
              "unverifiable | not_found |", "|---|---:|---:|---:|---:|---:|---:|"]
    for t, c in sorted(s["by_ticker"].items()):
        lines.append(f"| {t} | {c['confirmed'] + c['label_confirmed_on_review']} | "
                     f"{c['label_wrong']} | {c['needs_human']} | {c['unadjudicated']} | "
                     f"{c['unverifiable']} | {c['not_found']} |")
    disputed = [c for c in cells if c["status"] in ("label_wrong", "needs_human",
                                                    "unadjudicated")]
    if disputed:
        lines += ["", "## Disputed cells", "",
                  "| filing | cell | field | label | audited | status | cause |",
                  "|---|---|---|---:|---:|---|---|"]
        for c in disputed:
            lines.append(f"| {c['filing']} | `{c['cell']}` | {c['field']} | "
                         f"{_fmt(c['label'])} | {_fmt(c['audited'])} | {c['status']} | "
                         f"{(c['verdict'] or {}).get('cause') or ''} |")
    lines += ["", f"Tokens: {s['input_tokens_total']:,} input across reading and "
                  f"adjudication; {s['read_calls_total']} reading calls."]
    return "\n".join(lines) + "\n"


def _fmt(v):
    return "—" if v is None else f"{v:,.0f}".replace(",", ".")


def render_proposals(cells, version, tag):
    wrong = [c for c in cells if c["status"] == "label_wrong"]
    lines = ["# Proposed ground-truth corrections", "",
             f"Generated by the agentic label audit ({tag}) on {date.today().isoformat()}, "
             f"against the labels at `{version}`. **Nothing here has been applied.** Each "
             "entry is a form to check against the filing: a person accepts it, edits "
             "the workbook, and moves the entry into `CORRECTIONS.md`.", ""]
    if not wrong:
        lines.append("_No label was shown wrong by a verified citation._")
    for c in wrong:
        v = c["verdict"] or {}
        ev = v.get("evidence") or c["evidence"] or {}
        cited = "\n".join(
            f"  - {'−' if p.get('sign', 1) < 0 else '+'} `{p.get('printed_value')}` on page "
            f"{p.get('page')}, row *{p.get('row_label') or '?'}*, column "
            f"*{p.get('column_found') or p.get('column_header') or '?'}*"
            for p in ev.get("parts", []))
        located = "\n".join(f"  - {h['filing']} p{h['page']} ({h['scale']}): {h['line']}"
                            for h in (v.get("label_located") or [])[:4]) or \
            "  - printed nowhere in this issuer's filings"
        lines += ["---", "",
                  f"## {c['ticker']} `{c['field']}`, {c['quarter']} {c['year']} — "
                  f"{v.get('cause') or 'other'}", "",
                  "| Cell | Was | Proposed |", "|---|---:|---:|",
                  f"| `{c['cell']}` | {_fmt(c['label'])} | **{_fmt(v.get('proposed_value'))}** |",
                  "",
                  "**Origin:** unknown — check whether the label equals the old "
                  "`pdf_to_csv.py` output (the screen flags `equals_old_pipeline`).", "",
                  f"**Found by:** agentic label audit, blind reading then adjudication "
                  f"({tag}).", "",
                  f"**Evidence from the filing** ({ev.get('scale')}, {ev.get('currency')}):",
                  cited or "  - (none recorded)", "",
                  f"**Where the old label is printed:**", located, "",
                  f"**Auditor's reasoning:** {v.get('explanation') or ''}"
                  + (f" — quoting *{v.get('quote')}*" if v.get("quote") else ""), "",
                  f"**Consequence if left:** biases {CONSEQUENCE.get(c['field'], 'derived ratios')}, "
                  f"and scores the extractor against the wrong figure.", ""]
    return "\n".join(lines) + "\n"


def estimate(filings, out_dir):
    records = [r for r in (load_record(out_dir, f) for f in filings)
               if r and (r.get("read") or {}).get("usage")]
    done = sum(1 for r in records if r["read"].get("status") == "done")
    left = len(filings) - len(records)
    if not records:
        print("No reading cached yet: run a pilot first, e.g. --filings GTRA_Q2_2024")
        return
    tokens = sorted((input_tokens(r["read"]["usage"]) or 0) for r in records)
    calls = sorted((r["read"]["usage"].get("llm_calls") or 0) for r in records)
    mean_t, mean_c = sum(tokens) / len(tokens), sum(calls) / len(calls)
    p90_t = tokens[int(0.9 * (len(tokens) - 1))]
    print(f"\nMeasured on {len(records)} filing(s) read ({done} complete):")
    print(f"  input tokens per filing: mean {mean_t:,.0f}, p90 {p90_t:,.0f}, "
          f"max {tokens[-1]:,.0f}")
    print(f"  calls per filing: mean {mean_c:.1f}")
    print(f"\n{left} filing(s) not read yet → about {left * mean_t:,.0f} input tokens "
          f"and {left * mean_c:,.0f} calls (plus adjudication, measured separately).")
    tpm = int(os.getenv("AUDIT_TPM_LIMIT", "0"))
    rpd = int(os.getenv("AUDIT_RPD_LIMIT", "0"))
    if tpm:
        print(f"  at AUDIT_TPM_LIMIT={tpm:,}: at least {left * mean_t / tpm:,.0f} minutes "
              f"of pacing")
    if rpd:
        print(f"  at AUDIT_RPD_LIMIT={rpd:,} calls/day: about "
              f"{left * mean_c / rpd:,.1f} day(s)")
    if not (tpm or rpd):
        print("  set AUDIT_TPM_LIMIT / AUDIT_RPD_LIMIT to your quota to get a duration")


# --- main ----------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", action="store_true", help="every labelled filing")
    ap.add_argument("--tickers", nargs="+")
    ap.add_argument("--filings", nargs="+", help="stems such as GTRA_Q2_2024")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sample-seed", type=int)
    ap.add_argument("--corpus-root", nargs="+", default=DEFAULT_ROOTS)
    ap.add_argument("--phase", choices=["screen", "read", "adjudicate", "report", "all"],
                    default="all")
    ap.add_argument("--labels", default="worktree",
                    help="'worktree' (default) or a git revision such as HEAD")
    ap.add_argument("--predictions-tag", default=DEFAULT_PREDICTIONS)
    ap.add_argument("--out", default=str(ROOT / "output" / "label_audit"))
    ap.add_argument("--refresh", action="store_true", help="re-read cached filings")
    ap.add_argument("--estimate", action="store_true",
                    help="print the measured cost per filing and the projection; no calls")
    args = ap.parse_args()

    if not (args.corpus or args.tickers or args.filings):
        ap.error("say what to audit: --corpus, --tickers or --filings")

    corpus = discover_corpus(args.corpus_root, args.tickers)
    tickers = sorted(t for t in corpus if (GT_DIR / f"{t}.xlsx").exists())
    out_dir = Path(args.out) / auditor_tag()
    scratch = Path(args.out) / "_revisions"
    labels = load_labels(tickers, args.labels, scratch)

    filings = [Filing(t, q, y, pdf) for t in tickers
               for (q, y), pdf in corpus[t].items()
               if any(v is not None for v in labels.get(t, ({}, {}, None))[0]
                      .get((q, y), {}).values())]
    if args.filings:
        wanted = {s.upper() for s in args.filings}
        filings = [f for f in filings if f.stem.upper() in wanted]
    predictions = load_predictions(args.predictions_tag, filings)

    flags = phase_screen(filings, labels, predictions, args.corpus_root)
    filings = priority(filings, flags)
    if args.sample_seed is not None:
        random.Random(args.sample_seed).shuffle(filings)
    if args.limit:
        filings = filings[:args.limit]
    print(f"{len(filings)} labelled filing(s) across {len(tickers)} issuer(s); "
          f"labels at {args.labels}; auditor {auditor_tag()}")

    if args.estimate:
        estimate(filings, out_dir)
        return 0

    if args.phase in ("screen", "all"):
        strong = [f for f in flags if f.severity >= 2]
        kinds = {}
        for f in flags:
            kinds[f.kind] = kinds.get(f.kind, 0) + 1
        print(f"\n🔎 screen: {len(flags)} flag(s) — " +
              ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
        for f in sorted(strong, key=lambda f: (-f.severity, f.ticker, f.year, f.quarter))[:40]:
            print(f"   [{f.severity}] {f.ticker} {f.quarter} {f.year} "
                  f"{f.field or ''} {f.kind}: {f.detail}")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"screen_{args.labels}.json").write_text(
            json.dumps([f.to_dict() for f in flags], indent=1))
        if args.phase == "screen":
            return 0

    from auditagent import AuditConfigError, check_independence
    try:
        check_independence()
    except AuditConfigError as exc:
        print(f"✗ {exc}")
        return 2

    complete = True
    if args.phase in ("read", "all"):
        complete = phase_read(filings, corpus, out_dir, args.refresh)
    if complete and args.phase in ("adjudicate", "all"):
        complete = phase_adjudicate(filings, corpus, labels, predictions, out_dir)
    if args.phase in ("report", "all"):
        records = [r for r in (load_record(out_dir, f) for f in filings) if r]
        cells = collect_cells(filings, labels, out_dir)
        summary = summarise(cells, records)
        suffix = "" if args.labels == "worktree" else f"_{args.labels}"
        (out_dir / f"audit_report{suffix}.json").write_text(
            json.dumps({"labels": args.labels, "auditor": auditor_tag(), "summary": summary,
                        "cells": cells}, indent=1, default=str))
        (out_dir / f"audit_report{suffix}.md").write_text(
            render_report(summary, cells, args.labels, auditor_tag()))
        (out_dir / f"PROPOSED_CORRECTIONS{suffix}.md").write_text(
            render_proposals(cells, args.labels, auditor_tag()))
        pending = len(filings) - len(records)
        print(f"\n📝 {out_dir}/audit_report{suffix}.md"
              + (f"  ({pending} filing(s) not read yet)" if pending else ""))
        print(f"   label_wrong {summary['counts']['label_wrong']}, needs_human "
              f"{summary['counts']['needs_human']}, confirmed "
              f"{summary['counts']['confirmed'] + summary['counts']['label_confirmed_on_review']}")
    return 0 if complete else EXIT_QUOTA


if __name__ == "__main__":
    sys.exit(main())
