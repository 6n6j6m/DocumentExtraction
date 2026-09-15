#!/usr/bin/env python3
"""
API contract tests. No network, no model, no API key.

The pipeline underneath is already covered by tests/test_guards.py; what is untested
until here is the transport: does a corrupt upload get refused rather than crashing the
extractor, does a provider outage become a 503 that names the provider, and does one
bad file in a batch cost the caller the other forty-nine results.

The provider is replaced with a stub that returns a fixed JSON payload, so these tests
say something about the API rather than about Gemini's mood.

Run:  python -m pytest tests/test_api.py -v
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient          # noqa: E402

import api                                          # noqa: E402
from llm import LLMUnavailable                      # noqa: E402

REAL_PDF = ROOT / "data" / "raw" / "Q1_2022_ARCI.pdf"

# What a well-behaved model returns for the balance-sheet group. Values are ARCI's, so
# grounding finds them in the real filing and the happy path exercises the confidence
# layer rather than bypassing it.
STUB_PAYLOAD = {
    "period_end_date": "2022-03-31",
    "aset": 694671337, "total_aset_lancar": 73325265, "kas": 23125502,
    "liabilitas": 452486029, "utang_bank_jangka_pendek": 34220811,
    "utang_bank_bagian_lancar": 68136673, "total_ekuitas": 242185308,
    "kepentingan_non_pengendali": -76732, "pendapatan": 80129305,
    "laba_bersih": 9450480, "kas_dari_aktivitas_operasi": 36388972,
    "total_share": 24835000000,
    "currency": "USD", "reporting_scale": "FULL", "statement_scope": "CONSOLIDATED",
}


class StubProvider:
    """Answers every call with the same payload, and counts the calls."""
    name = "stub:test-model"
    model = "test-model"
    input_mode = "text"

    def __init__(self, raises=None):
        self.raises = raises
        self.calls = 0

    def complete(self, system, user, images=None, usage=None):
        self.calls += 1
        if self.raises:
            raise self.raises
        if usage is not None:
            from usage import CallUsage
            usage.record(CallUsage("stub", self.model, 1000, 100, 5))
        return json.dumps(STUB_PAYLOAD)

    def list_models(self):
        return ["test-model"]


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose pipeline talks to the stub instead of a real provider."""
    provider = StubProvider()
    monkeypatch.setattr("extract.get_provider_chain", lambda: [provider])
    api.app.dependency_overrides[api.get_llm_provider] = lambda: provider
    with TestClient(api.app) as c:
        c.provider = provider
        yield c
    api.app.dependency_overrides.clear()


def _pdf_bytes():
    if not REAL_PDF.exists():
        pytest.skip(f"{REAL_PDF.name} not present")
    return REAL_PDF.read_bytes()


# --- contract -------------------------------------------------------------------

def test_health_is_shallow_by_default(client):
    """A polled endpoint must not spend a provider call to answer.

    The compose healthcheck hits this every few seconds; contacting the provider each
    time would cost thousands of calls a day to say "I am alive".
    """
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["checked"] == "shallow"
    assert body["provider_reachable"] is None


def test_health_deep_contacts_the_provider(client):
    body = client.get("/health", params={"deep": "true"}).json()
    assert body["checked"] == "deep"
    assert body["provider_reachable"] is True


def test_schema_is_generated_from_the_extractor_definitions(client):
    """Served, not hand-written, so the contract cannot drift from the code."""
    body = client.get("/schema").json()
    names = {f["name"] for f in body["fields"]}
    assert {"aset", "utang_bank", "total_share_components"} <= names
    assert "aset" in body["scored_fields"]
    # utang_bank is computed, and says so.
    derived = next(f for f in body["fields"] if f["name"] == "utang_bank")
    assert derived["derived_from"] == ["utang_bank_jangka_pendek",
                                       "utang_bank_bagian_lancar"]
    assert 0 < body["abstain_threshold"] < 1


def test_extract_returns_values_confidence_and_usage(client):
    response = client.post("/extract",
                           files={"file": ("Q1_2022_ARCI.pdf", _pdf_bytes(),
                                           "application/pdf")})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["extraction"]["aset"] == 694671337
    # Derived in code, not asked of the model.
    assert body["extraction"]["utang_bank"] == 34220811 + 68136673
    assert body["confidence"]["aset"]["grounded"] is True
    assert body["pages_selected"], "the pages the figures came from are part of the answer"
    assert body["usage"]["llm_calls"] == client.provider.calls
    assert body["usage"]["tokens"]["input"] > 0


