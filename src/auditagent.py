#!/usr/bin/env python3
"""
An agent that audits the ground truth by reading the filings again.

Two conversations per filing, deliberately separate:

**Read (blind).** The agent is told the issuer, the period and the ten field definitions
-- never the labels. It finds the statements, reads them as tables whose columns are
named by the dates the page prints, and cites every figure with its page, row and column.
`labelaudit.verify_evidence` checks each citation against the page geometry before it
counts, and tells the agent what failed so it can correct itself on the next turn. A
reader that has been shown the expected answer finds it; this one cannot.

Because the reading does not depend on the labels, it is paid for ONCE per filing and
compared for free against any version of them -- the working tree, HEAD, or a copy with
errors planted on purpose to score the auditor.

**Adjudicate (informed).** Only for cells where a verified reading disagrees with the
label. The agent is shown the label, its own reading, the pipeline's answer, and every
place the label's figure is printed across the issuer's filings, and must decide which
side is wrong and why. A `label_wrong` verdict counts only if the corrected figure passes
the same page checks; otherwise it goes to a person.

**Running out.** Each step re-sends the whole transcript, so the cost of a step grows
with everything read before it. Three things keep that bounded, and one stops cleanly
when it cannot be:

  * compaction   page text older than the last two tool turns is replaced by a note
                 saying it was read. Findings live in report_evidence, not in history.
  * call cap     a call estimated above AUDIT_MAX_CALL_TOKENS is compacted harder first.
  * pacer        tokens sent in the last 60 s are counted, and a call that would pass
                 AUDIT_TPM_LIMIT waits. Respecting the quota, not working around it.
  * daily quota  when every audit model is resting on a per-day 429, QuotaExhausted is
                 raised; the driver stops, and the next run resumes from the cache.
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import llm
from agenttools import (MAX_PAGES_PER_READ, AgentBudget, ToolContext, ToolResult,
                        _page_index, navigation_schemas, run_tool)
from labelaudit import (AUDIT_FIELDS, Evidence, PageSource, evidence_from_args, feedback,
                        verify_evidence)
from llm import GeminiProvider, LLMError, LLMUnavailable
from prompts import AUDIT_ADJUDICATE_PROMPT, AUDIT_READ_PROMPT
from schema import EXCEL_ROWS

AUDIT_MODEL = os.getenv("AUDIT_MODEL", "gemini-3.8-flash")
AUDIT_FALLBACK_MODELS = os.getenv("AUDIT_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.6-flash")
AUDIT_TPM_LIMIT = int(os.getenv("AUDIT_TPM_LIMIT", "0"))            # 0 = no pacing
AUDIT_MAX_CALL_TOKENS = int(os.getenv("AUDIT_MAX_CALL_TOKENS", "60000"))
KEEP_RECENT_TOOL_TURNS = 2
PAGE_CHARS = 9_000                    # a rebuilt table is wider than condensed text
IMAGE_TOKENS = 1_100                  # a rendered page, conservatively
MAX_NO_TOOL_TURNS = 2
BULKY_TOOLS = {"read_page", "read_page_image", "list_pages"}
VERDICTS = ["label_wrong", "auditor_wrong", "ambiguous_definition"]
CAUSES = ["comparative_column", "period_shift", "double_count", "stale_value", "scale",
          "wrong_subtotal", "other"]
MONTHS_ID = {"Q1": "31 Maret", "Q2": "30 Juni", "Q3": "30 September", "Q4": "31 Desember"}


def audit_budget() -> AgentBudget:
    return AgentBudget(max_steps=int(os.getenv("AUDIT_MAX_STEPS", "20")),
                       max_images=int(os.getenv("AUDIT_MAX_IMAGES", "6")),
                       max_text_pages=int(os.getenv("AUDIT_MAX_TEXT_PAGES", "30")),
                       max_input_tokens=int(os.getenv("AUDIT_MAX_INPUT_TOKENS", "250000")),
                       max_seconds=int(os.getenv("AUDIT_MAX_SECONDS", "1200")))


class AuditConfigError(RuntimeError):
    """The audit would not be independent of the thing it audits."""


class QuotaExhausted(RuntimeError):
    """Every audit model has used its daily quota. Stop; the next run resumes."""


# --- who audits -----------------------------------------------------------------------

def audit_models() -> list:
    models = []
    for m in [AUDIT_MODEL] + AUDIT_FALLBACK_MODELS.split(","):
        m = m.strip()
        if m and m not in models:
            models.append(m)
    return models


def check_independence(models: Optional[list] = None) -> None:
    """Refuse to audit labels with the model whose output the labels are scored against.

    The rule in `.claude/skills/label-groundtruth`: never let the model under evaluation
    write, or check, its own ground truth. A fallback counts -- a chain that quietly
    handed over to the evaluated model would audit with it for every filing after the
    first rate limit.
    """
    evaluated = {m.strip() for m in os.getenv("AUDIT_EVALUATED_MODELS",
                                              os.getenv("GEMINI_MODEL", "")).split(",")
                 if m.strip()}
    clash = [m for m in (models or audit_models()) if m in evaluated]
    if clash:
        raise AuditConfigError(
            f"{', '.join(clash)} is the model being evaluated (GEMINI_MODEL / "
            f"AUDIT_EVALUATED_MODELS); an audit by it would check the labels against "
            f"itself. Set AUDIT_MODEL and AUDIT_FALLBACK_MODELS to other models.")


def audit_chain() -> list:
    """The audit models as providers, resting ones last, like get_provider_chain."""
    models = audit_models()
    check_independence(models)
    chain = [GeminiProvider(model=m) for m in models]
    ready = [p for p in chain if not llm.cooling_down(p.model)]
    resting = sorted((p for p in chain if llm.cooling_down(p.model)),
                     key=lambda p: llm._COOLDOWN_UNTIL[p.model])
    chain = ready + resting
    for provider in chain[:-1]:
        provider.rate_limit_wait = 0
        provider.hands_over = True
    # Patience on capacity. A 503 "high demand" on every flash model at once was the
    # first thing the pilot met; one 2-second retry gave up a nine-step reading on a
    # dropped connection. An audit is a batch nobody is waiting on, so it retries
    # longer before handing a filing over and losing its conversation.
    for provider in chain:
        provider.max_retries = int(os.getenv("AUDIT_RETRIES", "4"))
        provider.retry_backoff = float(os.getenv("AUDIT_RETRY_BACKOFF_S", "10"))
    return chain


def daily_quota_gone(models: Optional[list] = None, horizon_s: float = 3600) -> bool:
    """True when every audit model is resting for longer than an hour -- a daily cap,
    not a minute's throttle. Checked before a filing so a spent day costs no calls."""
    now = time.monotonic()
    return all(llm._COOLDOWN_UNTIL.get(m, 0.0) - now > horizon_s
               for m in (models or audit_models()))


