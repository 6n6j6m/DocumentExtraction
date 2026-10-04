#!/usr/bin/env python3
"""
The pieces an evaluation is built from: what to score, what the truth is, and what one
scored cell means. No printing, no argparse, no files written -- `scripts/run_eval.py`
is the driver, this is the machinery, and the split is what lets the metrics be tested
without a model, a key or a PDF.

Three things here exist because the single-ticker harness could not grow without them.

**A period is a tuple, not a string.** See `src/periods.py`.

**A bad workbook is a result, not an exception.** `load_ground_truth()` raises on a
sheet labelled for another issuer, which is right for a four-period run and fatal for a
223-filing one: one stale cell in one workbook would end the whole pass. `load_truth_sheet`
returns the problem in a field instead, so the run continues and the report names it.

**A cell carries its own slices.** `Cell` denormalises currency, scale, text-layer quality
and answering model onto every row, so "accuracy on shredded text layers" is a filter
rather than a join, and a scorecard read back from disk is enough to compute it.
"""

import hashlib
import json
from dataclasses import dataclass, field as dataclass_field, asdict
from pathlib import Path
from typing import Optional

import openpyxl

from periods import QUARTER_END, parse_period, parse_filing_stem, period_end_date, sort_key
from schema import EXCEL_ROWS, FinancialStatementExtraction

HEADER_ROW = 3
TICKER_CELL = "D1"      # the sheet names its own issuer here


# --- what to score ---------------------------------------------------------------

@dataclass(frozen=True)
class PeriodRef:
    """One (issuer, period) pair with a filing on disk."""
    ticker: str
    quarter: str
    year: int
    pdf: Path

    @property
    def key(self) -> str:
        """The cell key used in scorecards and in compare_runs: "ARCI Q1 2022"."""
        return f"{self.ticker} {self.quarter} {self.year}"

    @property
    def cache_stem(self) -> str:
        """Prediction cache filename stem.

        The year is part of it. Without it, ARCI Q1 2022 and ARCI Q1 2023 are the same
        file, and the second year silently scores the first year's prediction against
        its own labels -- every field wrong, for a reason that appears nowhere.
        """
        return f"{self.ticker}_{self.quarter}_{self.year}"

    @property
    def end_date(self) -> str:
        return period_end_date(self.quarter, self.year)

    @property
    def order(self) -> tuple:
        return (self.ticker,) + sort_key(self.quarter, self.year)


def discover_corpus(roots, tickers=None) -> dict:
    """{ticker: {(quarter, year): pdf}} for every filing under `roots`.

    Each root is read two ways, because the repo and the archive are laid out
    differently: flat (`data/raw/Q1_2022_ARCI.pdf`) and one folder per issuer
    (`~/FinancialReport/ARCI/Q1_2022_ARCI.pdf`). Earlier roots win, so a filing
    committed to the repo shadows the same filing in a personal archive and CI scores
    what a reviewer can see.
    """
    found = {}
    for root in [Path(r).expanduser() for r in roots]:
        if not root.exists():
            continue
        for pdf in sorted(root.glob("*.pdf")) + sorted(root.glob("*/*.pdf")):
            parsed = parse_filing_stem(pdf.stem)
            if not parsed:
                continue
            ticker, quarter, year = parsed
            if tickers and ticker not in {t.upper() for t in tickers}:
                continue
            found.setdefault(ticker, {}).setdefault((quarter, year), pdf)
    return found


# --- what the truth is -----------------------------------------------------------

@dataclass
class TruthSheet:
    """One issuer's labels, or the reason there are none."""
    ticker: str
    path: Path
    columns: dict = dataclass_field(default_factory=dict)   # {(quarter, year): {field: value}}
    problem: Optional[str] = None

    @property
    def labelled_cells(self) -> int:
        return sum(1 for col in self.columns.values()
                   for value in col.values() if value is not None)


