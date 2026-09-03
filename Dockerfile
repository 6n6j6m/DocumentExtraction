# Extraction service.
#
# Two stages, for a reason that is not image size alone: the build stage carries the
# compilers that some wheels need, and none of that has any business being in a running
# service. What survives into the runtime layer is the installed packages plus three
# system dependencies that are genuinely needed at run time:
#
#   poppler-utils    pdf2image shells out to pdftoppm to render a page for the VLM
#   tesseract-ocr    the OCR path, reached when a filing's text layer is unreadable
#   ind + eng data   IDX filings are bilingual, so both language packs are required
#
# Leaving tesseract out would not break the build. It would break EMAS quietly: page
# selection would fall back to the first ten pages, grounding would verify nothing, and
# the exchange rate would come back "not disclosed" for a filing that discloses it on
# page 23. That failure is invisible until someone reads the numbers.

# ---- build -------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---- runtime -----------------------------------------------------------------
FROM python:3.11-slim

RUN apt-get update && apt-get install --no-install-recommends -y \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-ind \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config/ ./config/

# Data and output are mounted, not baked: the filings are the user's, and a scorecard
# written inside the container would be lost the moment it exits.
RUN mkdir -p /app/data /app/output && \
    useradd --create-home --uid 10001 extractor && \
    chown -R extractor:extractor /app
USER extractor

EXPOSE 8000

# httpx is already a dependency, so the healthcheck needs no curl in the image.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8000/health', timeout=4).status_code==200 else 1)"

CMD ["uvicorn", "api:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
