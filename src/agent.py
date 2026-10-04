#!/usr/bin/env python3
"""
The same extraction, decided by the model instead of by regular expressions.

`extract_agentic()` is a SECOND implementation behind the pipeline's call signature, not
a rewrite of it. What changes is who chooses the pages: `extract_from_pdf` is handed a
selection computed by `page_select.py`, while this asks a model to find the statements
itself, with tools for listing, searching, reading and rendering pages.

What deliberately does NOT change is everything after the reading: `merge_group`, the
two date guards, `derive_fields` and `assess` are the same functions operating on the
same object. That is what makes the two paths comparable by construction rather than by
inspection -- a difference in score is a difference in control flow, because nothing
else was allowed to differ.

The repo argues against this at README:651: "the pages are known before any model runs,
so there is nothing for an agent to decide". That argument is exactly as strong as the
deterministic selector, which needed four hand-written patches for filings that hide
their titles behind translation notices or split them across bilingual columns. This
module exists to find out whether a model with a search tool needs those patches -- and
the evaluation harness, not this docstring, is what answers it.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from agenttools import (AgentBudget, ToolContext, all_schemas, run_tool)
from extract import (ALWAYS, GROUP_FIELDS, _apply_current_table_guard,
                     _apply_treasury_date_guard, _coerce_numbers, _filled, assess,
                     derive_fields, merge_group)
from llm import LLMError, LLMUnavailable, get_provider_chain
from prompts import AGENT_SYSTEM_PROMPT
from schema import FinancialStatementExtraction

REPORT_GROUPS = [group for group, fields in GROUP_FIELDS.items() if fields]
MAX_NO_TOOL_TURNS = 2       # one nudge, not an infinite politeness loop


@dataclass
class Trajectory:
    """What the loop did, in a form that survives the prediction cache.

    Shapes, not contents: no page text, no base64, no transcript. A trajectory is ~2-4 KB
    and is stored beside the prediction, so the agent metrics can be recomputed from a
    committed scorecard months later without the PDFs.
    """
    steps: list = field(default_factory=list)
    tool_errors: list = field(default_factory=list)
    reported: dict = field(default_factory=dict)          # group -> extraction
    reported_pages: dict = field(default_factory=dict)    # group -> [1-indexed pages]
    handovers: list = field(default_factory=list)
    providers: list = field(default_factory=list)
    stop_reason: str = "unknown"
    budget_exhausted: bool = False
    no_tool_call_turns: int = 0
    not_found: list = field(default_factory=list)

    def to_dict(self, ctx: ToolContext, budget: AgentBudget) -> dict:
        counts = {}
        for step in self.steps:
            counts[step["tool"]] = counts.get(step["tool"], 0) + 1
        return {
            "schema": 1,
            "steps_used": len(self.steps),
            "tool_calls": len(self.steps),
            "stop_reason": self.stop_reason,
            "budget_exhausted": self.budget_exhausted,
            "budget": budget.to_dict(),
            "steps": self.steps,
            "tool_errors": self.tool_errors,
            "tool_counts": counts,
            "pages_opened_text": sorted(ctx.pages_opened),
            "pages_rendered_image": sorted(ctx.pages_rendered),
            "pages_reported": {g: sorted(p) for g, p in self.reported_pages.items()},
            "groups_reported": sorted(self.reported),
            "no_tool_call_turns": self.no_tool_call_turns,
            "handovers": self.handovers,
            "providers": self.providers,
            "not_found": self.not_found,
            # Filled in offline by scripts/page_agreement.py: running the deterministic
            # selector here would charge the agent for the baseline's work and destroy
            # the latency comparison, which is the headline number.
            "deterministic_pages": None,
        }


def _report_group(trajectory: Trajectory, group: str, args: dict) -> dict:
    """Turn one report_<group> call into an extraction. Returns the payload to feed back."""
    pages = args.get("pages") or []
    pages = [int(p) for p in pages if isinstance(p, (int, float, str))
             and str(p).strip().lstrip("-").isdigit()]
    allowed = set(GROUP_FIELDS[group]) | set(ALWAYS)
    extras = sorted(set(args) - allowed - {"pages"})
    values = {k: v for k, v in args.items() if k in allowed}

    # The same coercion the pipeline applies to a model's JSON. Models put "1.234.567"
    # into a number field often enough that skipping this would read it as 1.234567.
    part = FinancialStatementExtraction.from_dict(_coerce_numbers(dict(values)),
                                                 strict=False)
    trajectory.reported[group] = part
    trajectory.reported_pages[group] = pages
    payload = {"recorded": group, "fields": sorted(k for k in values if values[k] is not None),
               "pages": pages,
               "still_needed": sorted(set(REPORT_GROUPS) - set(trajectory.reported))}
    if extras:
        # A warning rather than an error: the report landed, the strays were dropped.
        payload["warning"] = (f"dropped fields this statement cannot answer: "
                              f"{', '.join(extras)}")
    if not pages:
        payload["warning"] = ("no pages named, so these figures cannot be checked against "
                              "the filing and will be withdrawn -- report again with the "
                              "pages you read them from")
    return payload


def _opening_message(ctx: ToolContext, trajectory: Trajectory, budget: AgentBudget) -> str:
    """The first user turn. On a hand-over it also says what is already known."""
    remaining = max(0, budget.max_steps - len(trajectory.steps))
    lines = [f"This filing has {ctx.total_pages} pages. Find the statements and report "
             f"what they print. You have {remaining} steps left."]
    if trajectory.reported:
        # Carried as plain text, not as a translated transcript: Gemini's functionCall
        # parts and Ollama's tool_calls are different shapes, and a transcript rewritten
        # between them is a third thing to keep correct with no test that would catch it
        # drifting. The findings are what matter, and they are already extracted.
        lines.append("\nRESUME NOTE -- the previous model was cut off.")
        for group, pages in sorted(trajectory.reported_pages.items()):
            lines.append(f"  already reported: {group} (pages {pages or 'unnamed'})")
        lines.append(f"  still needed: "
                     f"{', '.join(sorted(set(REPORT_GROUPS) - set(trajectory.reported)))}")
        if ctx.pages_opened:
            lines.append(f"  pages already read: {sorted(ctx.pages_opened)}")
        lines.append("Do not report what is already listed above.")
    return "\n".join(lines)


def _spent(trajectory: Trajectory, budget: AgentBudget, started: float, usage) -> Optional[str]:
    """Which stopping budget, if any, is used up."""
    if len(trajectory.steps) >= budget.max_steps:
        return "step_budget"
    if time.time() - started > budget.max_seconds:
        return "time_budget"
    tokens = getattr(usage, "input_tokens", None) if usage else None
    if tokens and tokens > budget.max_input_tokens:
        return "token_budget"
    return None


def _run(provider, ctx: ToolContext, trajectory: Trajectory, budget: AgentBudget,
         tools: list, started: float, usage) -> None:
    """One provider's conversation. Returns when it stops; raises LLMUnavailable to hand over."""
    contents = [{"role": "user",
                 "parts": [{"text": _opening_message(ctx, trajectory, budget)}]}]
    consecutive_silent = 0

    while True:
        spent = _spent(trajectory, budget, started, usage)
        if spent:
            trajectory.stop_reason = spent
            trajectory.budget_exhausted = True
            return

        index = len(trajectory.steps) + 1
        if usage is not None:
            with usage.stage(f"step_{index}"):
                turn = provider.complete_with_tools(AGENT_SYSTEM_PROMPT, contents, tools,
                                                    usage=usage)
        else:
            turn = provider.complete_with_tools(AGENT_SYSTEM_PROMPT, contents, tools)

        if not turn.tool_calls:
            # A turn that answered in prose. Nudge once; a second one in a row means the
            # model is not going to drive the tools and further turns are just spending.
            consecutive_silent += 1
            trajectory.no_tool_call_turns += 1
            contents.append(turn.raw)
            if consecutive_silent >= MAX_NO_TOOL_TURNS:
                trajectory.stop_reason = "no_tool_call"
                return
            contents.append({"role": "user", "parts": [{"text":
                "Answer with a tool call. Call finish if you have nothing left to look for."}]})
            continue
        consecutive_silent = 0

        response_parts, images = [], []
        finished = False
        for call in turn.tool_calls:
            step = {"i": len(trajectory.steps) + 1, "tool": call.name,
                    "args": {k: v for k, v in (call.args or {}).items()
                             if k in ("page", "query", "max_hits", "pages", "reason")},
                    "ok": True}

            if call.name == "finish":
                trajectory.stop_reason = "finished"
                trajectory.not_found = list((call.args or {}).get("not_found") or [])
                payload = {"acknowledged": (call.args or {}).get("reason", "")}
                finished = True
            elif call.name.startswith("report_") and call.name[7:] in GROUP_FIELDS:
                payload = _report_group(trajectory, call.name[7:], call.args or {})
                if "warning" in payload:
                    step["ok"] = False
                    step["error_kind"] = "bad_field_name"
                    trajectory.tool_errors.append(
                        {"i": step["i"], "tool": call.name, "kind": "bad_field_name",
                         "message": payload["warning"]})
            else:
                result = run_tool(ctx, call.name, call.args or {}, budget=budget)
                payload = result.payload
                step.update(result.meta)
                if result.error_kind:
                    step["ok"] = False
                    step["error_kind"] = result.error_kind
                    trajectory.tool_errors.append(
                        {"i": step["i"], "tool": call.name, "kind": result.error_kind,
                         "message": str(payload.get("error") or payload.get("warning"))[:200]})
                if result.image_b64:
                    images.append((payload.get("page"), result.image_b64))

            trajectory.steps.append(step)
            # The response is always an OBJECT. Gemini rejects a scalar there, and an
            # error is an ordinary successful turn as far as the transport is concerned.
            response_parts.append({"functionResponse": {
                "name": call.name, "response": {"result": payload}}})

        contents.append(turn.raw)
        # A functionResponse cannot carry inline_data, so a rendered page travels beside
        # it with a caption -- without one, several images across several turns become
        # indistinguishable pixels.
        for page, image_b64 in images:
            response_parts.append({"inline_data": {"mime_type": "image/png",
                                                   "data": image_b64}})
            response_parts.append({"text": f"The image above is page {page}."})
        contents.append({"role": "user", "parts": response_parts})

        if finished:
            return
        if set(REPORT_GROUPS) <= set(trajectory.reported):
            trajectory.stop_reason = "all_groups"
            return


