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


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