# --- keeping each call small --------------------------------------------------------

class TokenPacer:
    """Tokens sent in the last minute, and a wait before a call that would pass the limit.

    One pacer per run, shared by every filing: the quota is per minute per model, not
    per document.
    """

    def __init__(self, tpm_limit: int = AUDIT_TPM_LIMIT, window: float = 60.0,
                 clock: Callable = time.monotonic, sleep: Callable = time.sleep):
        self.limit, self.window = tpm_limit, window
        self.clock, self.sleep = clock, sleep
        self.sent: list = []            # (time, tokens)
        self.waited_s = 0.0

    def _trim(self):
        cutoff = self.clock() - self.window
        self.sent = [(t, n) for t, n in self.sent if t > cutoff]

    def wait_for(self, estimate: int) -> float:
        if not self.limit:
            return 0.0
        waited = 0.0
        while True:
            self._trim()
            used = sum(n for _, n in self.sent)
            if not self.sent or used + estimate <= self.limit:
                break
            pause = max(0.5, self.sent[0][0] + self.window - self.clock() + 0.5)
            print(f"    ⏸  {used:,} tokens in the last minute; waiting {pause:.0f}s "
                  f"to stay under AUDIT_TPM_LIMIT={self.limit:,}")
            self.sleep(pause)
            waited += pause
        self.waited_s += waited
        return waited

    def record(self, tokens: int) -> None:
        if tokens:
            self.sent.append((self.clock(), int(tokens)))


