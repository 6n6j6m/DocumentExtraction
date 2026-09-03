#!/usr/bin/env python3
"""
Evaluate the extraction pipeline against the ground truth in data/ground_truth/<TICKER>.xlsx.

The spreadsheet is the system of record: one column per period, one row per field
(the row numbers live in src/schema.py EXCEL_ROWS). Its figures are stated in full
Rupiah, so predictions -- which come out of the filing in whatever currency and
scale it was printed in -- are normalised to Rupiah before being compared.

Two comparisons are reported per field, because they fail for different reasons:

  as-printed (USD)  isolates EXTRACTION error -- did the model read the right line?
  converted (IDR)   adds CONVERSION error    -- was the scale and rate right?

A field can be right in USD and wrong in IDR (bad rate/scale), which is a different
bug from reading the wrong row, so they are never collapsed into one number.

Predictions are cached under output/predictions/, so re-running to inspect results
costs no API calls. Use --no-cache to force a fresh extraction.

Usage:
    python scripts/run_eval.py                          # all periods
    python scripts/run_eval.py --periods Q1 Q2          # a subset
    python scripts/run_eval.py --no-cache --tolerance 0.001
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import openpyxl

from schema import FinancialStatementExtraction, EXCEL_ROWS
from normalize import to_idr, extract_fx_rate
from extract import extract_from_pdf
from llm import get_provider_with_fallback, LLMError, LLMUnavailable
from usage import Usage

HEADER_ROW = 3

# Environment that changes what the run measures. Recorded with the scorecard so a
# difference between two runs can be attributed instead of assumed.
TRACKED_CONFIG = [
    "LLM_PROVIDER", "GEMINI_MODEL", "OLLAMA_MODEL",
    "GEMINI_INPUT_MODE", "OLLAMA_INPUT_MODE",
    "SPLIT_BY_STATEMENT", "CONDENSE_TEXT", "IMAGE_DPI",
    "CONFIDENCE_ABSTAIN_THRESHOLD", "MAX_PDF_PAGES",
]


def run_metadata(tolerance: float) -> dict:
    """Everything needed to say whether two scorecards are comparable.

    A score that moved between runs is only informative if you know what else moved.
    The prompt hash matters most: prompts are edited far more often than code, and a
    prompt change is invisible in a git diff of the harness.
    """
    from prompts import SYSTEM_PROMPT, EXTRACTION_PROMPT

    def git(*args):
        try:
            return subprocess.check_output(["git", *args], cwd=ROOT,
                                           stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            # No .git -- running inside the image, which excludes it. The build stamps
            # GIT_COMMIT so the scorecard can still say which code produced it; without
            # that, a containerised run is unattributable and cannot be compared with
            # anything.
            return os.getenv("GIT_COMMIT") if args[:1] == ("rev-parse",) else None

    # Tracked modifications only. An untracked scratch file in data/ does not make a
    # run irreproducible, but a modified source file does -- lumping the two together
    # leaves the flag permanently true and therefore meaningless.
    dirty = git("status", "--porcelain", "--untracked-files=no")
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git("rev-parse", "--short", "HEAD"),
        "git_dirty": bool(dirty) if dirty is not None else None,
        "prompt_sha256": hashlib.sha256(
            (SYSTEM_PROMPT + EXTRACTION_PROMPT).encode()).hexdigest()[:12],
        "tolerance": tolerance,
        "config": {k: os.getenv(k) for k in TRACKED_CONFIG if os.getenv(k) is not None},
    }

QUARTER_END = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}


def discover_periods(ticker: str) -> dict:
    """Find the filings present for a ticker and map them to spreadsheet columns.

    Derived from what is on disk rather than hard-coded, so a second issuer needs no
    code change. Filenames follow <Quarter>_<Year>_<TICKER>.pdf.

    The Q4 filing is the annual report, which the spreadsheet heads "TAHUNAN <year>"
    rather than "Q4 <year>" -- the figures are cumulative for the year, so the label
    reflects that.
    """
    periods = {}
    for pdf in sorted((ROOT / "data" / "raw").glob(f"*_{ticker}.pdf")):
        parts = pdf.stem.split("_")
        if len(parts) < 3 or parts[0] not in QUARTER_END:
            continue
        quarter, year = parts[0], parts[1]
        label = f"TAHUNAN {year}" if quarter == "Q4" else f"{quarter} {year}"
        periods[quarter] = (label, pdf.stem, f"{year}-{QUARTER_END[quarter]}")
    return periods


TICKER_CELL = "D1"      # the sheet names its own issuer here


def load_ground_truth(xlsx_path: Path, period_label: str, ticker: str = None) -> dict:
    """Read one period's column. Returns {field: idr_value_or_None}.

    The sheet is checked against the ticker being evaluated first. These workbooks
    are made by copying an existing one and overwriting the columns, so a copy that
    was never re-labelled scores one issuer's extraction against another issuer's
    figures -- and every field comes back `wrong` for a reason that is nowhere in
    the output. The sheet names its own issuer; comparing costs one cell read.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Sheet1"]

    sheet_ticker = ws[TICKER_CELL].value
    if ticker and isinstance(sheet_ticker, str) and sheet_ticker.strip().upper() != ticker.upper():
        raise ValueError(
            f"{xlsx_path.name} is labelled for {sheet_ticker.strip()!r} in cell "
            f"{TICKER_CELL}, but the run is for {ticker!r}. This is what an "
            f"un-relabelled copy of another issuer's sheet looks like; fix the sheet "
            f"rather than scoring against the wrong figures."
        )

    column = None
    for cell in ws[HEADER_ROW]:
        if isinstance(cell.value, str) and cell.value.strip() == period_label:
            column = cell.column_letter
            break
    if column is None:
        raise KeyError(f"No column headed {period_label!r} in row {HEADER_ROW} of {xlsx_path.name}")

    truth = {}
    for field, (row, _label) in EXCEL_ROWS.items():
        value = ws[f"{column}{row}"].value
        truth[field] = float(value) if isinstance(value, (int, float)) else None
    return truth