def load_truth_sheet(xlsx_path: Path, ticker: str) -> TruthSheet:
    """Read every period column of one workbook. Never raises on a bad sheet.

    `problem` is set, and `columns` left empty, when the workbook cannot be trusted for
    this ticker -- it is missing, it has no `Sheet1`, it has no period headers, or it
    names another issuer in D1. A corpus run reports those and carries on; only a
    single-ticker run (see `run_eval.load_ground_truth`) still treats them as fatal.
    """
    sheet = TruthSheet(ticker=ticker.upper(), path=xlsx_path)
    if not xlsx_path.exists():
        sheet.problem = f"no workbook at {xlsx_path.name}"
        return sheet
    try:
        workbook = openpyxl.load_workbook(xlsx_path, data_only=True)
    except Exception as exc:                      # a corrupt or locked file
        sheet.problem = f"{xlsx_path.name} could not be opened: {exc}"
        return sheet
    if "Sheet1" not in workbook.sheetnames:
        sheet.problem = f"{xlsx_path.name} has no 'Sheet1' (sheets: {workbook.sheetnames})"
        return sheet
    worksheet = workbook["Sheet1"]

    named = worksheet[TICKER_CELL].value
    if isinstance(named, str) and named.strip().upper() != ticker.upper():
        sheet.problem = (f"{xlsx_path.name} is labelled {named.strip()!r} in {TICKER_CELL} "
                         f"but holds the filings of {ticker.upper()}; an un-relabelled copy "
                         f"scores one issuer against another's figures")
        return sheet

    columns = {}
    for cell in worksheet[HEADER_ROW]:
        period = parse_period(cell.value) if isinstance(cell.value, str) else None
        if not period:
            continue
        letter = cell.column_letter
        columns[period] = {
            name: (float(worksheet[f"{letter}{row}"].value)
                   if isinstance(worksheet[f"{letter}{row}"].value, (int, float)) else None)
            for name, (row, _label) in EXCEL_ROWS.items()
        }
    if not columns:
        sheet.problem = f"{xlsx_path.name} has no period headers in row {HEADER_ROW}"
        return sheet
    sheet.columns = columns
    return sheet


# --- what one scored cell means --------------------------------------------------

# Counting failures is not the same as understanding them. A scale bug, a
# comparative-column read and an invented number all show up as "wrong", but they
# have different causes and different fixes, so each wrong answer is classified.
def classify_failure(pred, truth, grounded) -> str:
    """Name the KIND of wrong answer, from its relationship to the truth."""
    if truth == 0:
        return "wrong_value"
    ratio = pred / truth
    if ratio == 0:
        # A nil reported where the filing prints a figure. Found by the first
        # full-corpus pass: every ratio test below divides by `ratio`, so this raised
        # ZeroDivisionError three frames down and cost the whole filing its row --
        # a classifier crashing on a wrong answer, which is the one input it exists for.
        return "wrong_value"

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


@dataclass
class Cell:
    """One (filing, field) result, with everything a metric needs to slice it."""
    key: str                       # "ARCI Q1 2022"
    ticker: str
    quarter: str
    year: int
    field: str
    status: str                    # correct | wrong | missed | no_truth | both_absent
    rel_error: Optional[float] = None
    failure_kind: Optional[str] = None
    pred_idr: Optional[float] = None
    truth_idr: Optional[float] = None
    pred_raw: object = None
    confidence: Optional[float] = None
    grounded: Optional[bool] = None
    abstained: bool = False
    reasons: list = dataclass_field(default_factory=list)
    # What abstention threw away, and what it would have scored. `would_have_been` is
    # None when the withheld value was never recorded (a prediction cached before
    # src/extract.py started keeping it) -- unknown, and never assumed either way.
    withheld_idr: Optional[float] = None
    would_have_been: Optional[str] = None
    # Slice attributes, denormalised so a scorecard on disk is enough to compute metrics.
    currency: Optional[str] = None
    reporting_scale: Optional[str] = None
    text_layer: Optional[str] = None
    model: Optional[str] = None
    fx_rate: Optional[float] = None

    @property
    def labelled(self) -> bool:
        return self.status in ("correct", "wrong", "missed")

    def to_dict(self) -> dict:
        return asdict(self)


def score_period(ref: PeriodRef, pred, truth: dict, derived: "DerivedInputs",
                 rel_tol: float) -> list:
    """Every scored field of one filing, as Cells."""
    confidence = getattr(pred, "field_confidence", {}) or {}
    cells = []
    for name in EXCEL_ROWS:
        conf = confidence.get(name) or {}
        truth_idr = truth.get(name)
        pred_idr = derived.idr_values.get(name)
        status, error, kind = compare(pred_idr, truth_idr, rel_tol, conf.get("grounded"))

        withheld = derived.withheld_idr.get(name)
        would_have_been = None
        if conf.get("abstained") and withheld is not None and truth_idr is not None:
            would_have_been, _, _ = compare(withheld, truth_idr, rel_tol, conf.get("grounded"))

        cells.append(Cell(
            key=ref.key, ticker=ref.ticker, quarter=ref.quarter, year=ref.year,
            field=name, status=status, rel_error=error, failure_kind=kind,
            pred_idr=pred_idr, truth_idr=truth_idr, pred_raw=getattr(pred, name, None),
            confidence=conf.get("confidence"), grounded=conf.get("grounded"),
            abstained=bool(conf.get("abstained")), reasons=list(conf.get("reasons") or []),
            withheld_idr=withheld, would_have_been=would_have_been,
            currency=derived.currency, reporting_scale=derived.reporting_scale,
            text_layer=derived.text_layer, model=derived.model, fx_rate=derived.fx_rate))
    return cells


# --- the arithmetic between a prediction and a scored cell -----------------------