def test_abstentions_are_reported_explicitly(client, monkeypatch):
    """A null because nothing was printed and a null because we did not trust what we
    read call for opposite responses, so the API distinguishes them."""
    payload = dict(STUB_PAYLOAD, kas=88888888)      # a figure not in the filing
    monkeypatch.setattr(StubProvider, "complete",
                        lambda self, s, u, images=None, usage=None: json.dumps(payload))
    body = client.post("/extract",
                       files={"file": ("f.pdf", _pdf_bytes(), "application/pdf")}).json()
    assert "kas" in body["abstained"]
    assert body["extraction"]["kas"] is None
    assert body["confidence"]["kas"]["abstained"] is True


def test_a_non_pdf_upload_is_refused_with_a_specific_message(client):
    """Checked by magic bytes, not by filename or content type -- the client controls
    both of those and neither says what the bytes are."""
    response = client.post("/extract",
                           files={"file": ("evil.pdf", b"not a pdf at all",
                                           "application/pdf")})
    assert response.status_code == 400
    assert "not a PDF" in response.json()["detail"]


def test_an_empty_upload_is_refused(client):
    response = client.post("/extract",
                           files={"file": ("empty.pdf", b"", "application/pdf")})
    assert response.status_code == 400


def test_provider_unavailable_is_503_and_names_the_provider(client, monkeypatch):
    """Not the caller's fault and not fixable by editing their file: they need to know
    to retry later, and which provider let them down."""
    def boom(self, s, u, images=None, usage=None):
        raise LLMUnavailable("Gemini rate limit (429)")
    monkeypatch.setattr(StubProvider, "complete", boom)

    response = client.post("/extract",
                           files={"file": ("f.pdf", _pdf_bytes(), "application/pdf")})
    assert response.status_code == 503
    assert "rate limit" in response.json()["detail"]


def test_batch_isolates_a_failing_document(client):
    """One corrupt PDF must not cost the caller the results for the others."""
    files = [
        ("files", ("good.pdf", _pdf_bytes(), "application/pdf")),
        ("files", ("broken.pdf", b"garbage", "application/pdf")),
        ("files", ("good2.pdf", _pdf_bytes(), "application/pdf")),
    ]
    response = client.post("/extract/batch", files=files)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["count"] == 3 and body["ok"] == 2 and body["failed"] == 1
    by_name = {item["filename"]: item for item in body["results"]}
    assert by_name["broken.pdf"]["status"] == "error"
    assert "not a PDF" in by_name["broken.pdf"]["error"]
    assert by_name["good.pdf"]["result"]["extraction"]["aset"] == 694671337
    assert body["usage"]["llm_calls"] > 0


def test_batch_refuses_more_files_than_the_limit(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_BATCH_FILES", 2)
    files = [("files", (f"f{i}.pdf", b"%PDF-1.4", "application/pdf")) for i in range(3)]
    response = client.post("/extract/batch", files=files)
    assert response.status_code == 413
    assert "exceeds the limit" in response.json()["detail"]


def test_uploads_are_not_kept(client):
    """A service that quietly accumulates other people's financial statements is a
    liability, not a feature."""
    import tempfile
    before = set(Path(tempfile.gettempdir()).glob("extract-*"))
    client.post("/extract", files={"file": ("f.pdf", _pdf_bytes(), "application/pdf")})
    after = set(Path(tempfile.gettempdir()).glob("extract-*"))
    assert after <= before


def test_a_throttled_model_hands_the_document_to_the_next(monkeypatch):
    """A rate-limited first model must not cost the document.

    The next provider in the chain takes the WHOLE document, and the result names it.
    Without that record, a CSV built during a throttled batch would mix two models'
    answers under nothing more than a filename.
    """
    import extract
    if not REAL_PDF.exists():
        pytest.skip(f"{REAL_PDF.name} not present")

    throttled = StubProvider(raises=LLMUnavailable("429 per-minute limit"))
    throttled.name = "stub:first-model"
    spare = StubProvider()
    spare.name = "stub:second-model"
    monkeypatch.setattr("extract.get_provider_chain", lambda: [throttled, spare])

    result = extract.extract_from_pdf(str(REAL_PDF))
    assert throttled.calls == 1, "the throttled model should be abandoned after one call"
    assert spare.calls >= 1
    assert result.model == "stub:second-model"
