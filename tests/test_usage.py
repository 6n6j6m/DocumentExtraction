#!/usr/bin/env python3
"""
Cost and type-validation guards.

Both exist for the same reason as everything in tests/test_guards.py: the machinery
is only observable when something is wrong. A cost report that silently invents a
number, and a schema that silently accepts a string where a figure belongs, both look
identical to a working system until the moment they matter.

Run:  python -m pytest tests/ -v
"""

import sys
from pathlib import Path

try:
    import pytest
except ImportError:                                   # pytest is optional here too
    class _Stub:
        class raises:
            def __init__(self, exc): self.exc = exc
            def __enter__(self): return self
            def __exit__(self, t, v, tb):
                if t is None: raise AssertionError(f"{self.exc.__name__} not raised")
                self.value = v
                return issubclass(t, self.exc)
    pytest = _Stub()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from schema import FinancialStatementExtraction as F, SchemaTypeError, FIELD_TYPES  # noqa: E402
from usage import Usage, CallUsage, load_pricing                                    # noqa: E402
from llm import _record                                                             # noqa: E402


# --- typed at the boundary ------------------------------------------------------

def test_every_field_has_a_declared_type():
    """A field added without a type would be silently unchecked."""
    assert set(F.__dataclass_fields__) == set(FIELD_TYPES)


def test_wrong_types_are_rejected_with_a_useful_message():
    """The old behaviour raised inside validate(), three frames from the cause.

    All offending fields are named at once: a malformed payload usually has more than
    one problem, and discovering them one round trip at a time is miserable.
    """
    with pytest.raises(SchemaTypeError) as excinfo:
        F.from_dict({"aset": "seratus", "currency": 123,
                     "total_share_components": {"a": 1}})
    message = str(excinfo.value)
    for field in ("aset", "currency", "total_share_components"):
        assert field in message, f"{field} missing from: {message}"
    assert "str" in message and "int" in message


def test_a_boolean_is_not_a_number():
    """bool subclasses int in Python, so `isinstance(True, int)` is True.

    Without an explicit check, `"aset": true` would be accepted and become 1.0 -- a
    figure, in the right units, that nothing downstream could tell was nonsense.
    """
    with pytest.raises(SchemaTypeError):
        F.from_dict({"aset": True})


def test_valid_payloads_still_pass_and_ints_become_floats():
    e = F.from_dict({"aset": 100, "kas": 12.5, "currency": "USD",
                     "total_share_components": [1, 2], "unknown_key": "ignored"})
    assert isinstance(e.aset, float) and e.aset == 100.0
    assert e.total_share_components == [1.0, 2.0]
    assert not hasattr(e, "unknown_key")


# --- usage accounting -----------------------------------------------------------

def _gemini_body(prompt, candidates):
    return {"usageMetadata": {"promptTokenCount": prompt,
                              "candidatesTokenCount": candidates}}


def test_gemini_token_counts_are_recorded_and_summed():
    usage = Usage()
    for body in (_gemini_body(1000, 200), _gemini_body(1500, 300)):
        _record(usage, "gemini", "gemini-3.1-flash-lite", body["usageMetadata"], 0.0,
                "promptTokenCount", "candidatesTokenCount")
    assert usage.llm_calls == 2
    assert usage.input_tokens == 2500
    assert usage.output_tokens == 500


def test_ollama_token_counts_use_its_own_field_names():
    usage = Usage()
    _record(usage, "ollama", "qwen2.5:7b-instruct",
            {"prompt_eval_count": 7700, "eval_count": 492}, 0.0,
            "prompt_eval_count", "eval_count")
    assert usage.input_tokens == 7700 and usage.output_tokens == 492


def test_a_provider_reporting_nothing_is_recorded_with_a_reason():
    """The call still happened. Dropping it would understate the work done, and
    guessing its size would misstate the spend."""
    usage = Usage()
    _record(usage, "gemini", "some-model", None, 0.0, "a", "b")
    assert usage.llm_calls == 1
    assert usage.input_tokens is None
    assert any("no token usage" in n for n in usage.notes)


def test_an_unpriced_model_reports_null_cost_and_says_why():
    """Never a guessed price. The tokens are still reported."""
    usage = Usage()
    usage.record(CallUsage("gemini", "unpriced-model", 1_000_000, 100_000))
    cost = usage.cost({"currency": "USD", "models": {}})
    assert cost["amount"] is None
    assert "unpriced-model" in cost["reason"]
    assert cost["per_model"][0]["input_tokens"] == 1_000_000