def estimate_tokens(system: str, contents: list, tools: list) -> int:
    """Roughly four characters per token for text, a fixed charge per image."""
    chars = len(system) + len(json.dumps(tools))
    images = 0
    for turn in contents:
        for part in turn.get("parts", []):
            if "inline_data" in part:
                images += 1
            else:
                chars += len(json.dumps(part, ensure_ascii=False))
    return chars // 4 + images * IMAGE_TOKENS


def _stub(name: str, result: dict) -> dict:
    if name == "list_pages":
        return {"compacted": f"page list of {result.get('total_pages')} pages shown "
                             f"earlier; call list_pages again if needed"}
    pages = [p.get("page") for p in result.get("pages", [])] if "pages" in result \
        else [result.get("page")]
    return {"compacted": f"page(s) {pages} were read earlier and are no longer shown. "
                         f"What you reported from them is kept; read them again only for "
                         f"a figure you have not reported yet."}


def compact(contents: list, keep_last: int = KEEP_RECENT_TOOL_TURNS) -> int:
    """Replace old page text and images with a note. Returns how many parts shrank.

    Only BULKY tools are touched, and only in tool-result turns older than the last
    `keep_last`. The functionResponse itself stays -- Gemini pairs it with the model's
    functionCall -- only its payload shrinks.
    """
    result_turns = [i for i, turn in enumerate(contents)
                    if turn.get("role") == "user"
                    and any("functionResponse" in p for p in turn.get("parts", []))]
    old = result_turns[:-keep_last] if keep_last else result_turns
    shrunk = 0
    for i in old:
        parts = []
        for part in contents[i]["parts"]:
            response = part.get("functionResponse")
            if response and response.get("name") in BULKY_TOOLS:
                result = (response.get("response") or {}).get("result") or {}
                if isinstance(result, dict) and "compacted" not in result:
                    response["response"] = {"result": _stub(response["name"], result)}
                    shrunk += 1
            if "inline_data" in part:
                parts.append({"text": "[a page image was shown here earlier]"})
                shrunk += 1
                continue
            parts.append(part)
        contents[i]["parts"] = parts
    return shrunk


# --- the tools only the audit has ----------------------------------------------------

def read_page(ctx: ToolContext, args: dict, budget=None) -> ToolResult:
    """Pages as markdown tables with date-named columns, via pagemd; text if no geometry."""
    from extract import condense_page_text
    from pagemd import page_markdown
    from pdftext import text_layer_usable

    wanted = args.get("pages")
    if wanted is None:
        wanted = [args.get("page")]
    elif not isinstance(wanted, list):
        wanted = [wanted]
    if not wanted or all(p is None for p in wanted):
        return ToolResult(payload={"error": f"give pages between 1 and {ctx.total_pages}"},
                          error_kind="malformed_args")
    if len(wanted) > MAX_PAGES_PER_READ:
        return ToolResult(payload={"error": f"at most {MAX_PAGES_PER_READ} pages per call"},
                          error_kind="malformed_args")
    try:
        indexes = [_page_index(ctx, p) for p in wanted]
    except ValueError as exc:
        return ToolResult(payload={"error": str(exc)}, error_kind="page_out_of_range")
    fresh = {i + 1 for i in indexes} - ctx.pages_opened
    if budget is not None and fresh and len(ctx.pages_opened) + len(fresh) > budget.max_text_pages:
        return ToolResult(payload={"error": f"text budget exhausted ({len(ctx.pages_opened)} "
                                            f"of {budget.max_text_pages} pages); report "
                                            f"what you have or finish"},
                          error_kind="budget")
    raw = {i: ctx.page_text(i) for i in indexes}
    try:
        tables = page_markdown(ctx.pdf_path, indexes,
                               fallback={i: condense_page_text(t) for i, t in raw.items()})
    except Exception:
        tables = {i: condense_page_text(t) for i, t in raw.items()}
    pages = []
    for i in indexes:
        text = tables.get(i) or ""
        note = None
        if not raw[i].strip() or not text_layer_usable(raw[i]):
            note = "this page has no readable text layer; use read_page_image"
        ctx.pages_opened.add(i + 1)
        pages.append({"page": i + 1, "text": text[:PAGE_CHARS],
                      "truncated": len(text) > PAGE_CHARS, "note": note})
    payload = pages[0] if len(pages) == 1 else {"pages": pages}
    return ToolResult(payload=payload, meta={"pages": len(pages)})