def extract_via_api(pdf_path: Path, api_url: str, timeout: int = 600):
    """Extract by POSTing the filing to a running service.

    The only difference from the in-process path is *where the extraction happens*.
    Everything after this -- normalising to Rupiah, comparing, classifying failures --
    is the same code operating on the same object, which is what makes the two paths
    comparable by construction rather than by inspection. A second scoring
    implementation for the service would be a second thing to keep correct, and the
    scorecard could not then be used to say whether the service and the library agree.

    Raises LLMError so the caller's existing per-period recovery applies unchanged.
    """
    import httpx

    url = api_url.rstrip("/") + "/extract"
    try:
        with open(pdf_path, "rb") as handle:
            response = httpx.post(
                url,
                files={"file": (pdf_path.name, handle, "application/pdf")},
                timeout=timeout,
            )
    except httpx.HTTPError as exc:
        raise LLMError(f"could not reach {url}: {exc}")

    if response.status_code == 503:
        # The service is up but its provider is not. Same meaning as the in-process
        # LLMUnavailable, and the caller already knows what to do with it.
        raise LLMError(f"API reports provider unavailable: "
                       f"{response.json().get('detail', response.text)[:200]}")
    if response.status_code != 200:
        raise LLMError(f"API {response.status_code}: {response.text[:200]}")

    body = response.json()
    result = FinancialStatementExtraction.from_dict(body["extraction"])
    result.field_confidence = body.get("confidence", {})
    result.usage_dict = body.get("usage")
    return result


def predict(pdf_path: Path, cache_path: Path, use_cache: bool,
            api_url: Optional[str] = None):
    """Extract from a filing, caching the raw (as-printed) result.

    `api_url` chooses WHERE extraction runs, not how it is scored.
    """
    if use_cache and cache_path.exists():
        data = json.loads(cache_path.read_text())
        # Cached payloads are read back through the same type checks as a live model
        # response: a hand-edited or stale cache is exactly the kind of input that used
        # to raise deep inside a validation rule instead of being rejected here.
        result = FinancialStatementExtraction.from_dict(
            {k: v for k, v in data.items() if not k.startswith("_")})
        # Confidence lives beside the fields rather than inside the dataclass, so it
        # has to be restored explicitly or a cached run loses it silently.
        result.field_confidence = data.get("_confidence", {})
        result.elapsed_s = data.get("_elapsed_s")
        result.usage_dict = data.get("_usage")
        return result, True

    started = time.time()
    if api_url:
        result = extract_via_api(pdf_path, api_url)
    else:
        usage = Usage()
        result = extract_from_pdf(str(pdf_path), usage=usage)
        if result is not None:
            result.usage_dict = usage.to_dict()
    if result is None:
        return None, False
    result.elapsed_s = round(time.time() - started, 1)

    payload = result.to_dict()
    payload["_confidence"] = getattr(result, "field_confidence", {})
    payload["_elapsed_s"] = result.elapsed_s
    payload["_usage"] = getattr(result, "usage_dict", None)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2))
    return result, False


