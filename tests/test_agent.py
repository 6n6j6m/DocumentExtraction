#!/usr/bin/env python3
"""
The agent loop, broken on purpose.

An agent fails differently from a pipeline: it asks for a page that does not exist, it
calls a tool that was never defined, it talks instead of acting, it runs out of budget
halfway, it gets rate-limited at step five of fourteen. None of those may lose the
document, and each of them has a test here.

Two fakes, both already idioms in this repo: a scripted provider object for the loop
(as `tests/test_api.py` fakes a provider), and a fake `requests.post` for the transport
(as `tests/test_usage.py` fakes the HTTP layer). No network, no key, no model.

Run:  python -m pytest tests/test_agent.py -v
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import llm                                                        # noqa: E402
from agenttools import AgentBudget                                # noqa: E402
from llm import AssistantTurn, LLMUnavailable, ToolCall           # noqa: E402
from usage import CallUsage, Usage                                # noqa: E402

import agent                                                      # noqa: E402

ARCI = ROOT / "data" / "raw" / "Q1_2022_ARCI.pdf"


@pytest.fixture(autouse=True)
def _fresh_cooldown_ledger(monkeypatch):
    """The cooldown ledger is process-wide and .env is read at import."""
    monkeypatch.setattr(llm, "_COOLDOWN_UNTIL", {})
    for name in ("GEMINI_PATIENT_MODELS", "GEMINI_PATIENT_RETRIES",
                 "GEMINI_PATIENT_RATE_LIMIT_RETRIES", "GEMINI_PATIENT_BACKOFF_S"):
        monkeypatch.delenv(name, raising=False)


# --- the fakes --------------------------------------------------------------------

def _calls(*calls) -> AssistantTurn:
    return AssistantTurn(tool_calls=[ToolCall(name=n, args=a) for n, a in calls],
                         raw={"role": "model", "parts": [
                             {"functionCall": {"name": n, "args": a}} for n, a in calls]})


def _report(group, **fields) -> AssistantTurn:
    return _calls((f"report_{group}", fields))


def _finish(reason="done") -> AssistantTurn:
    return _calls(("finish", {"reason": reason}))


class ScriptedToolProvider:
    """Plays a fixed script of model turns, and keeps every transcript it was handed."""
    input_mode = "text"
    supports_tools = True

    def __init__(self, script, name="stub:agent-model", raises_at=None):
        self.script = list(script)
        self.name = name
        self.model = name.split(":")[-1]
        self.raises_at = raises_at
        self.seen = []

    def complete_with_tools(self, system, contents, tools, usage=None):
        self.seen.append(json.loads(json.dumps(contents)))
        if self.raises_at == len(self.seen):
            raise LLMUnavailable("scripted rate limit")
        if usage is not None:
            usage.record(CallUsage("stub", self.model, 1000, 50, 5))
        return self.script.pop(0) if self.script else _finish("script exhausted")


def _ctx(monkeypatch, provider, pages=40, patch_document=True):
    """Run the loop over a fake document, with no PDF and no model.

    Pages are padded past MIN_TEXT_CHARS because build_document_text drops anything
    shorter, and a grounding check against an empty document returns "unverifiable"
    rather than "not found" -- which would quietly make the abstention test pass for
    the wrong reason.
    """
    from agenttools import ToolContext
    filler = ("Catatan atas laporan keuangan konsolidasian. " * 8)
    texts = {n: f"PAGE {n + 1}\nTotal aset 1.111.111\n{filler}" for n in range(pages)}

    def fake_for_pdf(pdf_path):
        context = ToolContext(pdf_path=pdf_path, total_pages=pages)
        context.texts, context.titles = texts, dict(texts)
        return context

    monkeypatch.setattr(agent, "get_provider_chain",
                        lambda: provider if isinstance(provider, list) else [provider])
    if patch_document:
        monkeypatch.setattr(agent.ToolContext, "for_pdf", staticmethod(fake_for_pdf))
        # Grounding needs the page text; the fake document has no PDF behind it.
        monkeypatch.setattr("pdftext.page_texts",
                            lambda path, pages=None, use_ocr=True:
                            {n: texts.get(n, "") for n in (pages or texts)})


ALL_FOUR = [_report("balance_sheet", aset=1111111, pages=[1]),
            _report("income", pendapatan=1111111, pages=[2]),
            _report("cash_flow", kas_dari_aktivitas_operasi=1111111, pages=[3]),
            _report("share_capital", total_share=1111111, pages=[4])]


# --- the loop ---------------------------------------------------------------------

def test_the_loop_stops_when_every_group_has_been_reported(monkeypatch):
    """Four statements is the whole job; a fifth turn would be spending for nothing."""
    provider = ScriptedToolProvider(ALL_FOUR + [_finish()])
    _ctx(monkeypatch, provider)
    usage = Usage()

    result = agent.extract_agentic("fake.pdf", usage=usage)

    assert result.agent_trajectory["stop_reason"] == "all_groups"
    assert len(provider.seen) == 4, "no turn is spent after the last group lands"
    assert usage.llm_calls == 4
    assert {"step_1", "step_4"} <= set(usage.stages)


def test_a_step_budget_returns_what_it_has_and_says_so(monkeypatch):
    """A partial result is information. An exception is a harness error."""
    forever = [_calls(("read_page_text", {"page": 3}))] * 20
    provider = ScriptedToolProvider([ALL_FOUR[0]] + forever)
    _ctx(monkeypatch, provider)

    result = agent.extract_agentic("fake.pdf", budget=AgentBudget(max_steps=4))

    trajectory = result.agent_trajectory
    assert trajectory["stop_reason"] == "step_budget" and trajectory["budget_exhausted"]
    assert len(trajectory["steps"]) == 4
    assert result.aset == 1111111, "the group that did land is kept"
    # derive_fields ran on the partial, exactly as it does for the pipeline.
    assert result.saham_ditempatkan is None and result.budget_exhausted


def test_a_malformed_tool_argument_is_fed_back_rather_than_raised(monkeypatch):
    provider = ScriptedToolProvider([_calls(("read_page_text", {"page": "five"}))] + ALL_FOUR)
    _ctx(monkeypatch, provider)

    result = agent.extract_agentic("fake.pdf")

    errors = result.agent_trajectory["tool_errors"]
    assert errors and errors[0]["kind"] == "malformed_args"
    # The model saw the message on its next turn, in a functionResponse.
    second_turn = provider.seen[1]
    payload = second_turn[-1]["parts"][0]["functionResponse"]["response"]["result"]
    assert "whole number" in payload["error"]
    assert result.agent_trajectory["stop_reason"] == "all_groups", "the loop continued"


def test_an_unknown_tool_is_answered_with_the_ones_that_exist(monkeypatch):
    provider = ScriptedToolProvider([_calls(("read_pdf", {}))] + ALL_FOUR)
    _ctx(monkeypatch, provider)

    result = agent.extract_agentic("fake.pdf")

    assert result.agent_trajectory["tool_errors"][0]["kind"] == "unknown_tool"
    payload = provider.seen[1][-1]["parts"][0]["functionResponse"]["response"]["result"]
    assert "read_page_text" in payload["available"]


def test_a_page_outside_the_document_is_refused_with_its_range(monkeypatch):
    provider = ScriptedToolProvider([_calls(("read_page_text", {"page": 300}))] + ALL_FOUR)
    _ctx(monkeypatch, provider, pages=40)

    result = agent.extract_agentic("fake.pdf")

    error = result.agent_trajectory["tool_errors"][0]
    assert error["kind"] == "page_out_of_range" and "(1-40)" in error["message"]


def test_fields_outside_a_statement_are_dropped_with_a_warning(monkeypatch):
    """report_income cannot answer for the balance sheet, and says so without failing."""
    provider = ScriptedToolProvider(
        [_report("income", pendapatan=1111111, aset=999, pages=[2])] + ALL_FOUR)
    _ctx(monkeypatch, provider)

    result = agent.extract_agentic("fake.pdf")

    kinds = [e["kind"] for e in result.agent_trajectory["tool_errors"]]
    assert "bad_field_name" in kinds
    payload = provider.seen[1][-1]["parts"][0]["functionResponse"]["response"]["result"]
    assert "aset" in payload["warning"]


def test_talking_instead_of_acting_is_nudged_once_then_stopped(monkeypatch):
    """A model that will not drive the tools must not be paid to keep explaining."""
    silence = AssistantTurn(tool_calls=[], text="I will now examine the filing.",
                            raw={"role": "model", "parts": [{"text": "..."}]})
    provider = ScriptedToolProvider([ALL_FOUR[0], silence, silence, ALL_FOUR[1]])
    _ctx(monkeypatch, provider)

    result = agent.extract_agentic("fake.pdf")

    assert result.agent_trajectory["stop_reason"] == "no_tool_call"
    assert result.agent_trajectory["no_tool_call_turns"] == 2
    assert len(provider.seen) == 3, "one nudge, not an infinite politeness loop"


def test_unavailable_mid_loop_hands_over_and_keeps_what_was_reported(monkeypatch):
    """Fourteen turns is fourteen chances to be throttled. The findings carry; the budget does not."""
    first = ScriptedToolProvider([ALL_FOUR[0]], name="stub:a", raises_at=2)
    second = ScriptedToolProvider(ALL_FOUR[1:] + [_finish()], name="stub:b")
    _ctx(monkeypatch, [first, second])

    result = agent.extract_agentic("fake.pdf", budget=AgentBudget(max_steps=10))

    trajectory = result.agent_trajectory
    assert len(trajectory["handovers"]) == 1
    assert trajectory["providers"] == ["stub:a", "stub:b"]
    assert result.model == "agent:stub:a>stub:b"
    opening = second.seen[0][0]["parts"][0]["text"]
    assert "already reported: balance_sheet" in opening
    assert "9 steps left" in opening, "the budget is not refreshed by a hand-over"
    assert result.aset == 1111111, "the first model's work survived"


def test_every_provider_unavailable_raises_the_string_the_api_maps_to_503(monkeypatch):
    dead = ScriptedToolProvider([], name="stub:dead", raises_at=1)
    _ctx(monkeypatch, [dead])

    with pytest.raises(LLMUnavailable) as caught:
        agent.extract_agentic("fake.pdf")
    assert str(caught.value).startswith("no provider was available")


def test_a_provider_that_cannot_use_tools_is_skipped_with_a_reason(monkeypatch):
    class NoTools:
        name, model, input_mode, supports_tools = "ollama:qwen", "qwen", "text", False
    provider = ScriptedToolProvider(ALL_FOUR + [_finish()], name="stub:b")
    _ctx(monkeypatch, [NoTools(), provider])

    result = agent.extract_agentic("fake.pdf")

    handover = result.agent_trajectory["handovers"][0]
    assert handover["provider"] == "ollama:qwen"
    assert "does not support tool calling" in handover["reason"]
    assert result.model == "agent:stub:b"


def test_a_figure_from_a_page_the_agent_never_read_is_withdrawn(monkeypatch):
    """Grounding checks the pages the agent NAMED, which makes its citation testable."""
    provider = ScriptedToolProvider(
        [_report("balance_sheet", aset=987654321, currency="IDR", pages=[1]), _finish()])
    _ctx(monkeypatch, provider)

    result = agent.extract_agentic("fake.pdf")

    assert result.aset is None, "987.654.321 is printed on no page it cited"
    assert result.field_confidence["aset"]["abstained"] is True


# --- the transport ----------------------------------------------------------------

class _Response:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


def _gemini_tools(monkeypatch, payloads):
    """A GeminiProvider whose posts return `payloads` in order; captures the bodies."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_RETRY_BACKOFF_S", "0")
    monkeypatch.setenv("LLM_RATE_LIMIT_WAIT_S", "0.01")
    bodies = []

    def fake_post(url, **kwargs):
        bodies.append(kwargs.get("json"))
        item = payloads[min(len(bodies) - 1, len(payloads) - 1)]
        return _Response(*item) if isinstance(item, tuple) else _Response(200, item)

    monkeypatch.setattr(llm.requests, "post", fake_post)
    return llm.GeminiProvider(), bodies