def _schemas(budget, phase: str) -> list:
    navigation = [s for s in navigation_schemas(budget)
                  if s["name"] in ("list_pages", "search_text", "read_page_image")]
    evidence_props = {
        "printed_value": {"type": "string", "description": "Exactly as printed, e.g. "
                          "\"1.234.567\", \"(76.732)\", \"-\"."},
        "page": {"type": "integer", "description": "1-indexed page it is printed on."},
        "row_label": {"type": "string"},
        "column_header": {"type": "string", "description": "The header of the column "
                          "you read, with its date."},
    }
    item = {"type": "object", "properties": {
        "field": {"type": "string", "enum": AUDIT_FIELDS},
        **evidence_props,
        "components": {"type": "array", "description": "For a sum or a difference: each "
                       "printed part, with its sign. Leave printed_value empty then.",
                       "items": {"type": "object", "properties": {
                           "name": {"type": "string"}, **evidence_props,
                           "sign": {"type": "string", "enum": ["+", "-"]}},
                           "required": ["printed_value", "page"]}},
        "scale": {"type": "string", "enum": ["FULL", "THOUSANDS", "MILLIONS", "BILLIONS"],
                  "description": "From the statement header: 'dalam ribuan' is THOUSANDS."},
        "currency": {"type": "string", "enum": ["IDR", "USD"]},
        "note": {"type": "string"}},
        "required": ["field", "scale", "currency"]}
    tools = navigation + [
        {"name": "read_page",
         "description": ("One page or several (up to 4), each rebuilt as a table whose "
                         "columns are named by the dates the page prints. Indentation is "
                         "kept as '·', because it is what separates two rows with the "
                         "same label in different sections. Page text stays visible for "
                         f"{KEEP_RECENT_TOOL_TURNS} more steps and is then removed to keep "
                         "each call small, so report_evidence for what a page shows "
                         "BEFORE reading further."),
         "parameters": {"type": "object", "properties": {
             "pages": {"type": "array", "items": {"type": "integer"}},
             "page": {"type": "integer"}}}},
        {"name": "find_number",
         "description": ("Where a figure is printed, searched at full, thousand and "
                         "million scale (and in USD for a dollar filer). Give the value "
                         "in full units." + (" scope 'issuer' also searches this "
                                             "issuer's other filings."
                                             if phase == "adjudicate" else "")),
         "parameters": {"type": "object", "properties": {
             "value": {"type": "number"},
             "scope": {"type": "string", "enum": (["filing", "issuer"]
                                                  if phase == "adjudicate" else ["filing"])}},
             "required": ["value"]}},
    ]
    if phase == "read":
        tools.append({"name": "report_evidence",
                      "description": "Report one or more fields with their evidence. "
                                     "Each citation is checked and the reply says what "
                                     "failed.",
                      "parameters": {"type": "object", "properties": {
                          "items": {"type": "array", "items": item}},
                          "required": ["items"]}})
    else:
        verdict = json.loads(json.dumps(item))
        verdict["properties"].update({
            "verdict": {"type": "string", "enum": VERDICTS},
            "cause": {"type": "string", "enum": CAUSES},
            "quote": {"type": "string", "description": "The printed row you rely on."},
            "explanation": {"type": "string"}})
        verdict["required"] = ["field", "verdict", "cause", "explanation"]
        tools.append({"name": "report_verdict",
                      "description": "Settle one or more disputed fields.",
                      "parameters": {"type": "object", "properties": {
                          "items": {"type": "array", "items": verdict}},
                          "required": ["items"]}})
    tools.append({"name": "finish", "description": "Stop, saying what was not found and why.",
                  "parameters": {"type": "object", "properties": {
                      "reason": {"type": "string"},
                      "not_found": {"type": "array", "items": {"type": "string"}}},
                      "required": ["reason"]}})
    return tools