def test_a_priced_model_computes_from_the_configured_rate():
    usage = Usage()
    usage.record(CallUsage("gemini", "priced", 2_000_000, 500_000))
    cost = usage.cost({"currency": "USD", "models": {
        "priced": {"input_per_1m": 0.10, "output_per_1m": 0.40}}})
    # 2M in at 0.10/M = 0.20; 0.5M out at 0.40/M = 0.20
    assert cost["amount"] == 0.40
    assert cost["currency"] == "USD"


def test_local_models_are_priced_at_zero_rather_than_hidden():
    """A local run costs no money and the same tokens. Showing zero keeps a
    cloud-versus-local comparison honest; omitting it would read as missing data."""
    pricing = load_pricing(ROOT / "config" / "pricing.json")
    usage = Usage()
    usage.record(CallUsage("ollama", "qwen2.5:7b-instruct", 7700, 492))
    cost = usage.cost(pricing)
    assert cost["amount"] == 0
    assert cost["per_model"][0]["input_tokens"] == 7700


def test_a_broken_price_file_does_not_break_extraction():
    """Cost reporting is an accessory. It must degrade, not raise."""
    pricing = load_pricing("/nonexistent/pricing.json")
    assert pricing == {"currency": "USD", "models": {}}


def test_batch_totals_merge_per_document_usage():
    a, b = Usage(), Usage()
    a.record(CallUsage("gemini", "m", 100, 10))
    b.record(CallUsage("gemini", "m", 200, 20))
    a.merge(b)
    assert a.llm_calls == 2 and a.input_tokens == 300


def test_stage_timing_is_recorded_separately():
    usage = Usage()
    with usage.stage("select_pages"):
        pass
    with usage.stage("extract"):
        pass
    assert set(usage.stages) == {"select_pages", "extract"}




# --- transient upstream failures -------------------------------------------------

class _Response:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