def extract_agentic(pdf_path: str, usage=None, budget: Optional[AgentBudget] = None
                    ) -> Optional[FinancialStatementExtraction]:
    """Extract by letting the model choose which pages to open.

    Same contract as extract.extract_from_pdf: a FinancialStatementExtraction carrying
    .usage, .pages_selected, .model and .field_confidence, or LLMUnavailable when no
    provider could be reached. The difference is entirely in how the pages are chosen
    and how the answers are collected.
    """
    from usage import Usage

    usage = Usage() if usage is None else usage
    budget = budget or AgentBudget()
    started = time.time()

    with usage.stage("select_pages"):
        # Named the same stage as the pipeline's page selection, because it is the same
        # work: opening the PDF and learning how many pages it has. Everything the agent
        # spends on FINDING pages lands in step_N, which is the honest place for it.
        ctx = ToolContext.for_pdf(pdf_path)

    trajectory = Trajectory()
    tools = all_schemas(budget)
    unavailable = []

    for provider in get_provider_chain():
        if not getattr(provider, "supports_tools", False):
            trajectory.handovers.append({"provider": provider.name,
                                         "step": len(trajectory.steps),
                                         "reason": "provider does not support tool calling"})
            continue
        if len(trajectory.steps) >= budget.max_steps:
            trajectory.stop_reason = "step_budget"
            trajectory.budget_exhausted = True
            break

        trajectory.providers.append(provider.name)
        print(f"\n\U0001F916 {provider.name} [agent, "
              f"{budget.max_steps - len(trajectory.steps)} steps left]...")
        try:
            _run(provider, ctx, trajectory, budget, tools, started, usage)
        except LLMUnavailable as exc:
            # The budget is NOT refreshed on hand-over. Otherwise a flaky chain lets one
            # document spend three budgets and the cost comparison means nothing.
            print(f"    ↪ {exc}")
            trajectory.handovers.append({"provider": provider.name,
                                         "step": len(trajectory.steps),
                                         "reason": str(exc)[:200]})
            unavailable.append(f"{provider.name}: {exc}")
            continue
        except LLMError as exc:
            print(f"    ✗ {type(exc).__name__}: {exc}")
            trajectory.handovers.append({"provider": provider.name,
                                         "step": len(trajectory.steps),
                                         "reason": str(exc)[:200]})
            unavailable.append(f"{provider.name}: {exc}")
            continue
        break

    if not trajectory.reported:
        if unavailable:
            raise LLMUnavailable("no provider was available - " + "; ".join(unavailable))
        raise LLMError("the agent reported no statement")

    # --- everything below is the pipeline's own code, unchanged --------------------
    groups = {group: sorted({p - 1 for p in pages})
              for group, pages in trajectory.reported_pages.items()}
    reported_pages = sorted({p for pages in groups.values() for p in pages})

    from pdftext import page_texts as read_pages
    with usage.stage("read_text"):
        # Grounding checks only the pages the agent SAID it read the figures from, so a
        # figure claimed from a page it never opened fails and abstention withdraws it.
        # That makes the agent's own citation testable rather than decorative.
        page_texts = read_pages(pdf_path, reported_pages) if reported_pages else {}

    merged = FinancialStatementExtraction()
    for group in REPORT_GROUPS:
        merge_group(merged, trajectory.reported.get(group), group)

    _apply_current_table_guard(merged, page_texts, groups)
    _apply_treasury_date_guard(merged, page_texts, groups)
    for warning in derive_fields(merged):
        print(f"    ⚠ {warning}")

    with usage.stage("assess"):
        merged.field_confidence = assess(merged, page_texts)

    merged.usage = usage
    merged.pages_selected = [p + 1 for p in reported_pages]
    # Which model answered, and in which order if it changed hands. The metrics slice by
    # this, so an agent run can never be mistaken for a pipeline run.
    merged.model = "agent:" + ">".join(trajectory.providers or ["none"])
    merged.agent_trajectory = trajectory.to_dict(ctx, budget)
    merged.budget_exhausted = trajectory.budget_exhausted

    print(f"  ✓ {_filled(merged)} field(s) in {len(trajectory.steps)} step(s), "
          f"{trajectory.stop_reason}\n")
    return merged