# --- one conversation -----------------------------------------------------------------

@dataclass
class AuditState:
    """Everything one filing's audit knows. Shapes in `steps`, never page contents."""
    ticker: str
    quarter: str
    year: int
    ctx: ToolContext
    source: PageSource
    fx: object = None
    fx_read: bool = False
    evidence: dict = field(default_factory=dict)          # field -> Evidence
    verdicts: dict = field(default_factory=dict)          # field -> dict
    disputes: dict = field(default_factory=dict)          # field -> label (adjudication)
    steps: list = field(default_factory=list)
    call_tokens: list = field(default_factory=list)       # estimated input per call
    compactions: int = 0
    handovers: list = field(default_factory=list)
    providers: list = field(default_factory=list)
    stop_reason: str = "unknown"
    not_found: list = field(default_factory=list)
    tool_errors: int = 0

    def rate(self):
        if not self.fx_read:
            from normalize import extract_fx_rate
            self.fx_read = True
            try:
                self.fx = extract_fx_rate(self.ctx.pdf_path)
            except Exception:
                self.fx = None
            self.ctx.fx_rate = getattr(self.fx, "idr_per_usd", None)
        return self.fx

    def trajectory(self) -> dict:
        counts = {}
        for s in self.steps:
            counts[s["tool"]] = counts.get(s["tool"], 0) + 1
        return {"steps_used": len(self.steps), "tool_counts": counts,
                "tool_errors": self.tool_errors, "stop_reason": self.stop_reason,
                "call_tokens_estimated": self.call_tokens,
                "max_call_tokens_estimated": max(self.call_tokens or [0]),
                "compactions": self.compactions, "handovers": self.handovers,
                "providers": self.providers, "not_found": self.not_found,
                "pages_opened": sorted(self.ctx.pages_opened),
                "pages_rendered": sorted(self.ctx.pages_rendered),
                "steps": self.steps}


def _record_evidence(state: AuditState, args: dict) -> dict:
    replies = []
    for raw in args.get("items") or []:
        if not isinstance(raw, dict):
            continue
        evidence = evidence_from_args(raw)
        if evidence.currency == "USD":
            state.rate()
        verify_evidence(evidence, state.source, state.quarter, state.year, fx=state.fx)
        if evidence.field in AUDIT_FIELDS:
            state.evidence[evidence.field] = evidence
        replies.append(feedback(evidence))
    missing = [f for f in AUDIT_FIELDS
               if f not in state.evidence or not state.evidence[f].verified]
    return {"checked": replies, "still_needed_or_failing": missing}