_OK = {"candidates": [{"content": {"parts": [{"text": '{"aset": 1}'}]}}],
       "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2}}


@pytest.fixture(autouse=True)
def _fresh_cooldown_ledger(monkeypatch):
    """The rotation ledger is process-wide on purpose, so a test must not inherit a rest
    that an earlier test earned -- that is exactly how one test's 429 once reordered
    another test's provider chain."""
    import llm
    monkeypatch.setattr(llm, "_COOLDOWN_UNTIL", {})
    # Likewise the patience settings: .env names patient models, and a test that did not
    # ask for them must not inherit them.
    for name in ("GEMINI_PATIENT_MODELS", "GEMINI_PATIENT_RETRIES",
                 "GEMINI_PATIENT_RATE_LIMIT_RETRIES", "GEMINI_PATIENT_BACKOFF_S"):
        monkeypatch.delenv(name, raising=False)


def _gemini(monkeypatch, statuses, error_body=None):
    """A GeminiProvider whose HTTP calls return `statuses` in order."""
    import llm
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_RETRY_BACKOFF_S", "0")      # no real sleeping in tests
    monkeypatch.setenv("LLM_RATE_LIMIT_WAIT_S", "0.01")
    calls = []

    def fake_post(url, **kwargs):
        status = statuses[len(calls)] if len(calls) < len(statuses) else statuses[-1]
        calls.append(status)
        if status == 200:
            return _Response(200, _OK)
        return _Response(status, error_body or {"error": {"code": status}})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    return llm.GeminiProvider(), calls


def test_a_capacity_503_is_retried_once_and_recovers(monkeypatch):
    """Observed, not hypothetical: a 503 "high demand" spike cost a real run one field.

    The model could read the page perfectly well; the service was briefly
    oversubscribed and said so. One more attempt is the proportionate answer.
    """
    provider, calls = _gemini(monkeypatch, [503, 200])
    assert provider.complete("sys", "user") == '{"aset": 1}'
    assert calls == [503, 200], "should have tried again after the 503"


def test_a_per_minute_rate_limit_is_waited_out(monkeypatch):
    """A requests-per-minute bucket refills on a clock, so waiting IS the fix.

    This test replaces one that asserted the opposite. The earlier reasoning -- that
    retrying a throttle deepens it -- holds for a daily cap and fails for a per-minute
    one, and treating them alike made a long batch die on a limit that would have
    cleared itself in about a minute.
    """
    provider, calls = _gemini(monkeypatch, [429, 200])
    assert provider.complete("sys", "user") == '{"aset": 1}'
    assert calls == [429, 200], "should have waited out the window and tried again"


def test_a_daily_quota_is_not_waited_out(monkeypatch):
    """The other half of the distinction: sleeping a minute cannot clear a daily cap.

    Waiting there buys nothing but a slower failure, so the caller is told immediately
    and can fall back to another provider or stop for the day.
    """
    from llm import LLMUnavailable
    provider, calls = _gemini(monkeypatch, [429, 200],
                              error_body={"error": {"code": 429, "message":
                                          "Quota exceeded: GenerateRequestsPerDay"}})
    with pytest.raises(LLMUnavailable):
        provider.complete("sys", "user")
    assert calls == [429], "a daily cap must fail fast, not sleep"


def test_the_cooldown_is_never_shorter_than_configured(monkeypatch):
    """The provider's retryDelay can lengthen the cooldown, never shorten it.

    Gemini sometimes answers "retry in 20s". Trusting that alone retries before the
    per-minute window has reset and buys a second 429, so the configured cooldown is a
    floor. A longer hint is still honoured, with a margin, because the provider knows
    when its bucket refills.
    """
    from llm import _rate_limit_wait
    assert _rate_limit_wait('"retryDelay": "20s" PerMinute', 70) == 70
    assert _rate_limit_wait('"retryDelay": "90s" PerMinute', 70) == 95.0
    assert _rate_limit_wait("per minute quota exceeded", 70) == 70
    assert _rate_limit_wait("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 70) is None
    # Both exhausted: the day's cap decides it. A minute's sleep ends in the same 429.
    assert _rate_limit_wait("GenerateRequestsPerMinute ... GenerateRequestsPerDay", 70) is None


def test_other_gemini_models_are_tried_before_the_local_one(monkeypatch):
    """Gemini counts limits per model, so a second model is the cheaper next step.

    Order is GEMINI_MODEL, then GEMINI_FALLBACK_MODELS, then LLM_FALLBACK_PROVIDER.
    Every Gemini model but the last hands over on a 429 without cooling down -- sleeping
    a minute while a model with spare quota is one call away waits for nothing. The last
    keeps its cooldown, because what follows it is slower still.
    """
    import llm
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    # The primary repeated, and a trailing comma: both must be tolerated.
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite, gemini-3.1-flash-lite,")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_INPUT_MODE", "text")      # image mode probes the server
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3-vl:8b")
    monkeypatch.setenv("LLM_RATE_LIMIT_WAIT_S", "70")

    chain = llm.get_provider_chain()
    assert [p.name for p in chain] == ["gemini:gemini-3.1-flash-lite",
                                       "gemini:gemini-3.5-flash-lite",
                                       "ollama:qwen3-vl:8b"]
    assert chain[0].rate_limit_wait == 0, "a model with a fallback must not cool down"
    assert chain[1].rate_limit_wait == 70, "the last Gemini model keeps its cooldown"
    assert chain[0].hands_over and not chain[1].hands_over

    # With no Gemini fallback, the primary is the last Gemini model and cools down.
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    chain = llm.get_provider_chain()
    assert [p.name for p in chain] == ["gemini:gemini-3.1-flash-lite", "ollama:qwen3-vl:8b"]
    assert chain[0].rate_limit_wait == 70


def test_a_throttled_model_hands_over_without_cooling_down(monkeypatch):
    """With another model waiting, a 429 is reported after one call, not after a minute."""
    from llm import LLMUnavailable
    provider, calls = _gemini(monkeypatch, [429, 200])
    provider.rate_limit_wait = 0          # what get_provider_chain sets for a non-last model
    provider.hands_over = True
    with pytest.raises(LLMUnavailable, match="handing over to the next model"):
        provider.complete("sys", "user")
    assert calls == [429]


def test_exhausted_capacity_hands_over_only_when_a_model_is_next(monkeypatch):
    """A 503 that outlives its retry moves the document on -- if there is somewhere to go.

    As a plain LLMError it was swallowed per statement group: the overloaded model kept
    the document and one statement's fields silently went missing. With another model
    next, it must hand over. As the last model, losing a group still beats losing the
    whole document, so it stays an ordinary error there.
    """
    import llm
    monkeypatch.setattr(llm, "_COOLDOWN_UNTIL", {})
    provider, calls = _gemini(monkeypatch, [503, 503, 503])
    provider.hands_over = True
    with pytest.raises(llm.LLMUnavailable, match="capacity"):
        provider.complete("sys", "user")
    assert llm.cooling_down(provider.model), "an overloaded model should rest"

    last, _ = _gemini(monkeypatch, [503, 503, 503])
    with pytest.raises(llm.LLMError) as caught:
        last.complete("sys", "user")
    assert not isinstance(caught.value, llm.LLMUnavailable)


def test_a_resting_model_moves_to_the_back_of_the_rotation(monkeypatch):
    """The chain is rebuilt per document, so it must remember who is resting.

    Otherwise every document asks the throttled model first and pays a wasted 429 to
    learn what the previous document already knew.
    """
    import llm
    monkeypatch.setattr(llm, "_COOLDOWN_UNTIL", {})
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-3.6-flash,gemini-3.7-flash")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "")
    monkeypatch.setenv("LLM_RATE_LIMIT_WAIT_S", "70")

    names = lambda chain: [p.model for p in chain]
    assert names(llm.get_provider_chain()) == [
        "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-3.7-flash"]

    llm._cool("gemini-3.1-flash-lite", 60)
    chain = llm.get_provider_chain()
    assert names(chain) == ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.1-flash-lite"]
    assert chain[0].hands_over and chain[1].hands_over
    assert not chain[2].hands_over and chain[2].rate_limit_wait == 70, \
        "the model resting last is still tried, with its cooldown"

    # A 429 that hands over is what puts a model in the ledger in the first place.
    monkeypatch.setattr(llm, "_COOLDOWN_UNTIL", {})
    provider, _ = _gemini(monkeypatch, [429])
    provider.hands_over = True
    provider.rate_limit_wait = 0
    with pytest.raises(llm.LLMUnavailable):
        provider.complete("sys", "user")
    assert llm.cooling_down(provider.model)


def test_a_model_that_times_out_hands_the_document_over(monkeypatch):
    """A read timeout is a model not answering, and must move the document on.

    It used to escape as a raw requests exception, which the image path swallows per
    statement group: gemini-3.7-flash timed out at 120 s on the balance sheet, then again
    on the income statement, losing both and never reaching gemini-3.8-flash.
    """
    import llm
    import requests as real_requests
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_RETRY_BACKOFF_S", "0")
    calls = []

    def timing_out(url, **kwargs):
        calls.append(url)
        raise real_requests.exceptions.ReadTimeout("Read timed out. (read timeout=120)")

    monkeypatch.setattr(llm.requests, "post", timing_out)

    provider = llm.GeminiProvider(model="gemini-3.7-flash")
    provider.hands_over = True
    with pytest.raises(llm.LLMUnavailable, match="handing over"):
        provider.complete("sys", "user")
    assert len(calls) == provider.max_retries + 1, "one retry, then hand over"
    assert llm.cooling_down("gemini-3.7-flash")

    # The last model has nowhere to hand over to: an ordinary error, as for a 503.
    calls.clear()
    last = llm.GeminiProvider(model="gemini-3.8-flash")
    with pytest.raises(llm.LLMError) as caught:
        last.complete("sys", "user")
    assert not isinstance(caught.value, llm.LLMUnavailable)


def test_patient_models_wait_and_retry_before_handing_over(monkeypatch):
    """The cheap models at the front of the queue should be tried harder than the rest.

    Handing over at once sends the document to a model that costs three times as much
    and answers several times slower. A patient model waits out a per-minute limit and
    retries capacity errors first; only then does it hand over. Everyone else keeps
    handing over at once, and a daily quota never waits.
    """
    import llm
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite,gemini-3.6-flash,gemini-3.8-flash")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "")
    monkeypatch.setenv("LLM_RATE_LIMIT_WAIT_S", "70")
    monkeypatch.setenv("GEMINI_PATIENT_MODELS", "gemini-3.1-flash-lite, gemini-3.5-flash-lite")
    monkeypatch.setenv("GEMINI_PATIENT_RETRIES", "3")
    monkeypatch.setenv("GEMINI_PATIENT_RATE_LIMIT_RETRIES", "2")

    chain = {p.model: p for p in llm.get_provider_chain()}
    for model in ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite"):
        p = chain[model]
        assert p.hands_over, "patient, but still hands over in the end"
        assert p.rate_limit_wait == 70 and p.rate_limit_retries == 2 and p.max_retries == 3
    assert chain["gemini-3.6-flash"].rate_limit_wait == 0, "the rest still hand over at once"

    # Behaviour: three 503s then success -- the patient model recovers without handing over.
    provider, calls = _gemini(monkeypatch, [503, 503, 503, 200])
    provider.hands_over, provider.max_retries, provider.retry_backoff = True, 3, 0
    assert provider.complete("sys", "user") == '{"aset": 1}'
    assert calls == [503, 503, 503, 200]

    # Two per-minute 429s are waited out, then it answers.
    provider, calls = _gemini(monkeypatch, [429, 429, 200])
    provider.hands_over, provider.rate_limit_retries = True, 2
    assert provider.complete("sys", "user") == '{"aset": 1}'
    assert calls == [429, 429, 200]

    # A daily quota is never waited for, however patient the model.
    provider, calls = _gemini(monkeypatch, [429, 200],
                              error_body={"error": {"code": 429, "message": "GenerateRequestsPerDay"}})
    provider.hands_over, provider.rate_limit_retries = True, 2
    with pytest.raises(llm.LLMUnavailable, match="daily"):
        provider.complete("sys", "user")
    assert calls == [429]


def test_retries_are_bounded(monkeypatch):
    """A provider that is genuinely down must be discovered quickly, not stalled on."""
    from llm import LLMError
    provider, calls = _gemini(monkeypatch, [503, 503, 503])
    with pytest.raises(LLMError):
        provider.complete("sys", "user")
    assert len(calls) == provider.max_retries + 1 == 2





def test_the_eval_scores_cached_predictions_without_a_provider(monkeypatch, tmp_path):
    """A reviewer with no API key must still be able to reproduce the scorecard.

    Every prediction is committed, and scoring them calls no model -- so refusing to
    start without a provider denied a reviewer the one thing they could check for free.
    It used to raise LLMUnavailable out of main() as a traceback.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "scripts" / "run_eval.py")
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)

    import json
    import shutil

    # The prediction cache lives under the output directory, so pointing --out at a
    # temp dir moves the cache with it. Copy it across, or the run "passes" by failing
    # every period and finding nothing wrong in an empty tally.
    shutil.copytree(ROOT / "output" / "predictions", tmp_path / "predictions")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # Pin the model to the one the committed cache was produced with. Without this the
    # test reads whichever model .env happens to name, misses the cache, and tries to
    # call a provider it has just been denied -- failing for a reason that has nothing
    # to do with what it is testing.
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("GEMINI_INPUT_MODE", "image")
    monkeypatch.setattr("sys.argv", ["run_eval", "--periods", "Q1", "--out", str(tmp_path)])

    assert run_eval.main() == 0
    written = list(tmp_path.glob("scorecard_*.json"))
    assert written, "a scorecard should have been written from the cache"

    report = json.loads(written[0].read_text())
    assert report["summary"]["correct"] == 10, "all ten scored fields should be read"
    assert "error" not in report["periods"]["Q1"], "the period must have scored, not failed"


def test_no_cache_without_a_provider_refuses_clearly(monkeypatch, tmp_path, capsys):
    """--no-cache needs a model. Saying so beats a traceback from three frames down."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "scripts" / "run_eval.py")
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # llm.py loads .env itself, so deleting the variable is not enough to simulate a
    # machine without a key -- the file would put it straight back on the next import.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr("sys.argv",
                        ["run_eval", "--no-cache", "--periods", "Q1", "--out", str(tmp_path)])

    assert run_eval.main() == 2          # could not run, distinct from "found errors"
    assert "needs a working provider" in capsys.readouterr().out


if __name__ == "__main__":
    # Kept at the very BOTTOM on purpose: this block runs the moment the interpreter
    # reaches it, so any test defined after it would never be collected.
    import inspect

    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = skipped = 0
    for name, fn in tests:
        if inspect.signature(fn).parameters:
            # Needs a pytest fixture (monkeypatch). Runnable under pytest only.
            skipped += 1
            print(f"  SKIP  {name}  (needs pytest fixtures)")
            continue
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed - skipped}/{len(tests) - skipped} passed"
          f"{f', {skipped} skipped' if skipped else ''}")
    raise SystemExit(1 if failed else 0)