_CALL_TURN = {"candidates": [{"content": {"parts": [
    {"functionCall": {"name": "read_page_text", "args": {"page": 5}}}]}}],
    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2}}


def test_the_tool_request_drops_response_mime_type_and_carries_roles(monkeypatch):
    """responseMimeType and tools are mutually exclusive; sending both is a 400 that
    reads like a schema error. This is the most likely first failure of the whole branch."""
    provider, bodies = _gemini_tools(monkeypatch, [_CALL_TURN])

    provider.complete_with_tools("system text",
                                 [{"role": "user", "parts": [{"text": "go"}]}],
                                 [{"name": "read_page_text", "parameters": {}}])

    body = bodies[0]
    assert "responseMimeType" not in body["generationConfig"]
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "read_page_text"
    assert body["systemInstruction"]["parts"][0]["text"] == "system text"
    assert all("role" in entry for entry in body["contents"])


def test_a_function_call_part_is_parsed_rather_than_key_erroring(monkeypatch):
    """The old reader indexed straight into parts[0]["text"]."""
    provider, _ = _gemini_tools(monkeypatch, [_CALL_TURN])

    turn = provider.complete_with_tools("s", [{"role": "user", "parts": []}], [])

    assert [(c.name, c.args) for c in turn.tool_calls] == [("read_page_text", {"page": 5})]
    assert turn.raw["role"] == "model"