def _record_verdict(state: AuditState, args: dict) -> dict:
    replies = []
    for raw in args.get("items") or []:
        if not isinstance(raw, dict) or raw.get("field") not in state.disputes:
            replies.append({"field": (raw or {}).get("field"),
                            "error": f"not a disputed field; disputed: {sorted(state.disputes)}"})
            continue
        name = raw["field"]
        label = state.disputes[name]
        verdict = {k: raw.get(k) for k in ("verdict", "cause", "quote", "explanation")}
        evidence = None
        if raw.get("printed_value") not in (None, "") or raw.get("components"):
            evidence = evidence_from_args(raw)
            if evidence.currency == "USD":
                state.rate()
            verify_evidence(evidence, state.source, state.quarter, state.year, fx=state.fx)
        elif name in state.evidence:
            evidence = state.evidence[name]
        verdict["evidence"] = evidence.to_dict() if evidence else None
        # A verdict is a claim. It is accepted only as far as the filing backs it.
        from labelaudit import rel_error, tolerance_for
        if verdict["verdict"] == "label_wrong":
            if evidence is None or not evidence.verified:
                verdict["accepted"], verdict["status"] = False, "needs_human"
                verdict["why"] = "the corrected figure's citation did not check out"
            elif rel_error(evidence.value, label) <= tolerance_for(evidence):
                verdict["accepted"], verdict["status"] = False, "needs_human"
                verdict["why"] = "the 'corrected' figure equals the label"
            else:
                verdict["accepted"], verdict["status"] = True, "label_wrong"
                verdict["proposed_value"] = evidence.value
        elif verdict["verdict"] == "auditor_wrong":
            verdict["accepted"], verdict["status"] = True, "label_confirmed_on_review"
        else:
            verdict["accepted"], verdict["status"] = False, "needs_human"
            verdict["why"] = "the definition admits both readings"
        state.verdicts[name] = verdict
        replies.append({"field": name, "status": verdict["status"],
                        "why": verdict.get("why"),
                        "problems": feedback(evidence)["problems"] if evidence else None})
    return {"checked": replies,
            "still_open": sorted(set(state.disputes) - set(state.verdicts))}


def _spent(state: AuditState, budget: AgentBudget, started: float, usage) -> Optional[str]:
    if len(state.steps) >= budget.max_steps:
        return "step_budget"
    if time.time() - started > budget.max_seconds:
        return "time_budget"
    if usage is not None and (usage.input_tokens or 0) > budget.max_input_tokens:
        return "token_budget"
    return None


def _conversation(provider, system: str, opening: str, tools: list, state: AuditState,
                  budget: AgentBudget, pacer: TokenPacer, usage, started: float,
                  phase: str) -> None:
    contents = [{"role": "user", "parts": [{"text": opening}]}]
    silent = 0
    while True:
        spent = _spent(state, budget, started, usage)
        if spent:
            state.stop_reason = spent
            return
        if phase == "read" and all(f in state.evidence and state.evidence[f].verified
                                   for f in AUDIT_FIELDS):
            state.stop_reason = "all_fields_verified"
            return
        if phase == "adjudicate" and set(state.disputes) <= set(state.verdicts):
            state.stop_reason = "all_disputes_settled"
            return

        state.compactions += compact(contents)
        estimate = estimate_tokens(system, contents, tools)
        if estimate > AUDIT_MAX_CALL_TOKENS:
            state.compactions += compact(contents, keep_last=0)
            estimate = estimate_tokens(system, contents, tools)
        pacer.wait_for(estimate)
        state.call_tokens.append(estimate)
        before = (usage.input_tokens or 0) if usage is not None else 0
        turn = provider.complete_with_tools(system, contents, tools, usage=usage)
        after = (usage.input_tokens or 0) if usage is not None else 0
        pacer.record((after - before) or estimate)

        if not turn.tool_calls:
            silent += 1
            contents.append(turn.raw or {"role": "model", "parts": [{"text": turn.text or ""}]})
            if silent >= MAX_NO_TOOL_TURNS:
                state.stop_reason = "no_tool_call"
                return
            contents.append({"role": "user", "parts": [{"text":
                "Answer with a tool call. Call finish if there is nothing left to do."}]})
            continue
        silent = 0

        responses, images, finished = [], [], False
        for call in turn.tool_calls:
            args = call.args or {}
            step = {"i": len(state.steps) + 1, "tool": call.name, "ok": True,
                    "args": {k: v for k, v in args.items()
                             if k in ("page", "pages", "query", "scope", "reason")}}
            if call.name == "finish":
                state.stop_reason, finished = "finished", True
                state.not_found = list(args.get("not_found") or [])
                payload = {"acknowledged": args.get("reason", "")}
            elif call.name == "report_evidence" and phase == "read":
                payload = _record_evidence(state, args)
                step["fields"] = [c["field"] for c in payload["checked"]]
                step["verified"] = sum(1 for c in payload["checked"] if c["verified"])
            elif call.name == "report_verdict" and phase == "adjudicate":
                payload = _record_verdict(state, args)
                step["fields"] = [c["field"] for c in payload["checked"]]
            elif call.name == "read_page":
                result = read_page(state.ctx, args, budget=budget)
                payload, step["error_kind"] = result.payload, result.error_kind
            else:
                if call.name == "find_number":
                    state.rate()
                    if phase != "adjudicate":
                        args = {**args, "scope": "filing"}
                result = run_tool(state.ctx, call.name, args, budget=budget)
                payload, step["error_kind"] = result.payload, result.error_kind
                if result.image_b64:
                    images.append((payload.get("page"), result.image_b64))
            if step.get("error_kind"):
                step["ok"] = False
                state.tool_errors += 1
            else:
                step.pop("error_kind", None)
            state.steps.append(step)
            responses.append({"functionResponse": {"name": call.name,
                                                   "response": {"result": payload}}})
        contents.append(turn.raw)
        for page, image in images:
            responses.append({"inline_data": {"mime_type": "image/png", "data": image}})
            responses.append({"text": f"The image above is page {page}."})
        contents.append({"role": "user", "parts": responses})
        if finished:
            return