# Counting failures is not the same as understanding them. A scale bug, a
# comparative-column read and an invented number all show up as "wrong", but they
# have different causes and different fixes, so each wrong answer is classified.
def classify_failure(pred, truth, grounded) -> str:
    """Name the KIND of wrong answer, from its relationship to the truth."""
    if truth == 0:
        return "wrong_value"
    ratio = pred / truth

    for factor, name in ((1000, "scale_1e3"), (1e6, "scale_1e6"), (1e9, "scale_1e9")):
        if abs(ratio - factor) < 0.01 or abs(ratio - 1 / factor) < 1e-9:
            return f"wrong_{name}"
    # An FX rate applied when it should not have been, or omitted when it should.
    if 8_000 < ratio < 25_000 or 8_000 < 1 / ratio < 25_000:
        return "wrong_currency_conversion"
    if abs(ratio + 1) < 0.01:
        return "wrong_sign"
    if grounded is False:
        return "hallucinated"          # value is not printed anywhere in the filing
    if abs(ratio - 1) < 0.05:
        return "wrong_near_miss"       # neighbouring row, or comparative column
    return "wrong_value"


def compare(pred, truth, rel_tol, grounded=None):
    """Compare one field. Returns (status, rel_error, failure_kind)."""
    if truth is None and pred is None:
        return "both_absent", None, None
    if truth is None:
        return "no_truth", None, None
    if pred is None:
        return "missed", None, None
    denominator = max(abs(truth), 1.0)
    error = abs(pred - truth) / denominator
    if error <= rel_tol:
        return "correct", error, None
    return "wrong", error, classify_failure(pred, truth, grounded)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="ARCI")
    ap.add_argument("--periods", nargs="*", default=None)
    ap.add_argument("--tolerance", type=float, default=1e-4,
                    help="relative tolerance, default 0.0001 (0.01%%)")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--out", default="output")
    ap.add_argument("--provider", help="override LLM_PROVIDER for this run (gemini|ollama)")
    ap.add_argument("--api-url", default=os.getenv("EVAL_TARGET") or None,
                    help="score a running service instead of the library "
                         "(e.g. http://localhost:8000). Defaults to $EVAL_TARGET; "
                         "empty means in-process, so the tests need no container.")
    args = ap.parse_args()

    PERIODS = discover_periods(args.ticker)
    if not PERIODS:
        print(f"No filings found matching data/raw/*_{args.ticker}.pdf")
        return 2
    args.periods = args.periods or sorted(PERIODS)

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
        os.environ["LLM_FALLBACK_PROVIDER"] = ""   # comparing providers means no silent switch
    if args.api_url:
        # The service decides which model answers; reading LLM_PROVIDER here would tag
        # the scorecard with this process's configuration and quietly mislabel the run.
        import httpx
        try:
            health = httpx.get(args.api_url.rstrip("/") + "/health", timeout=30).json()
        except Exception as exc:
            print(f"cannot reach {args.api_url}: {exc}")
            return 2
        print(f"target: {args.api_url}  ({health['provider']} [{health['input_mode']}], "
              f"commit {health.get('git_commit')})")

        class _Remote:
            name = health["provider"]
            input_mode = health["input_mode"]
        _p = _Remote()
    else:
        try:
            _p = get_provider_with_fallback()[0]
        except LLMUnavailable as exc:
            # No usable provider -- almost always a reviewer who has not set up a key
            # yet. The committed predictions can still be scored, and that path calls
            # no model at all, so refusing to start would deny them the one thing they
            # can check for free. The tag is rebuilt from configuration instead, which
            # is what names the cache directory anyway.
            provider = os.getenv("LLM_PROVIDER", "gemini").lower()
            model = os.getenv(f"{provider.upper()}_MODEL",
                              "gemini-3.1-flash-lite" if provider == "gemini"
                              else "qwen2.5:7b-instruct")
            mode = os.getenv(f"{provider.upper()}_INPUT_MODE",
                             "image" if provider == "gemini" else "text")

            class _Offline:
                name = f"{provider}:{model}"
                input_mode = mode
            _p = _Offline()

            print(f"⚠ {exc}")
            print(f"  no provider configured, so only CACHED predictions can be scored.")
            print(f"  assuming {_p.name} [{mode}] from configuration, to find the cache.")
            if args.no_cache:
                print("  --no-cache needs a working provider; nothing to extract with.")
                return 2
    # The input mode changes what the model is shown, so two runs of the same model
    # are different experiments. Without it in the tag they overwrite each other and
    # the comparison silently becomes a comparison of a run with itself.
    provider_tag = (f"{_p.name}_{getattr(_p, 'input_mode', 'text')}"
                    .replace(":", "_").replace("/", "_"))
    # Scoring the service and scoring the library are two experiments, even when the
    # model behind them is the same one. Without this the API run overwrites the local
    # run's scorecard and its cached predictions, and the comparison that is supposed to
    # prove the two paths agree quietly becomes a run compared with itself -- the exact
    # failure the input mode is already in this name to prevent.
    if args.api_url:
        provider_tag += "_api"
    # A subset run gets its own filename. Otherwise `--periods Q1` overwrites the
    # full four-period scorecard with a one-period one, and the committed artifact
    # quietly stops meaning what its name says -- which happened once already.
    subset = "" if set(args.periods) == set(PERIODS) else "_" + "".join(sorted(args.periods))
    # The ticker names the scorecard too. It was missing for the same reason it was
    # missing from the cache -- one issuer was the only issuer -- and the second one
    # silently overwrote the first one's committed result on its very first run.
    scorecard_name = f"scorecard_{args.ticker}_{provider_tag}{subset}.json"
    print(f"provider: {provider_tag}")

    xlsx = ROOT / "data" / "ground_truth" / f"{args.ticker}.xlsx"
    out_dir = ROOT / args.out
    report = {"ticker": args.ticker, "tolerance": args.tolerance,
              "run": run_metadata(args.tolerance), "periods": {}}
    tally = {"correct": 0, "wrong": 0, "missed": 0, "no_truth": 0, "both_absent": 0}
    failure_kinds = {}

    for key in args.periods:
        if key not in PERIODS:
            print(f"[{key}] SKIP - no filing for this period")
            continue
        label, stem, expected_date = PERIODS[key]
        pdf = ROOT / "data" / "raw" / f"{stem}.pdf"
        if not pdf.exists():
            print(f"[{key}] SKIP - {pdf.name} not found")
            continue

        print(f"\n{'='*78}\n{key}  ({label})  {pdf.name}\n{'='*78}")
        truth = load_ground_truth(xlsx, label, ticker=args.ticker)

        # One period failing must not abandon the others: a scorecard covering three
        # of four periods with the fourth recorded as failed is still usable, and the
        # recorded failure is itself a result worth keeping.
        try:
            pred, cached = predict(
                # The ticker belongs in the cache name. Without it "Q1" means one
                # thing for ARCI and another for JPFA, and a second issuer silently
                # scores the FIRST issuer's cached prediction against its own labels --
                # every field wrong, for a reason that appears nowhere in the output.
                pdf, out_dir / "predictions" / provider_tag / f"{args.ticker}_{key}.json",
                not args.no_cache, api_url=args.api_url)
        except LLMError as exc:
            print(f"  extraction failed: {exc}")
            report["periods"][key] = {"error": str(exc)}
            tally["failed_periods"] = tally.get("failed_periods", 0) + 1
            continue
        if pred is None:
            print("  extraction failed - no fields returned")
            report["periods"][key] = {"error": "extraction_failed"}
            continue
        if cached:
            print("  (cached prediction; --no-cache to re-extract)")

        fx = extract_fx_rate(str(pdf))
        rate = fx.idr_per_usd if fx else None
        from extract import read_page_texts, build_document_text
        from page_select import select_statement_pages
        doc_text = build_document_text(
            read_page_texts(str(pdf), select_statement_pages(str(pdf)).pages))
        converted = to_idr(pred, pdf_path=str(pdf), document_text=doc_text)["values"]

        if pred.period_end_date != expected_date:
            print(f"  ⚠ period_end_date {pred.period_end_date!r}, expected {expected_date!r}")
        if rate:
            print(f"  kurs {rate:,.2f} IDR/USD  (hal. {fx.page}, {fx.source})")

        print(f"\n  {'field':28}{'as printed':>16}{'truth (USD)':>16}{'IDR err':>10}  status")
        rows = {}
        for field in EXCEL_ROWS:
            truth_idr = truth[field]
            pred_idr = converted.get(field)
            conf = (getattr(pred, "field_confidence", {}) or {}).get(field, {})
            status, err, kind = compare(pred_idr, truth_idr, args.tolerance,
                                        conf.get("grounded"))
            tally[status] += 1
            if kind:
                failure_kinds[kind] = failure_kinds.get(kind, 0) + 1
            if status == "missed" and conf.get("abstained"):
                tally["missed_abstained"] = tally.get("missed_abstained", 0) + 1

            raw = getattr(pred, field, None)
            truth_usd = (truth_idr / rate) if (truth_idr and rate and field != "total_share") else truth_idr
            rows[field] = {"status": status, "rel_error": err, "failure_kind": kind,
                           "pred_idr": pred_idr, "truth_idr": truth_idr, "pred_raw": raw,
                           "confidence": conf.get("confidence"),
                           "grounded": conf.get("grounded"),
                           "abstained": conf.get("abstained")}

            mark = {"correct": "OK", "wrong": f"<<< {kind}", "missed": "-- missed",
                    "no_truth": "(no truth)", "both_absent": "(both empty)"}[status]
            if status == "missed" and conf.get("abstained"):
                mark = "-- abstained"
            print(f"  {field:28}"
                  f"{raw if raw is not None else '-':>16}"
                  f"{f'{truth_usd:,.0f}' if truth_usd else '-':>16}"
                  f"{f'{err:.2%}' if err is not None else '-':>10}  {mark}")

        abstained = [f for f, r in rows.items() if r.get("abstained")]
        report["periods"][key] = {"fx_rate": rate, "fields": rows,
                                  "elapsed_s": getattr(pred, "elapsed_s", None),
                                  "usage": getattr(pred, "usage_dict", None),
                                  "abstained": abstained}

    total_scored = tally["correct"] + tally["wrong"] + tally["missed"]
    print(f"\n{'='*78}\nSUMMARY")
    print(f"  correct      {tally['correct']:>3}")
    print(f"  wrong        {tally['wrong']:>3}")
    print(f"  missed       {tally['missed']:>3}   (truth exists, model returned nothing)")
    print(f"  no truth     {tally['no_truth']:>3}   (not scored)")
    if tally.get("missed_abstained"):
        print(f"    of which abstained deliberately: {tally['missed_abstained']}")
    if failure_kinds:
        print("\n  failures by kind:")
        for kind, n in sorted(failure_kinds.items(), key=lambda kv: -kv[1]):
            print(f"    {kind:28}{n:>3}")
    if total_scored:
        print(f"\n  accuracy     {tally['correct']/total_scored:.1%}  ({tally['correct']}/{total_scored})")

    # Totals across the run. Summed from what each period reported rather than
    # recomputed, so a cached period contributes the usage of the run that produced it
    # and a period that failed contributes nothing instead of a zero that reads as free.
    per_period = [p.get("usage") for p in report["periods"].values() if p.get("usage")]
    if per_period:
        tokens_in = [u["tokens"]["input"] for u in per_period
                     if u.get("tokens", {}).get("input") is not None]
        tokens_out = [u["tokens"]["output"] for u in per_period
                      if u.get("tokens", {}).get("output") is not None]
        priced = [u["cost"]["amount"] for u in per_period
                  if u.get("cost", {}).get("amount") is not None]
        totals = {
            "documents": len(per_period),
            "llm_calls": sum(u.get("llm_calls", 0) for u in per_period),
            "tokens": {"input": sum(tokens_in) if tokens_in else None,
                       "output": sum(tokens_out) if tokens_out else None},
            "cost": {"amount": round(sum(priced), 6) if len(priced) == len(per_period)
                                else None,
                     "currency": per_period[0].get("cost", {}).get("currency", "USD"),
                     "reason": None if len(priced) == len(per_period)
                               else per_period[0].get("cost", {}).get("reason")},
        }
        report["usage"] = totals
        print("\n  usage")
        print(f"    documents           {totals['documents']:>3}")
        print(f"    LLM calls           {totals['llm_calls']:>3}")
        t = totals["tokens"]
        print(f"    tokens              {t['input'] if t['input'] is not None else '-'} in"
              f" / {t['output'] if t['output'] is not None else '-'} out")
        cost = totals["cost"]
        if cost["amount"] is not None:
            print(f"    cost                {cost['amount']} {cost['currency']}")
        else:
            print(f"    cost                -  ({cost['reason']})")
        elapsed = [p.get("elapsed_s") for p in report["periods"].values()
                   if p.get("elapsed_s")]
        if elapsed:
            print(f"    latency             {min(elapsed):.0f}-{max(elapsed):.0f}s per "
                  f"document (mean {sum(elapsed)/len(elapsed):.0f}s)")

    report["summary"] = tally
    report["failure_kinds"] = failure_kinds
    report["provider"] = provider_tag
    report["target"] = args.api_url or "in-process"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / scorecard_name).write_text(json.dumps(report, indent=2, default=str))
    print(f"\n  written to {out_dir / scorecard_name}")

    return 1 if tally["wrong"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