def test_a_turn_with_no_parts_is_a_silent_turn_not_a_crash(monkeypatch):
    """finishReason MAX_TOKENS or SAFETY returns a candidate with no content at all."""
    provider, _ = _gemini_tools(monkeypatch, [{"candidates": [{"finishReason": "MAX_TOKENS"}]}])

    turn = provider.complete_with_tools("s", [{"role": "user", "parts": []}], [])

    assert turn.tool_calls == [] and turn.text is None
    assert turn.finish_reason == "MAX_TOKENS"


def test_each_turn_records_its_own_usage(monkeypatch):
    provider, _ = _gemini_tools(monkeypatch, [_CALL_TURN])
    usage = Usage()

    for _ in range(3):
        provider.complete_with_tools("s", [{"role": "user", "parts": []}], [], usage=usage)

    assert usage.llm_calls == 3 and usage.input_tokens == 30


def test_a_daily_429_in_the_tool_path_still_cools_the_model_down(monkeypatch):
    """The tool method goes through the same transport, or the resilience layer is a lie."""
    body = {"error": {"code": 429, "message": "quota exceeded",
                      "details": [{"violations": [{"quotaId": "PerDay"}]}]}}
    provider, _ = _gemini_tools(monkeypatch, [(429, body)])

    with pytest.raises(LLMUnavailable):
        provider.complete_with_tools("s", [{"role": "user", "parts": []}], [])
    assert llm.cooling_down(provider.model), "a daily cap must rest the model"


