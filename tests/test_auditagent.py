#!/usr/bin/env python3
"""
The label-audit agent, broken on purpose.

What must hold for its output to mean anything: the reading is blind to the labels; a
citation that does not check out is fed back and never counted; a verdict of "the label
is wrong" stands only on a verified figure; the auditor refuses to be the model it
audits; each call stays small however long the conversation runs; a spent daily quota
stops the run instead of failing every remaining filing.

A scripted provider plays the model, as in tests/test_agent.py. No network, no key.

Run:  python -m pytest tests/test_auditagent.py -v
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import auditagent                                                  # noqa: E402
import llm                                                         # noqa: E402
from agenttools import AgentBudget, ToolContext, run_tool          # noqa: E402
from auditagent import (AuditConfigError, AuditState, QuotaExhausted,   # noqa: E402
                        TokenPacer, adjudicate_filing, check_independence, compact,
                        read_filing)
from labelaudit import AUDIT_FIELDS, PageSource                    # noqa: E402
from llm import AssistantTurn, LLMUnavailable, ToolCall            # noqa: E402
from usage import CallUsage                                        # noqa: E402

FILLER = "Catatan atas laporan keuangan konsolidasian yang merupakan bagian. " * 4
HEADER = "LAPORAN POSISI KEUANGAN (Dinyatakan dalam Rupiah)\n30 Juni 2024 31 Desember 2023"
PAGES = {
    4: f"{HEADER}\nTotal aset 7.777.777.777 6.666.666.666\n{FILLER}",
    5: f"{HEADER}\nPendapatan 3.333.333.333 2.222.222.222\n{FILLER}",
}
LABEL = 9_191_919_191          # a value printed nowhere, so a leak would be visible


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(llm, "_COOLDOWN_UNTIL", {})
    monkeypatch.setattr(auditagent, "AUDIT_MAX_CALL_TOKENS", 60_000)


def _turn(*calls):
    return AssistantTurn(tool_calls=[ToolCall(n, a) for n, a in calls],
                         raw={"role": "model", "parts": [
                             {"functionCall": {"name": n, "args": a}} for n, a in calls]})


class Scripted:
    supports_tools = True

    def __init__(self, script, name="stub:auditor", raises=None):
        self.script, self.name, self.model = list(script), name, name.split(":")[-1]
        self.raises, self.seen = raises, []

    def complete_with_tools(self, system, contents, tools, usage=None):
        self.seen.append(json.loads(json.dumps(contents)))
        if self.raises:
            raise self.raises
        if usage is not None:
            usage.record(CallUsage("stub", self.model, 500, 20, 1))
        return self.script.pop(0) if self.script else _turn(("finish", {"reason": "done"}))


def _state(pages=None, total=40):
    texts = dict(pages or PAGES)
    ctx = ToolContext(pdf_path="/nonexistent.pdf", total_pages=total)
    ctx.texts = {n: texts.get(n, FILLER) for n in range(total)}
    ctx.titles = dict(ctx.texts)
    return AuditState(ticker="TEST", quarter="Q2", year=2024, ctx=ctx,
                      source=PageSource(texts=texts, tables={}))


def _evidence(field, value, page, header="30 Juni 2024"):
    return {"field": field, "printed_value": value, "page": page,
            "row_label": field, "column_header": header,
            "scale": "FULL", "currency": "IDR"}


# --- blind, and self-correcting ------------------------------------------------------

def test_the_reading_never_sees_the_label_and_is_told_what_failed():
    provider = Scripted([
        _turn(("report_evidence", {"items": [_evidence("aset", "7.777.777.778", 5)]})),
        _turn(("report_evidence", {"items": [_evidence("aset", "7.777.777.777", 5)]})),
        _turn(("finish", {"reason": "done", "not_found": ["kas"]})),
    ])
    state = _state()
    record = read_filing(state, budget=AgentBudget(max_steps=10), chain=[provider])

    transcripts = json.dumps(provider.seen)
    assert "9191919191" not in transcripts and "9.191.919.191" not in transcripts
    # The mistyped citation came back as a problem the agent could read ...
    assert "is not printed on page 5" in json.dumps(provider.seen[1])
    # ... and the corrected report is the one kept.
    assert record["evidence"]["aset"]["verified"] is True
    assert record["evidence"]["aset"]["value"] == 7_777_777_777
    assert record["trajectory"]["not_found"] == ["kas"]


def test_naming_the_comparative_column_is_fed_back_as_the_wrong_period():
    provider = Scripted([_turn(("report_evidence", {"items": [
        _evidence("aset", "6.666.666.666", 5, header="31 Desember 2023")]}))])
    state = _state()
    record = read_filing(state, budget=AgentBudget(max_steps=4), chain=[provider])
    assert record["evidence"]["aset"]["verified"] is False
    assert "is not the Q2 2024 period" in json.dumps(provider.seen[1])


def test_the_reading_stops_by_itself_once_every_field_is_verified():
    pages = {4: HEADER + "\n" + "\n".join(f"Baris {i} {i + 1}.111.111.111 9.999.999"
                                            for i in range(10)) + "\n" + FILLER}
    items = [_evidence(f, f"{i + 1}.111.111.111", 5) for i, f in enumerate(AUDIT_FIELDS)]
    provider = Scripted([_turn(("report_evidence", {"items": items}))] +
                        [_turn(("list_pages", {}))] * 5)
    state = _state(pages)
    record = read_filing(state, budget=AgentBudget(max_steps=10), chain=[provider])
    assert record["stop_reason"] == "all_fields_verified"
    assert len(provider.seen) == 1, "no call is spent after the job is done"


# --- verdicts stand on evidence -----------------------------------------------------------

def _dispute_state():
    state = _state()
    from labelaudit import evidence_from_args, verify_evidence
    ev = evidence_from_args(_evidence("aset", "7.777.777.777", 5))
    state.evidence = {"aset": verify_evidence(ev, state.source, "Q2", 2024)}
    return state


def test_label_wrong_is_accepted_only_on_a_citation_that_checks_out(monkeypatch):
    monkeypatch.setattr("agenttools.find_number",
                        lambda ctx, args: type("R", (), {"payload": {"hits": []}})())
    provider = Scripted([_turn(("report_verdict", {"items": [
        {"field": "aset", "verdict": "label_wrong", "cause": "period_shift",
         "explanation": "the label is printed nowhere in this filing",
         **{k: v for k, v in _evidence("aset", "7.777.777.777", 5).items() if k != "field"}}]}))])
    state = _dispute_state()
    state.rate = lambda: None
    result = adjudicate_filing(state, {"aset": LABEL}, budget=AgentBudget(max_steps=4),
                               chain=[provider])
    verdict = result["verdicts"]["aset"]
    assert verdict["status"] == "label_wrong" and verdict["proposed_value"] == 7_777_777_777
    # The model WAS shown the label in this phase -- that is the point of it.
    assert "9.191.919.191" in json.dumps(provider.seen[0])


def test_label_wrong_on_a_figure_not_on_the_page_goes_to_a_person(monkeypatch):
    monkeypatch.setattr("agenttools.find_number",
                        lambda ctx, args: type("R", (), {"payload": {"hits": []}})())
    provider = Scripted([_turn(("report_verdict", {"items": [
        {"field": "aset", "verdict": "label_wrong", "cause": "other", "explanation": "x",
         **{k: v for k, v in _evidence("aset", "1.234.567.890", 5).items() if k != "field"}}]}))])
    state = _dispute_state()
    state.rate = lambda: None
    result = adjudicate_filing(state, {"aset": LABEL}, budget=AgentBudget(max_steps=4),
                               chain=[provider])
    assert result["verdicts"]["aset"]["status"] == "needs_human"


def test_conceding_the_label_is_right_is_recorded_as_such(monkeypatch):
    monkeypatch.setattr("agenttools.find_number",
                        lambda ctx, args: type("R", (), {"payload": {"hits": []}})())
    provider = Scripted([_turn(("report_verdict", {"items": [
        {"field": "aset", "verdict": "auditor_wrong", "cause": "other",
         "explanation": "I read the wrong line"}]}))])
    state = _dispute_state()
    state.rate = lambda: None
    result = adjudicate_filing(state, {"aset": LABEL}, budget=AgentBudget(max_steps=4),
                               chain=[provider])
    assert result["verdicts"]["aset"]["status"] == "label_confirmed_on_review"


# --- independence --------------------------------------------------------------------------

def test_the_auditor_refuses_to_be_the_model_it_audits(monkeypatch):
    monkeypatch.setenv("AUDIT_EVALUATED_MODELS", "gemini-3.1-flash-lite")
    with pytest.raises(AuditConfigError):
        check_independence(["gemini-3.8-flash", "gemini-3.1-flash-lite"])
    check_independence(["gemini-3.8-flash", "gemini-3.7-flash"])


# --- running out ---------------------------------------------------------------------------

def test_each_call_stays_small_however_many_pages_are_read():
    """Every call re-sends the transcript. Without compaction, ten page reads make the
    tenth call carry all ten pages; with it, only the last two."""
    big = {n: f"{HEADER}\n" + "\n".join(f"Baris {i} {n}.{i:03d}.111.111" for i in range(200))
           + "\n" + FILLER for n in range(12)}
    provider = Scripted([_turn(("read_page", {"page": n + 1})) for n in range(10)])
    state = _state(big, total=12)
    record = read_filing(state, budget=AgentBudget(max_steps=11, max_text_pages=30),
                         chain=[provider])
    calls = record["trajectory"]["call_tokens_estimated"]
    assert record["trajectory"]["compactions"] > 0
    assert max(calls[4:]) < 2 * calls[3], f"call size kept growing: {calls}"
    last = json.dumps(provider.seen[-1])
    assert last.count('"compacted"') >= 6


def test_compaction_keeps_every_function_response_paired_with_its_call():
    contents = [{"role": "user", "parts": [{"text": "go"}]}]
    for n in range(4):
        contents.append({"role": "model", "parts": [{"functionCall": {"name": "read_page",
                                                                        "args": {"page": n}}}]})
        contents.append({"role": "user", "parts": [
            {"functionResponse": {"name": "read_page",
                                  "response": {"result": {"page": n, "text": "x" * 5000}}}},
            {"inline_data": {"mime_type": "image/png", "data": "AAAA"}}]})
    compact(contents, keep_last=1)
    responses = [p for t in contents for p in t["parts"] if "functionResponse" in p]
    assert len(responses) == 4
    assert all("compacted" in r["functionResponse"]["response"]["result"]
               for r in responses[:3])
    assert "text" in responses[3]["functionResponse"]["response"]["result"]
    assert sum(1 for t in contents for p in t["parts"] if "inline_data" in p) == 1


def test_the_pacer_waits_rather_than_passing_the_per_minute_limit():
    now = [0.0]
    slept = []
    pacer = TokenPacer(tpm_limit=100_000, clock=lambda: now[0],
                       sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    pacer.record(80_000)
    now[0] = 10.0
    pacer.wait_for(30_000)
    assert slept and now[0] >= 60.0, "waited for the first call to leave the window"
    slept.clear()
    pacer.wait_for(30_000)
    assert not slept


def test_a_spent_daily_quota_stops_the_run_instead_of_failing_each_filing():
    daily = LLMUnavailable("Gemini rate limit (429) on m: daily quota (RPD) used up")
    chain = [Scripted([], name="stub:a", raises=daily),
             Scripted([], name="stub:b", raises=daily)]
    with pytest.raises(QuotaExhausted):
        read_filing(_state(), budget=AgentBudget(max_steps=4), chain=chain)


def test_a_per_minute_limit_hands_over_and_keeps_what_was_verified():
    first = Scripted([_turn(("report_evidence", {"items": [_evidence("aset", "7.777.777.777", 5)]}))])
    first_calls = []

    def flaky(system, contents, tools, usage=None):
        first_calls.append(1)
        if len(first_calls) > 1:
            raise LLMUnavailable("per-minute limit (RPM/TPM); handing over")
        return Scripted.complete_with_tools(first, system, contents, tools, usage)

    first.complete_with_tools = flaky
    second = Scripted([_turn(("finish", {"reason": "done"}))], name="stub:second")
    record = read_filing(_state(), budget=AgentBudget(max_steps=6), chain=[first, second])
    assert record["evidence"]["aset"]["verified"]
    assert "Already verified: aset" in json.dumps(second.seen[0])
    assert record["trajectory"]["handovers"]


# --- the deterministic search -----------------------------------------------------------------

def test_find_number_finds_a_full_rupiah_figure_printed_in_thousands():
    ctx = ToolContext(pdf_path="/x.pdf", total_pages=2)
    ctx.texts = {0: "Dalam ribuan Rupiah\nTotal aset 7.777.778 6.000.000", 1: ""}
    result = run_tool(ctx, "find_number", {"value": 7_777_777_777})
    assert result.error_kind is None
    assert result.payload["hits"][0]["scale"] == "THOUSANDS"
    assert result.payload["hits"][0]["page"] == 1