@dataclass
class DerivedInputs:
    """Everything scoring needs from the PDF, computed once and cached.

    Scoring used to re-open the filing on every run -- page selection, text extraction,
    the FX rate, the scale -- even when the prediction itself came from cache. On a
    filing whose text layer is glyph ids that is minutes of OCR per period, and it made
    a CI gate over cached predictions impossible.

    This is cached ARITHMETIC OVER THE MODEL'S OWN OUTPUT, not a second source of truth:
    refreshing it cannot change what the model said, only how that answer is converted.
    """
    idr_values: dict
    withheld_idr: dict
    fx_rate: Optional[float] = None
    currency: Optional[str] = None
    reporting_scale: Optional[str] = None
    text_layer: str = "unknown"          # clean | shredded | empty | unknown
    model: Optional[str] = None
    sha: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DerivedInputs":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        known.setdefault("idr_values", {})
        known.setdefault("withheld_idr", {})
        return cls(**known)


def conversion_sha() -> str:
    """Fingerprint of the code that turns a prediction into the compared figure.

    A cached `DerivedInputs` is only valid for the normalisation rules that produced it.
    When `src/normalize.py` changes, every cached conversion is stale and has to be
    refreshed -- and the alternative to noticing that is a scorecard that silently
    measures last week's arithmetic.
    """
    source = (Path(__file__).resolve().parent / "normalize.py").read_bytes()
    return hashlib.sha256(source).hexdigest()[:12]


def _text_layer_quality(pdf: Path, pages) -> str:
    from pdftext import page_texts, text_layer_shredded
    try:
        texts = page_texts(str(pdf), pages, use_ocr=False)
    except Exception:
        return "unknown"
    values = [t or "" for t in texts.values()]
    if not values or not any(v.strip() for v in values):
        return "empty"
    shredded = sum(1 for v in values if text_layer_shredded(v))
    return "shredded" if shredded >= max(1, len(values) // 2) else "clean"


def derive(pred, pdf: Path) -> DerivedInputs:
    """Read the filing and convert one prediction to full Rupiah. Costs no LLM call."""
    from extract import read_page_texts, build_document_text
    from normalize import extract_fx_rate, to_idr
    from page_select import select_statement_pages

    pages = select_statement_pages(str(pdf)).pages
    document_text = build_document_text(read_page_texts(str(pdf), pages))
    fx = extract_fx_rate(str(pdf))
    converted = to_idr(pred, pdf_path=str(pdf), document_text=document_text)["values"]

    # The same conversion applied to the figures abstention removed, so the eval can ask
    # what a withdrawal actually cost. Without this, "abstention precision" is not
    # measurable at all -- the withheld figure is gone by the time scoring sees it.
    confidence = getattr(pred, "field_confidence", {}) or {}
    withheld_raw = {name: (confidence.get(name) or {}).get("withheld_value")
                    for name in EXCEL_ROWS}
    withheld_idr = {}
    if any(v is not None for v in withheld_raw.values()):
        shadow = FinancialStatementExtraction.from_dict(pred.to_dict())
        for name, value in withheld_raw.items():
            if value is not None:
                setattr(shadow, name, value)
        shadow_values = to_idr(shadow, pdf_path=str(pdf),
                               document_text=document_text)["values"]
        withheld_idr = {name: shadow_values.get(name)
                        for name, value in withheld_raw.items() if value is not None}

    return DerivedInputs(
        idr_values=converted, withheld_idr=withheld_idr,
        fx_rate=fx.idr_per_usd if fx else None,
        currency=pred.currency, reporting_scale=pred.reporting_scale,
        text_layer=_text_layer_quality(pdf, pages),
        model=getattr(pred, "model", None), sha=conversion_sha())


def derive_from_cache(payload: dict) -> Optional[DerivedInputs]:
    """The cached conversion, or None when it is absent or stale.

    Stale means produced by a different `src/normalize.py`. Returning None sends the
    caller back to the PDF rather than letting a scorecard quietly report figures that
    the current code would convert differently.
    """
    data = (payload or {}).get("_derived")
    if not data:
        return None
    derived = DerivedInputs.from_dict(data)
    return derived if derived.sha == conversion_sha() else None


# --- cache paths ------------------------------------------------------------------

def cache_path_for(ref: PeriodRef, out_dir: Path, provider_tag: str) -> Path:
    return out_dir / "predictions" / provider_tag / f"{ref.cache_stem}.json"


def legacy_cache_path(ref: PeriodRef, out_dir: Path, provider_tag: str) -> Optional[Path]:
    """The old, un-yeared `<TICKER>_<Qn>.json`, but only when it is provably this period.

    The key it was written under could not tell 2022 from 2023, so it is accepted only
    when the payload's own `period_end_date` matches the period being scored. That makes
    the migration self-validating: it cannot repeat the collision it exists to fix.
    """
    path = out_dir / "predictions" / provider_tag / f"{ref.ticker}_{ref.quarter}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (ValueError, OSError):
        return None
    return path if payload.get("period_end_date") == ref.end_date else None