def test_complete_still_returns_a_string_after_the_refactor(monkeypatch):
    text_turn = {"candidates": [{"content": {"parts": [{"text": '{"aset": 1}'}]}}],
                 "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2}}
    provider, bodies = _gemini_tools(monkeypatch, [text_turn])

    assert provider.complete("sys", "user") == '{"aset": 1}'
    assert bodies[0]["generationConfig"]["responseMimeType"] == "application/json"
    assert "tools" not in bodies[0]


# --- the harness seam -------------------------------------------------------------

def _run_eval():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "run_eval", ROOT / "scripts" / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_agent_cache_can_never_overwrite_the_pipelines():
    """Two implementations on one model are two experiments.

    Without the suffix the agent's predictions land in the pipeline's cache directory
    and its scorecard overwrites the baseline -- and the comparison meant to settle the
    question becomes a run compared with itself, which is the exact failure the input
    mode and the _api suffix are already in this name to prevent.
    """
    from evalkit import PeriodRef, cache_path_for
    run_eval = _run_eval()

    class _P:
        name, input_mode = "gemini:gemini-3.1-flash-lite", "image"

    pipeline = run_eval.provider_tag_for(_P(), extractor="pipeline")
    agentic = run_eval.provider_tag_for(_P(), extractor="agentic")
    assert pipeline == "gemini_gemini-3.1-flash-lite_image"
    assert agentic == pipeline + "_agentic"
    assert run_eval.provider_tag_for(_P(), api_url="http://x", extractor="agentic") \
        == pipeline + "_api_agentic"

    ref = PeriodRef("ARCI", "Q1", 2022, Path("x.pdf"))
    assert cache_path_for(ref, Path("out"), pipeline).parent != \
        cache_path_for(ref, Path("out"), agentic).parent


def test_a_trajectory_survives_the_prediction_cache(monkeypatch, tmp_path):
    """A re-scored agent run must not silently lose every agent metric."""
    import evalmetrics
    run_eval = _run_eval()
    trajectory = {"schema": 1, "steps_used": 3, "steps": [{"i": 1, "tool": "list_pages"}],
                  "tool_errors": [], "tool_counts": {"list_pages": 1},
                  "pages_opened_text": [1, 2], "pages_rendered_image": [],
                  "groups_reported": ["income"], "stop_reason": "finished",
                  "handovers": [], "budget_exhausted": False, "no_tool_call_turns": 0}

    from schema import FinancialStatementExtraction
    def fake_agent(path, usage=None):
        result = FinancialStatementExtraction(aset=1.0)
        result.agent_trajectory = trajectory
        result.model = "agent:stub"
        return result

    monkeypatch.setitem(sys.modules, "agent", type(sys)("agent"))
    sys.modules["agent"].extract_agentic = fake_agent
    cache = tmp_path / "ARCI_Q1_2022.json"

    fresh, cached, _ = run_eval.predict(Path("x.pdf"), cache, use_cache=True,
                                        extractor="agentic")
    assert cached is False and fresh.agent_trajectory["steps_used"] == 3
    assert json.loads(cache.read_text())["_agent"]["stop_reason"] == "finished"

    again, cached, _ = run_eval.predict(Path("x.pdf"), cache, use_cache=True,
                                        extractor="agentic")
    assert cached is True, "the second call reads the cache"
    assert again.agent_trajectory["steps_used"] == 3, "and the trajectory came back"
    assert evalmetrics.agent_behaviour([again.agent_trajectory])["filings"] == 1


def test_metrics_without_a_trajectory_are_exactly_what_they_were():
    """Every committed scorecard and every pipeline run must be unaffected."""
    import evalmetrics
    keys = set(evalmetrics.summarise([], []))
    assert "agent" not in keys and "page_agreement" not in keys
    assert set(evalmetrics.summarise([], [], [None, None])) == keys


def test_agent_metrics_skip_filings_that_recorded_nothing():
    """A filing with no trajectory is unmeasured, not efficient."""
    import evalmetrics
    trajectory = {"steps_used": 4, "steps": [{"tool": "list_pages"}],
                  "tool_errors": [], "tool_counts": {}, "pages_opened_text": [],
                  "pages_rendered_image": [], "groups_reported": [],
                  "stop_reason": "finished", "handovers": [], "budget_exhausted": False,
                  "no_tool_call_turns": 0}
    behaviour = evalmetrics.agent_behaviour([trajectory, None, trajectory])
    assert behaviour["filings"] == 2


def test_page_agreement_is_only_computed_where_the_selector_was_recorded():
    """It compares the agent with the selector -- not with the truth, and the report
    says so. Filings the backfill has not reached are excluded rather than assumed."""
    import evalmetrics
    with_pages = {"key": "ARCI Q1 2022", "pages_reported": {"balance_sheet": [4, 5]},
                  "deterministic_pages": [4, 5, 6]}
    without = {"key": "ARCI Q2 2022", "pages_reported": {"balance_sheet": [4]},
               "deterministic_pages": None}
    agreement = evalmetrics.page_selection_agreement([with_pages, without])
    assert agreement["filings"] == 1
    assert agreement["precision"] == 1.0            # both its pages are the selector's
    assert agreement["recall"] == pytest.approx(2 / 3)
    assert agreement["pages_only_the_selector_chose"][0]["pages"] == [6]


# --- the one that matters most ----------------------------------------------------

@pytest.mark.skipif(not ARCI.exists(), reason="Q1_2022_ARCI.pdf not present")
def test_the_agent_result_is_interchangeable_with_the_pipelines(monkeypatch):
    """Both paths must be scoreable by the same code.

    If they are not, a comparison between them compares two harnesses rather than two
    extractors, and every number in the experiment means something else.
    """
    from evalkit import PeriodRef, derive, score_period
    from schema import EXCEL_ROWS

    agentic = ScriptedToolProvider([
        _report("balance_sheet", aset=694671337, currency="USD",
                reporting_scale="FULL", pages=[5]),
        _finish()])
    # The real filing this time: `derive` reads the disclosed exchange rate off it, and a
    # fake document would make the interchangeability check pass without conversion.
    _ctx(monkeypatch, agentic, patch_document=False)
    from_agent = agent.extract_agentic(str(ARCI), usage=Usage())

    assert set(from_agent.to_dict()) == set(__import__("schema")
                                            .FinancialStatementExtraction().to_dict())
    for attribute in ("usage", "pages_selected", "model", "field_confidence"):
        assert getattr(from_agent, attribute, None) is not None
    assert from_agent.model.startswith("agent:"), "the model slice separates the two"

    ref = PeriodRef(ticker="ARCI", quarter="Q1", year=2022, pdf=ARCI)
    truth = {name: 1.0 for name in EXCEL_ROWS}
    cells = score_period(ref, from_agent, truth, derive(from_agent, ARCI), 1e-4)
    assert [c.field for c in cells] == list(EXCEL_ROWS)
    assert all(c.model.startswith("agent:") for c in cells)


if __name__ == "__main__":
    print("needs pytest fixtures; run: python -m pytest tests/test_agent.py -v")
