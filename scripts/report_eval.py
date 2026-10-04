#!/usr/bin/env python3
"""
Turn a scorecard into something a person reads.

A scorecard is the record; this is the account of it. They are separate scripts on
purpose: the report re-renders from a committed JSON with no API key, no network and no
PDF, so a reviewer can regenerate every number in it, and CI can publish it as an
artifact of a run that called no model at all.

What the report refuses to do is as important as what it prints:

  * an unpriced run prints "no price configured", never "$0.00" -- a zero cost reads as
    free, and `config/pricing.json` ships empty on purpose;
  * every slice carries its n, so a four-cell slice cannot be read as a result;
  * an abstention whose withheld figure was never recorded is counted as unknown, not
    as a save and not as a loss.

Usage:
    python scripts/report_eval.py output/corpus_scorecard_<tag>.json
    python scripts/report_eval.py <scorecard> --out some/dir
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from evalmetrics import summarise, worst_cells   # noqa: E402

CELL_COLUMNS = ["key", "ticker", "quarter", "year", "field", "status", "rel_error",
                "failure_kind", "pred_idr", "truth_idr", "confidence", "grounded",
                "abstained", "would_have_been", "currency", "reporting_scale",
                "text_layer", "model", "reasons"]


def _pct(value, digits=1):
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _num(value, digits=0):
    return "—" if value is None else f"{value:,.{digits}f}"


def cells_of(scorecard: dict) -> list:
    """The flat cell list, rebuilt from `periods` when a scorecard predates it."""
    if scorecard.get("cells"):
        return scorecard["cells"]
    cells = []
    for key, period in (scorecard.get("periods") or {}).items():
        for field, row in (period.get("fields") or {}).items():
            cells.append({"key": key, "field": field, "ticker": scorecard.get("ticker"),
                          **row})
    return cells


def metrics_of(scorecard: dict) -> dict:
    """The stored metrics, or freshly computed ones for an older scorecard."""
    if scorecard.get("metrics"):
        return scorecard["metrics"]
    filings = [{"elapsed_s": p.get("elapsed_s"), "usage": p.get("usage")}
               for p in (scorecard.get("periods") or {}).values()]
    return summarise(cells_of(scorecard), filings)


def _slice_table(title: str, rows: dict, limit: int = 40) -> list:
    if not rows:
        return []
    out = [f"### {title}", "",
           "| value | n | filings | correct | wrong | missed | accuracy | answered |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    ordered = sorted(rows.items(), key=lambda kv: (kv[1]["accuracy"] is None,
                                                   kv[1]["accuracy"], -kv[1]["scored"]))
    for name, row in ordered[:limit]:
        out.append(f"| {name} | {row['scored']} | {row.get('filings', '—')} | "
                   f"{row['correct']} | {row['wrong']} | {row['missed']} | "
                   f"{_pct(row['accuracy'])} | {_pct(row.get('answer_rate'))} |")
    out.append("")
    return out


def render_markdown(scorecard: dict) -> str:
    metrics = metrics_of(scorecard)
    cells = cells_of(scorecard)
    accuracy = metrics["accuracy"]
    coverage = metrics["coverage"]
    withdrawal = metrics["abstention"]
    cost = metrics.get("cost_latency", {})
    run = scorecard.get("run") or {}
    corpus = scorecard.get("corpus") or {}

    lines = [f"# Evaluation — {scorecard.get('ticker', '?')} on "
             f"`{scorecard.get('provider', '?')}`", ""]
    lines += [f"- **run** {run.get('timestamp', '—')}, commit `{run.get('git_commit', '—')}`"
              f"{' (dirty tree)' if run.get('git_dirty') else ''}, prompt "
              f"`{run.get('prompt_sha256', '—')}`",
              f"- **target** {scorecard.get('target', '—')}, tolerance "
              f"{scorecard.get('tolerance', '—')}"]
    if corpus:
        lines.append(f"- **corpus** {corpus.get('scored_pairs', '—')} of "
                     f"{corpus.get('pairs', '—')} filings scored, "
                     f"{len(corpus.get('tickers') or [])} issuers, "
                     f"{corpus.get('cells_labelled', '—')} labelled cells")
    lines += ["", "## Headline", "",
              "| | |", "|---|---:|",
              f"| accuracy (labelled cells) | **{_pct(accuracy['accuracy'])}** "
              f"({accuracy['correct']}/{accuracy['scored']}) |",
              f"| accuracy when it answered | {_pct(accuracy['accuracy_on_answered'])} |",
              f"| answer rate | {_pct(coverage['answer_rate'])} |",
              f"| wrong | {accuracy['wrong']} |",
              f"| withheld on a labelled cell | {coverage['abstained_on_labelled']} |"]
    if cost.get("documents"):
        seconds = cost.get("seconds_per_filing", {})
        tokens = cost.get("tokens_per_filing", {})
        amount = cost.get("cost", {})
        priced = (f"{amount['amount']} {amount.get('currency', 'USD')}"
                  if amount.get("amount") is not None
                  else f"— ({amount.get('reason') or 'no price configured'})")
        lines += [f"| LLM calls per filing | {_num(cost.get('calls_per_filing'), 2)} |",
                  f"| tokens per filing | {_num(tokens.get('input'))} in / "
                  f"{_num(tokens.get('output'))} out |",
                  f"| seconds per filing (p50 / p95) | {_num(seconds.get('p50'), 1)} / "
                  f"{_num(seconds.get('p95'), 1)} |",
                  f"| cost | {priced} |"]
    lines.append("")

    lines += ["## Coverage", "",
              "Every labelled cell lands in exactly one row. The last three rows are cells",
              "nobody has labelled yet: an abstention there used to vanish into",
              "`both_absent`, counted in neither the numerator nor the denominator.", "",
              "| bucket | n |", "|---|---:|",
              f"| labelled cells | {coverage['labelled']} |",
              f"| … answered correctly | {coverage['correct']} |",
              f"| … answered wrongly | {coverage['wrong']} |",
              f"| … withheld deliberately | {coverage['abstained_on_labelled']} |",
              f"| … missing for another reason | {coverage['missed_not_abstained']} |",
              f"| unlabelled, answered | {coverage['unlabelled_answered']} |",
              f"| unlabelled, withheld | {coverage['unlabelled_abstained']} |",
              f"| unlabelled, silent | {coverage['unlabelled_silent']} |", ""]

    lines += ["## Was withholding the right call?", "",
              f"- **withdrawn** {withdrawal['withdrawn']} labelled cells",
              f"- **caught** {withdrawal['caught']} — the withheld figure would have been wrong",
              f"- **thrown away** {withdrawal['thrown_away']} — it would have been right",
              f"- **precision** {_pct(withdrawal['precision'])}, "
              f"**recall** {_pct(withdrawal['recall'])} "
              f"(of {withdrawal['caught'] + withdrawal['silent_errors']} cells that would "
              f"have been wrong)"]
    if withdrawal["unknown_withheld"]:
        lines.append(f"- **unknown** {withdrawal['unknown_withheld']} withdrawals whose "
                     f"withheld figure was never recorded — excluded from precision "
                     f"rather than assumed either way (predictions cached before "
                     f"`assess()` kept it)")
    lines.append("")

    calibration = metrics["calibration"]
    lines += ["## Calibration", "",
              f"Does a stated confidence mean what it says? ECE "
              f"**{_num(calibration.get('ece'), 3)}** over {calibration.get('n', 0)} "
              f"answered cells; a negative gap is overconfidence.", "",
              "| confidence | n | mean stated | observed accuracy | gap |",
              "|---|---:|---:|---:|---:|"]
    for bucket in calibration["buckets"]:
        if not bucket["n"]:
            continue
        low, high = bucket["range"]
        lines.append(f"| {low:.2f}–{high:.2f} | {bucket['n']} | "
                     f"{_num(bucket['mean_confidence'], 3)} | "
                     f"{_pct(bucket['accuracy'])} | {_num(bucket['gap'], 3)} |")
    lines.append("")

    lines += ["## Slices", "",
              "Each row carries its n. A slice of four cells is an anecdote, and the",
              "column is there so it cannot be quoted as anything else.", ""]
    for name, rows in (metrics.get("slices") or {}).items():
        lines += _slice_table(name, rows)

    behaviour = metrics.get("agent")
    if behaviour and behaviour.get("filings"):
        steps = behaviour["steps_per_filing"]
        images = behaviour["images_per_filing"]
        text_pages = behaviour["text_pages_per_filing"]
        lines += ["## Agent behaviour", "",
                  "What the loop did, not whether it was right. The accuracy table above is",
                  "the only place that answers whether any of this was worth it.", "",
                  "| | |", "|---|---:|",
                  f"| filings run by the agent | {behaviour['filings']} |",
                  f"| steps per filing (p50 / p95 / max) | {_num(steps['p50'])} / "
                  f"{_num(steps['p95'])} / {_num(steps['max'])} |",
                  f"| tool-call error rate | {_pct(behaviour['tool_error_rate'])} |",
                  f"| text pages opened per filing | {_num(text_pages['mean'], 1)} |",
                  f"| images rendered per filing | {_num(images['mean'], 1)} |",
                  f"| statements reported per filing | "
                  f"{_num(behaviour['groups_reported_per_filing'], 2)} of 4 |",
                  f"| budget exhausted | {_pct(behaviour['budget_exhausted_rate'])} of filings |",
                  f"| provider hand-overs per filing | "
                  f"{_num(behaviour['handovers_per_filing'], 2)} |", ""]
        if behaviour.get("tool_errors_by_kind"):
            lines += ["| tool error | n |", "|---|---:|"]
            lines += [f"| {kind} | {n} |"
                      for kind, n in behaviour["tool_errors_by_kind"].items()]
            lines.append("")
        if behaviour.get("stop_reasons"):
            lines += ["| stopped because | n |", "|---|---:|"]
            lines += [f"| {reason} | {n} |"
                      for reason, n in behaviour["stop_reasons"].items()]
            lines.append("")

    agreement = metrics.get("page_agreement")
    if agreement and agreement.get("filings"):
        lines += ["## Page selection", "",
                  "**Agreement, not correctness.** The deterministic selector is the thing",
                  "being contested here, not ground truth -- it needed four hand-written",
                  "patches to reach its current state. Whether the agent chose *better* is",
                  "answered by the accuracy table; this says how differently it chose, which",
                  "is what distinguishes an agent that found something from one that",
                  "rediscovered the selector at several times the cost.", "",
                  "| | |", "|---|---:|",
                  f"| filings compared | {agreement['filings']} |",
                  f"| pages per filing, agent | {_num(agreement['mean_pages_agent'], 1)} |",
                  f"| pages per filing, selector | {_num(agreement['mean_pages_selector'], 1)} |",
                  f"| overlap (Jaccard) | {_pct(agreement['jaccard'])} |",
                  f"| of the agent's pages, also the selector's | {_pct(agreement['precision'])} |",
                  f"| of the selector's pages, also the agent's | {_pct(agreement['recall'])} |", ""]
        for title, key in (("Pages only the agent chose", "pages_only_the_agent_chose"),
                           ("Pages only the selector chose", "pages_only_the_selector_chose")):
            rows = agreement.get(key) or []
            if rows:
                lines += [f"### {title}", ""]
                lines += [f"- {r.get('key') or '?'}: {r['pages']}" for r in rows[:10]]
                lines.append("")

    kinds = metrics.get("failure_kinds") or {}
    if kinds:
        lines += ["## Failures by kind", "", "| kind | n |", "|---|---:|"]
        lines += [f"| {kind} | {count} |" for kind, count in kinds.items()]
        lines.append("")

    skipped = corpus.get("skipped") or []
    errors = scorecard.get("errors") or []
    uncached = corpus.get("uncached") or []
    if skipped or errors or uncached:
        lines += ["## Not measured", ""]
        for entry in skipped:
            lines.append(f"- **{entry['ticker']} skipped** — {entry['reason']} "
                         f"({entry.get('filings', '?')} filings)")
        if uncached:
            lines.append(f"- **{len(uncached)} filings had no cached prediction** and were "
                         f"skipped (`--cached-only`): {', '.join(uncached[:8])}"
                         f"{' …' if len(uncached) > 8 else ''}")
        for error in errors[:20]:
            lines.append(f"- **{error['key']} failed** — {error['error']}")
        lines.append("")

    worst = worst_cells(cells, 25)
    if worst:
        lines += ["## Worst cells", "",
                  "| filing | field | predicted | truth | error | conf | kind | why |",
                  "|---|---|---:|---:|---:|---:|---|---|"]
        for cell in worst:
            reasons = "; ".join(cell.get("reasons") or [])[:80]
            lines.append(f"| {cell.get('key')} | {cell.get('field')} | "
                         f"{_num(cell.get('pred_idr'))} | {_num(cell.get('truth_idr'))} | "
                         f"{_pct(cell.get('rel_error'), 2)} | "
                         f"{_num(cell.get('confidence'), 2)} | "
                         f"{cell.get('failure_kind') or '—'} | {reasons or '—'} |")
        lines.append("")

    lines += ["---", "",
              "Figures are compared in full Rupiah. The conversion is cached arithmetic over",
              "the model's own output (`_derived` beside each prediction), not a second",
              "source of truth: refreshing it cannot change what the model said.", ""]
    return "\n".join(lines)


def render_cells_csv(scorecard: dict) -> str:
    from io import StringIO
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CELL_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for cell in cells_of(scorecard):
        row = dict(cell)
        row["reasons"] = "; ".join(row.get("reasons") or [])
        writer.writerow(row)
    return buffer.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a scorecard as markdown and CSV.")
    ap.add_argument("scorecard")
    ap.add_argument("--out", help="directory for the report (default: beside the scorecard)")
    args = ap.parse_args()

    path = Path(args.scorecard)
    if not path.exists():
        print(f"no scorecard at {path}")
        return 2
    scorecard = json.loads(path.read_text())

    out_dir = Path(args.out) if args.out else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = out_dir / (path.stem + ".md")
    cells_csv = out_dir / (path.stem + ".cells.csv")
    markdown.write_text(render_markdown(scorecard))
    cells_csv.write_text(render_cells_csv(scorecard))
    print(f"{markdown}\n{cells_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