def _period_words(quarter: str, year: int) -> str:
    return f"{MONTHS_ID[quarter]} {year}"


def _read_opening(state: AuditState, budget: AgentBudget) -> str:
    lines = [f"Issuer {state.ticker}. The period being audited ends {_period_words(state.quarter, state.year)} "
             f"({state.quarter} {state.year}). This filing has {state.ctx.total_pages} pages. "
             f"You have {budget.max_steps - len(state.steps)} steps."]
    done = [f for f in AUDIT_FIELDS if f in state.evidence and state.evidence[f].verified]
    if done:
        lines.append("RESUME NOTE -- the previous model was cut off. Already verified: "
                     + ", ".join(done) + ". Still needed: "
                     + ", ".join(f for f in AUDIT_FIELDS if f not in done) + ".")
    return "\n".join(lines)


def _fmt(value) -> str:
    return "-" if value is None else f"{value:,.0f}".replace(",", ".")


def _adjudicate_opening(state: AuditState, pipeline: dict, located: dict) -> str:
    lines = [f"Issuer {state.ticker}, period ending {_period_words(state.quarter, state.year)} "
             f"({state.quarter} {state.year}); {state.ctx.total_pages} pages.",
             "The disputed fields:"]
    for name, label in sorted(state.disputes.items()):
        ev = state.evidence.get(name)
        lines.append(f"\n- {name} ({EXCEL_ROWS[name][1]})")
        lines.append(f"    label in the sheet:      {_fmt(label)} (full units)")
        if ev is not None:
            cited = "; ".join(f"{'-' if p.sign < 0 else '+'}{p.printed_value} p{p.page} "
                              f"'{p.row_label}' under '{p.column_header}'" for p in ev.parts)
            lines.append(f"    earlier reading:         {_fmt(ev.value)} from {cited} "
                         f"({ev.scale}, {ev.currency})")
        lines.append(f"    pipeline extraction:     {_fmt(pipeline.get(name))}")
        hits = located.get(name) or []
        if hits:
            for hit in hits[:6]:
                lines.append(f"    label printed at:        {hit['filing']} p{hit['page']} "
                             f"({hit['scale']}, {hit['currency']}): {hit['line']}")
        else:
            lines.append("    label printed at:        nowhere in this issuer's filings, "
                         "at any scale")
    return "\n".join(lines)


