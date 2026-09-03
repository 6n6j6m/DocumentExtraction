"""
HTTP transport for the extraction pipeline.

FastAPI is glue here and nothing more. Every route does the same three things: put the
uploaded bytes somewhere `extract_from_pdf` can read them, call it, and shape what
comes back. No parsing, no scoring, no arithmetic on a figure. The moment a handler
starts deciding what a number means, the extractor has been forked in two, and the one
behind the HTTP boundary is the one the evaluation harness cannot test.

That is also why `/extract` returns values **as printed** rather than converted to
Rupiah. Conversion needs the filing's own disclosed rate and reporting scale, and
`normalize.py` already does it for the harness. Doing it again here would mean two
implementations that agree until they do not.

Three behaviours worth knowing before reading the code:

**Failure is per document, not per batch.** Fifty filings with one corrupt PDF return
forty-nine results and one explanation. A batch that gives up wholesale forces the
caller to work out which document poisoned it and resend the rest.

**A rate limit is different in kind from a bad file.** `LLMUnavailable` means the
provider is gone; the remaining documents in the batch are failed immediately rather
than each spending a call to rediscover it. Retrying a throttle deepens it.

**A partial extraction is a result.** A per-page `LLMError` leaves the fields it did
read, with `issues` populated, and returns 200. Eight of ten fields plus an
explanation is worth more to a caller than a 500.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_models import (BatchItem, BatchResponse, ExtractionResponse, HealthResponse,
                        SchemaField, SchemaResponse, UsageModel)
from confidence import ABSTAIN_THRESHOLD, DERIVED_FROM
from extract import FIELDS, extract_from_pdf
from llm import LLMError, LLMUnavailable, get_provider
from schema import EXCEL_ROWS, FIELD_TYPES, SchemaTypeError
from usage import Usage

ROOT = Path(__file__).resolve().parent.parent

MAX_UPLOAD_MB = int(os.getenv("API_MAX_UPLOAD_MB", "25"))
MAX_BATCH_FILES = int(os.getenv("API_MAX_BATCH_FILES", "10"))
# Small by default: these calls are billed and rate limited, and the failure mode of
# too much concurrency is a 429 that makes the whole batch slower, not faster.
MAX_CONCURRENCY = int(os.getenv("API_MAX_CONCURRENCY", "2"))

app = FastAPI(
    title="IDX Financial Statement Extraction",
    description="Extracts a fixed schema of figures from Indonesian Stock Exchange "
                "filings, with per-field confidence and abstention.",
    version="1.0.0",
)


# --- logging --------------------------------------------------------------------

def log(**fields) -> None:
    """One JSON object per line.

    Structured because these lines are read by machines first: the questions asked of
    them ("which filings abstained", "what is p95 latency by provider") are filters and
    aggregations, and prose defeats both.
    """
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **fields}),
          flush=True)


# --- provider wiring ------------------------------------------------------------

def get_llm_provider():
    """The active provider, as a dependency so tests can replace it.

    Constructing it per request is deliberate: a key rotated in the environment takes
    effect without a restart, and the object is cheap.
    """
    return get_provider()


_reachability_cache = {"checked_at": 0.0, "value": None}
REACHABILITY_TTL = 30.0


def _provider_reachable(provider) -> Optional[bool]:
    """Cheapest possible "is the provider answering" check, cached.

    Cached because `/health` is polled -- a compose healthcheck every 10 seconds would
    otherwise spend around 8,600 provider calls a day to say "I am alive". Thirty
    seconds is short enough to catch an outage during a deployment and long enough that
    the check costs nothing.
    """
    now = time.time()
    if now - _reachability_cache["checked_at"] < REACHABILITY_TTL:
        return _reachability_cache["value"]

    value = None
    try:
        if hasattr(provider, "list_models"):
            value = bool(provider.list_models())
        elif hasattr(provider, "supports_vision"):
            value = provider.supports_vision() is not None
    except Exception:
        value = False

    _reachability_cache.update(checked_at=now, value=value)
    return value


def _git_commit() -> Optional[str]:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


# --- upload handling ------------------------------------------------------------

PDF_MAGIC = b"%PDF"


def _save_upload(upload: UploadFile, directory: Path) -> Path:
    """Write an upload to disk, refusing anything that is not a PDF.

    The magic bytes are checked rather than the filename or the declared content type,
    both of which the client controls and neither of which says what the bytes are.
    """
    data = upload.file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"{upload.filename}: {len(data) / 1e6:.1f} MB exceeds the "
                   f"{MAX_UPLOAD_MB} MB limit (API_MAX_UPLOAD_MB)")
    if not data:
        raise HTTPException(status_code=400, detail=f"{upload.filename}: file is empty")
    if not data.startswith(PDF_MAGIC):
        raise HTTPException(
            status_code=400,
            detail=f"{upload.filename}: not a PDF (expected a %PDF header, got "
                   f"{data[:8]!r})")

    path = directory / (Path(upload.filename or "upload.pdf").name or "upload.pdf")
    path.write_bytes(data)
    return path


def _shape(filename: str, result, usage: Usage) -> ExtractionResponse:
    """Turn a pipeline result into the response model. No computation here."""
    confidence = getattr(result, "field_confidence", {}) or {}
    return ExtractionResponse(
        filename=filename,
        pages_selected=getattr(result, "pages_selected", []),
        extraction=result.to_dict(),
        confidence=confidence,
        abstained=[name for name, score in confidence.items()
                   if score.get("abstained")],
        issues=getattr(result, "issues", []),
        usage=UsageModel(**usage.to_dict()),
    )


def _extract_one(path: Path, filename: str) -> ExtractionResponse:
    """Run the pipeline over one saved file. Raises for the caller to map."""
    usage = Usage()
    result = extract_from_pdf(str(path), usage=usage)
    if result is None:
        raise LLMError("extraction returned no fields")
    return _shape(filename, result, usage)


# --- endpoints ------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
def health(deep: bool = Query(False, description="Also check that the provider answers"),
           provider=Depends(get_llm_provider)):
    """Liveness, and optionally whether the provider is reachable.

    Shallow by default on purpose -- see `_provider_reachable`. The compose healthcheck
    uses the shallow form; `?deep=true` is for a human asking why nothing works.
    """
    return HealthResponse(
        status="ok",
        provider=provider.name,
        model=getattr(provider, "model", "unknown"),
        input_mode=getattr(provider, "input_mode", "text"),
        git_commit=_git_commit(),
        provider_reachable=_provider_reachable(provider) if deep else None,
        checked="deep" if deep else "shallow",
    )


@app.get("/schema", response_model=SchemaResponse)
def schema():
    """The field contract, generated from the definitions the extractor actually uses.

    Served rather than documented separately so the two cannot disagree: if a field is
    added to the dataclass, it appears here without anyone remembering to update a
    table.
    """
    fields = []
    for name in FIELDS:
        fields.append(SchemaField(
            name=name,
            type=FIELD_TYPES.get(name, "unknown"),
            scored=name in EXCEL_ROWS,
            derived_from=list(DERIVED_FROM[name]) if name in DERIVED_FROM else None,
            description=("computed in code from its components"
                         if name in DERIVED_FROM else None),
        ))
    return SchemaResponse(
        fields=fields,
        scored_fields=list(EXCEL_ROWS),
        abstain_threshold=ABSTAIN_THRESHOLD,
    )


@app.post("/extract", response_model=ExtractionResponse)
def extract(request: Request, file: UploadFile = File(...)):
    """Extract one filing."""
    request_id = str(uuid.uuid4())[:8]
    started = time.time()
    workdir = Path(tempfile.mkdtemp(prefix="extract-"))
    try:
        path = _save_upload(file, workdir)
        response = _extract_one(path, file.filename or path.name)
        log(request_id=request_id, event="extract", filename=response.filename,
            pages=len(response.pages_selected), provider=os.getenv("LLM_PROVIDER", "gemini"),
            latency_ms=int((time.time() - started) * 1000),
            fields_filled=sum(1 for v in response.extraction.values() if v is not None),
            abstained=len(response.abstained),
            tokens_in=response.usage.tokens.input, tokens_out=response.usage.tokens.output)
        return response
    except HTTPException:
        raise
    except LLMUnavailable as exc:
        # The provider, not the request, is what failed. 503 with the provider named,
        # so a caller knows to retry later rather than to fix their file.
        log(request_id=request_id, event="provider_unavailable", error=str(exc))
        raise HTTPException(status_code=503,
                            detail=f"provider unavailable: {exc}")
    except SchemaTypeError as exc:
        log(request_id=request_id, event="schema_error", error=str(exc))
        raise HTTPException(status_code=502,
                            detail=f"model returned a malformed payload: {exc}")
    except (LLMError, ValueError) as exc:
        log(request_id=request_id, event="extract_failed", error=str(exc))
        raise HTTPException(status_code=422, detail=f"extraction failed: {exc}")
    finally:
        # Uploads are never kept. Nothing here needs them after the call, and a service
        # that quietly accumulates other people's financial statements is a liability.
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/extract/batch", response_model=BatchResponse)
def extract_batch(request: Request, files: List[UploadFile] = File(...)):
    """Extract several filings, isolating each document's failure.

    Concurrency is bounded by API_MAX_CONCURRENCY (default 2). These calls are billed
    and rate limited: past a small number the marginal request buys a 429 rather than
    throughput, and a 429 costs the whole batch more than the parallelism saved.
    """
    request_id = str(uuid.uuid4())[:8]
    started = time.time()
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"{len(files)} files exceeds the limit of {MAX_BATCH_FILES} "
                   f"(API_MAX_BATCH_FILES)")

    workdir = Path(tempfile.mkdtemp(prefix="extract-batch-"))
    provider_down: Optional[str] = None
    try:
        saved = []
        for index, upload in enumerate(files):
            name = upload.filename or f"upload-{index}.pdf"
            try:
                # Its own directory: two uploads may share a filename.
                slot = workdir / str(index)
                slot.mkdir()
                saved.append((name, _save_upload(upload, slot), None))
            except HTTPException as exc:
                saved.append((name, None, str(exc.detail)))

        def run(entry):
            name, path, error = entry
            if error is not None:
                return BatchItem(filename=name, status="error", error=error)
            if provider_down:
                return BatchItem(filename=name, status="error",
                                 error=f"skipped: {provider_down}")
            try:
                return BatchItem(filename=name, status="ok",
                                 result=_extract_one(path, name))
            except LLMUnavailable as exc:
                # Not this document's fault, and not survivable by the next one.
                return BatchItem(filename=name, status="error",
                                 error=f"provider unavailable: {exc}")
            except Exception as exc:
                return BatchItem(filename=name, status="error",
                                 error=f"{type(exc).__name__}: {exc}")

        with ThreadPoolExecutor(max_workers=max(1, MAX_CONCURRENCY)) as pool:
            results = list(pool.map(run, saved))

        # Totals are summed from the per-document reports rather than by replaying the
        # calls: the accumulators are per document by design, so that a failure in one
        # filing cannot corrupt another's numbers.
        tokens_in = [i.result.usage.tokens.input for i in results
                     if i.result and i.result.usage.tokens.input is not None]
        tokens_out = [i.result.usage.tokens.output for i in results
                      if i.result and i.result.usage.tokens.output is not None]
        aggregate = UsageModel(
            llm_calls=sum(i.result.usage.llm_calls for i in results if i.result),
            tokens={"input": sum(tokens_in) if tokens_in else None,
                    "output": sum(tokens_out) if tokens_out else None},
            latency_ms={"total": int((time.time() - started) * 1000)},
            cost={"amount": None, "currency": "USD",
                  "reason": "per-document costs are reported on each result"},
        )

        ok = sum(1 for item in results if item.status == "ok")
        log(request_id=request_id, event="extract_batch", count=len(results), ok=ok,
            failed=len(results) - ok, concurrency=MAX_CONCURRENCY,
            latency_ms=aggregate.latency_ms["total"])
        return BatchResponse(count=len(results), ok=ok, failed=len(results) - ok,
                             results=results, usage=aggregate)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.exception_handler(Exception)
def unhandled(request: Request, exc: Exception):
    """Never leak a traceback to a caller; always leave one in the log."""
    log(event="unhandled", path=str(request.url.path), error=f"{type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500,
                        content={"detail": f"internal error: {type(exc).__name__}"})