def _run_phase(state: AuditState, phase: str, opening: Callable, budget: AgentBudget,
               pacer: TokenPacer, usage, chain: Optional[list] = None) -> None:
    """Walk the provider chain for one phase. Budget is never refreshed on hand-over."""
    system = AUDIT_READ_PROMPT if phase == "read" else AUDIT_ADJUDICATE_PROMPT
    tools = _schemas(budget, phase)
    started = time.time()
    chain = chain if chain is not None else audit_chain()
    daily = []
    for provider in chain:
        if not getattr(provider, "supports_tools", False):
            state.handovers.append({"phase": phase, "provider": provider.name,
                                    "reason": "no tool calling"})
            continue
        state.providers.append(provider.name)
        try:
            _conversation(provider, system, opening(), tools, state, budget, pacer,
                          usage, started, phase)
            return
        except LLMUnavailable as exc:
            state.handovers.append({"phase": phase, "provider": provider.name,
                                    "step": len(state.steps), "reason": str(exc)[:200]})
            daily.append("daily quota" in str(exc))
            print(f"    ↪ {exc}")
        except LLMError as exc:
            state.handovers.append({"phase": phase, "provider": provider.name,
                                    "step": len(state.steps), "reason": str(exc)[:200]})
            print(f"    ✗ {type(exc).__name__}: {exc}")
    if daily and all(daily) and len(daily) == len(chain):
        raise QuotaExhausted("every audit model has used its daily quota")
    state.stop_reason = "no_provider"


# --- the two entry points ---------------------------------------------------------------

def new_state(ticker: str, quarter: str, year: int, pdf: str,
              related: Optional[dict] = None) -> AuditState:
    ctx = ToolContext.for_pdf(pdf)
    ctx.related = dict(related or {})
    return AuditState(ticker=ticker, quarter=quarter, year=year, ctx=ctx,
                      source=PageSource(pdf_path=pdf))


def read_filing(state: AuditState, budget: Optional[AgentBudget] = None,
                pacer: Optional[TokenPacer] = None, usage=None,
                chain: Optional[list] = None) -> dict:
    """Phase one: the blind reading. Returns the cacheable record."""
    from usage import Usage
    usage = usage or Usage()
    budget = budget or audit_budget()
    pacer = pacer or TokenPacer()
    _run_phase(state, "read", lambda: _read_opening(state, budget), budget, pacer, usage,
               chain)
    verified = sum(1 for e in state.evidence.values() if e.verified)
    return {"status": "done" if state.stop_reason in ("finished", "all_fields_verified")
            else "partial",
            "stop_reason": state.stop_reason,
            "fields_verified": verified,
            "evidence": {f: e.to_dict() for f, e in state.evidence.items()},
            "fx_rate": getattr(state.fx, "idr_per_usd", None),
            "trajectory": state.trajectory(),
            "usage": usage.to_dict()}


def adjudicate_filing(state: AuditState, disputes: dict, pipeline: Optional[dict] = None,
                      budget: Optional[AgentBudget] = None,
                      pacer: Optional[TokenPacer] = None, usage=None,
                      chain: Optional[list] = None) -> dict:
    """Phase two: settle the cells where a verified reading disagrees with the label."""
    from agenttools import find_number
    from usage import Usage
    usage = usage or Usage()
    budget = budget or audit_budget()
    pacer = pacer or TokenPacer()
    state.disputes = dict(disputes)
    state.verdicts, state.steps, state.call_tokens = {}, [], []
    state.stop_reason = "unknown"
    state.rate()
    located = {}
    for name, label in disputes.items():
        # Where the LABEL is printed, found by code before the model is asked anything.
        # This is what separated "comparative column" from "another filing's figure" on
        # GTRA, and it costs no tokens.
        try:
            located[name] = find_number(state.ctx, {"value": label, "scope": "issuer"}
                                        ).payload["hits"]
        except Exception:
            located[name] = []
    _run_phase(state, "adjudicate",
               lambda: _adjudicate_opening(state, pipeline or {}, located),
               budget, pacer, usage, chain)
    return {"stop_reason": state.stop_reason,
            "verdicts": {f: {**v, "label": state.disputes[f],
                             "label_located": located.get(f, [])[:6]}
                         for f, v in state.verdicts.items()},
            "unsettled": sorted(set(disputes) - set(state.verdicts)),
            "trajectory": state.trajectory(),
            "usage": usage.to_dict()}


def evidence_from_record(record: dict) -> dict:
    """{field: Evidence} back from a cached reading."""
    return {f: Evidence.from_dict(raw)
            for f, raw in ((record or {}).get("evidence") or {}).items()}
