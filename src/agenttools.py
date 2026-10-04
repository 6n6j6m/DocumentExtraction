#!/usr/bin/env python3
"""
The tools an agent is given, and nothing else: no provider, no prompt, no loop.

Everything here is a pure function over a PDF and a dict of arguments, which is the
point — the thesis of the agentic branch can be tested before a single token is spent.
If `search_text` cannot find the statement titles that the deterministic selector's
250-character title region misses, the agent has nothing to decide and the README's
argument at line 651 stands.

Two conventions, both chosen to remove a class of bug rather than to be tidy:

**Page numbers are 1-indexed at the tool boundary and 0-indexed inside.** The model sees
what a human reading the PDF sees. The conversion happens in exactly one function,
`_page_index`, which is also where an out-of-range page is refused — getting this right
in two places and wrong in a third is how that bug usually survives.

**A tool never raises.** Every failure is a payload the model reads on its next turn, and
every message names the valid range or the valid set: a model told "page 300 does not
exist; this filing has 122 pages (1-122)" asks for a different page, while one told
"invalid page" asks for the same page again.
"""

import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from extract import condense_page_text, render_pdf_page_to_image
from schema import FIELD_TYPES, NUMBER, NUMBER_LIST, TEXT

TITLE_CHARS = 110          # enough to recognise a statement; short enough to list 150 pages
PAGE_TEXT_CHARS = 6_000    # an unreadable page must not eat a third of the window
MAX_HITS = 25
MAX_PAGES_PER_READ = 4     # a statement spans two or three pages; more is a fishing trip
CONTEXT_CHARS = 90


@dataclass
class AgentBudget:
    """Two kinds of ceiling, which behave differently on purpose.

    STOPPING budgets (steps, seconds, input tokens) end the loop: whatever has been
    reported still goes through derive_fields and assess, because a partial result is
    information while an exception is a harness error.

    REFUSAL budgets (images, text pages) refuse the TOOL and let the loop continue. The
    agent can still finish; it just has to finish from what it already has.

    Defaults are set for quality rather than thrift -- the experiment decides modality on
    accuracy first, and a budget tight enough to change the answer would decide it by
    accident.
    """
    max_steps: int = int(os.getenv("AGENT_MAX_STEPS", "14"))
    max_images: int = int(os.getenv("AGENT_MAX_IMAGES", "8"))
    max_text_pages: int = int(os.getenv("AGENT_MAX_TEXT_PAGES", "25"))
    max_input_tokens: int = int(os.getenv("AGENT_MAX_INPUT_TOKENS", "200000"))
    # Wall clock, which includes the provider's own waiting: a single per-minute 429
    # costs a 70-second cooldown inside one step. At 240s a filing that met two of them
    # stopped for "time" having barely thought, which measured the rate limiter rather
    # than the loop. This is a guard against a runaway conversation, not a cost lever --
    # steps and images are the cost levers.
    max_seconds: int = int(os.getenv("AGENT_MAX_SECONDS", "900"))

    def to_dict(self) -> dict:
        return {"max_steps": self.max_steps, "max_images": self.max_images,
                "max_text_pages": self.max_text_pages,
                "max_input_tokens": self.max_input_tokens,
                "max_seconds": self.max_seconds}


@dataclass
class ToolResult:
    """What one tool call produced: a payload for the model, and what it cost us."""
    payload: dict
    image_b64: Optional[str] = None
    error_kind: Optional[str] = None
    meta: dict = field(default_factory=dict)


@dataclass
class ToolContext:
    """Per-document state shared by every tool call in one extraction.

    Built once per DOCUMENT, not per provider, so a hand-over to another model re-reads
    nothing from the PDF: `pdftext.page_texts` and `page_titles` are disk-cached, and
    rendered images are kept here in memory for the life of the document.
    """
    pdf_path: str
    total_pages: int
    titles: Optional[dict] = None
    texts: Optional[dict] = None
    images: dict = field(default_factory=dict)
    pages_opened: set = field(default_factory=set)      # 1-indexed, text
    pages_rendered: set = field(default_factory=set)    # 1-indexed, image
    # The same issuer's other filings, {"Q1 2024": path}, for find_number's issuer
    # scope. Empty for extraction; the label audit fills it.
    related: dict = field(default_factory=dict)
    # IDR per USD, when the filing reports in dollars, so find_number can look for a
    # full-Rupiah figure as the dollar amount it was converted from.
    fx_rate: Optional[float] = None

    @classmethod
    def for_pdf(cls, pdf_path: str) -> "ToolContext":
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
        return cls(pdf_path=pdf_path, total_pages=total)

    def all_titles(self) -> dict:
        if self.titles is None:
            from pdftext import page_titles
            self.titles = page_titles(self.pdf_path)
        return self.titles

    def all_texts(self) -> dict:
        if self.texts is None:
            from pdftext import page_texts
            self.texts = page_texts(self.pdf_path)
        return self.texts

    def page_text(self, index: int) -> str:
        """One page's text, from whatever has already been read.

        Reading a single page has to go through the same store as a whole-document
        search, or a filing whose pages were read one way disagrees with itself when
        read the other -- and the OCR of a broken page would be paid for twice.
        """
        if self.texts is not None:
            return self.texts.get(index, "") or ""
        from pdftext import page_texts
        page = page_texts(self.pdf_path, [index]) or {}
        return page.get(index, "") or ""


def _page_index(ctx: ToolContext, value) -> int:
    """A 1-indexed page from the model to a 0-indexed page for the code.

    Raises ValueError with the message the model should see. The caller turns it into a
    payload; nothing propagates out of a tool.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"page must be a whole number between 1 and {ctx.total_pages}, "
                         f"got {value!r}")
    try:
        page = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"page must be a whole number between 1 and {ctx.total_pages}, "
                         f"got {value!r}")
    if page < 1 or page > ctx.total_pages:
        raise ValueError(f"page {page} does not exist; this filing has "
                         f"{ctx.total_pages} pages (1-{ctx.total_pages})")
    return page - 1


# --- the navigation tools ---------------------------------------------------------

def list_pages(ctx: ToolContext, args: dict) -> ToolResult:
    """Every page's title region: the shape of the filing, before opening anything."""
    titles = ctx.all_titles()
    pages = []
    for n in range(ctx.total_pages):
        head = " ".join((titles.get(n) or "").split())[:TITLE_CHARS]
        pages.append({"page": n + 1, "title": head})
    return ToolResult(payload={"total_pages": ctx.total_pages, "pages": pages},
                      meta={"chars": sum(len(p["title"]) for p in pages)})


def search_text(ctx: ToolContext, args: dict) -> ToolResult:
    """Find a phrase anywhere in the filing.

    This is the tool that contests the deterministic selector. Every one of the four
    hand-written patches in page_select.py exists because a title is present in the page
    text but outside the region the selector reads: behind a translation notice, or split
    across bilingual columns. A plain full-text search has no such region.

    The model supplies a phrase, never a pattern -- it is escaped before use, so a stray
    bracket is a search for a bracket rather than a crash or a catastrophic backtrack.
    """
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty phrase, for example "
                         "\"POSISI KEUANGAN\" or \"issued and fully paid\"")
    limit = args.get("max_hits", 10)
    try:
        limit = max(1, min(MAX_HITS, int(limit)))
    except (TypeError, ValueError):
        limit = 10

    pattern = re.compile(re.escape(query.strip()), re.IGNORECASE)
    hits, truncated = [], False
    for n, text in sorted(ctx.all_texts().items()):
        for line in (text or "").split("\n"):
            match = pattern.search(line)
            if not match:
                continue
            start = max(0, match.start() - CONTEXT_CHARS)
            hits.append({"page": n + 1,
                         "line": " ".join(line[start:match.end() + CONTEXT_CHARS].split())})
            break                      # one hit per page: the page is what is being chosen
        if len(hits) >= limit:
            truncated = True
            break
    return ToolResult(payload={"query": query, "hits": hits, "truncated": truncated,
                               "note": ("nothing found; try the other language, or a "
                                        "shorter phrase") if not hits else None},
                      meta={"hits": len(hits)})


def _one_page_text(ctx: ToolContext, index: int, condensed: bool) -> dict:
    from pdftext import text_layer_usable
    raw = ctx.page_text(index)
    text = condense_page_text(raw) if condensed is not False else raw
    note = None
    if not raw.strip():
        note = "this page has no readable text; try read_page_image"
    elif not text_layer_usable(raw):
        note = "this page's text layer was unreadable and has been OCR'd"
    ctx.pages_opened.add(index + 1)
    return {"page": index + 1, "text": text[:PAGE_TEXT_CHARS], "chars": len(text),
            "truncated": len(text) > PAGE_TEXT_CHARS, "note": note}


def read_page_text(ctx: ToolContext, args: dict, budget=None) -> ToolResult:
    """The text of one page or several, with lines that cannot carry a figure removed.

    Several, because a statement spans two or three consecutive pages and reading them
    one per turn spends a step on each. On the first real pass that was four of the
    thirteen steps one filing used, and the filing that ran out of budget ran out while
    still looking for the shareholder table.
    """
    wanted = args.get("pages")
    if wanted is None:
        wanted = [args.get("page")]
    elif not isinstance(wanted, list):
        wanted = [wanted]
    if not wanted or all(p is None for p in wanted):
        raise ValueError(f"give a page, or a list of pages, between 1 and {ctx.total_pages}")
    if len(wanted) > MAX_PAGES_PER_READ:
        raise ValueError(f"at most {MAX_PAGES_PER_READ} pages at a time, got {len(wanted)}")

    indexes = [_page_index(ctx, p) for p in wanted]
    fresh = {i + 1 for i in indexes} - ctx.pages_opened
    if (budget is not None and fresh
            and len(ctx.pages_opened) + len(fresh) > budget.max_text_pages):
        return ToolResult(
            payload={"error": f"text budget exhausted ({len(ctx.pages_opened)} of "
                              f"{budget.max_text_pages} pages read); answer from the pages "
                              f"you already have, or call finish"},
            error_kind="budget")

    condensed = args.get("condensed", True)
    read = [_one_page_text(ctx, index, condensed) for index in indexes]
    payload = read[0] if len(read) == 1 else {"pages": read}
    return ToolResult(payload=payload,
                      meta={"chars": sum(page["chars"] for page in read),
                            "pages": len(read)})


def read_page_image(ctx: ToolContext, args: dict, budget=None) -> ToolResult:
    """Render one page and look at it. Roughly fifteen times the cost of its text."""
    import base64
    index = _page_index(ctx, args.get("page"))
    page = index + 1
    if (budget is not None and page not in ctx.pages_rendered
            and len(ctx.pages_rendered) >= budget.max_images):
        return ToolResult(
            payload={"error": f"image budget exhausted ({len(ctx.pages_rendered)} of "
                              f"{budget.max_images} pages rendered); answer from the text "
                              f"you already have"},
            error_kind="budget")

    if page not in ctx.images:
        ctx.images[page] = base64.standard_b64encode(
            render_pdf_page_to_image(ctx.pdf_path, index)).decode()
    ctx.pages_rendered.add(page)
    return ToolResult(payload={"page": page, "status": "rendered"},
                      image_b64=ctx.images[page], meta={"page": page})


FIND_SCALES = (("FULL", 1), ("THOUSANDS", 1_000), ("MILLIONS", 1_000_000))
_RELATED_TEXTS: dict = {}          # path -> {page: text}; other filings, read once per run


def number_hits(texts: dict, value: float, fx_rate: Optional[float] = None,
                max_hits: int = 8) -> list:
    """Every place a full-Rupiah figure is printed, at any scale it could be printed at.

    A label is stored in full Rupiah; the filing prints it in thousands, or millions, or
    in US dollars. So the figure is searched for as each of those, and a hit says which
    reading found it -- "printed in thousands on page 7" is itself evidence.
    """
    from numfmt import grouped_numbers
    readings = [(scale, mult, "IDR", 1.0) for scale, mult in FIND_SCALES]
    if fx_rate:
        readings += [(scale, mult, "USD", fx_rate) for scale, mult in FIND_SCALES]
    hits = []
    for n, text in sorted(texts.items()):
        for line in (text or "").split("\n"):
            numbers = grouped_numbers(line)
            if not numbers:
                continue
            for scale, mult, currency, rate in readings:
                target = abs(value) / (mult * rate)
                # Half a printed unit: a figure rounded to thousands is still that figure.
                slack = 0.5 if currency == "IDR" else max(0.5, target * 2e-3)
                if target >= 1 and any(abs(abs(v) - target) <= slack for v in numbers):
                    hits.append({"page": n + 1, "scale": scale, "currency": currency,
                                 "line": " ".join(line.split())[:160]})
                    break
            if len(hits) >= max_hits:
                return hits
    return hits


def find_number(ctx: ToolContext, args: dict) -> ToolResult:
    """Where is this figure printed -- in this filing, or in the issuer's others?

    Deterministic: no model reads anything. It is the tool that proved GTRA's labels were
    shifted: the figure the sheet held for Q4 2025 was printed only in the Q2 2026 filing.
    """
    raw = args.get("value")
    try:
        value = float(str(raw).replace(",", "").replace("_", "")) if not isinstance(
            raw, (int, float)) else float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"value must be a number in full units (e.g. 18672839545), "
                         f"got {raw!r}")
    scope = str(args.get("scope") or "filing").lower()
    if scope not in ("filing", "issuer"):
        raise ValueError("scope must be 'filing' or 'issuer'")

    found = [{"filing": "this filing", **hit}
             for hit in number_hits(ctx.all_texts(), value, ctx.fx_rate)]
    if scope == "issuer":
        from pdftext import page_texts
        for label, path in sorted(ctx.related.items()):
            key = str(path)
            if key not in _RELATED_TEXTS:
                _RELATED_TEXTS[key] = page_texts(key, use_ocr=False)
            found += [{"filing": label, **hit}
                      for hit in number_hits(_RELATED_TEXTS[key], value, ctx.fx_rate,
                                             max_hits=4)]
    return ToolResult(payload={"value": value, "scope": scope, "hits": found[:MAX_HITS],
                               "note": None if found else
                               "printed nowhere searched, at full, thousand or million scale"},
                      meta={"hits": len(found)})


NAVIGATION = {"list_pages": list_pages, "search_text": search_text,
              "read_page_text": read_page_text, "read_page_image": read_page_image,
              "find_number": find_number}


def run_tool(ctx: ToolContext, name: str, args: dict, budget=None) -> ToolResult:
    """Dispatch one navigation tool. Never raises; every failure is a payload."""
    handler = NAVIGATION.get(name)
    if handler is None:
        return ToolResult(payload={"error": f"unknown tool {name!r}",
                                   "available": sorted(NAVIGATION)},
                          error_kind="unknown_tool")
    started = time.time()
    try:
        if handler in (read_page_text, read_page_image):
            result = handler(ctx, args or {}, budget=budget)
        else:
            result = handler(ctx, args or {})
    except ValueError as exc:
        kind = "page_out_of_range" if "does not exist" in str(exc) else "malformed_args"
        return ToolResult(payload={"error": str(exc)}, error_kind=kind)
    except Exception as exc:
        # A tool that breaks is a fact about this filing, not a reason to lose it.
        return ToolResult(payload={"error": f"{name} failed: {type(exc).__name__}: {exc}"},
                          error_kind="tool_exception")
    result.meta["ms"] = int((time.time() - started) * 1000)
    return result


# --- the schemas ------------------------------------------------------------------

# The three metadata fields validate.py rejects anything else for. Measured, not
# guessed: on the first real agent pass the model answered reporting_scale "1000", the
# validator failed it as an unrecognised scale, and the confidence layer withdrew it --
# on both filings. An enum in the schema is where that belongs, because it is the model's
# own tooling that then refuses the wrong shape, one turn earlier and for free.
_ENUMS = {
    "reporting_scale": ["FULL", "THOUSANDS", "MILLIONS", "BILLIONS"],
    "currency": ["IDR", "USD"],
    "statement_scope": ["CONSOLIDATED", "PARENT_ONLY"],
}


def _json_type(field_name: str) -> dict:
    """One source of truth for field types: schema.FIELD_TYPES."""
    if field_name in _ENUMS:
        return {"type": "string", "enum": _ENUMS[field_name],
                "description": {"reporting_scale":
                                "The scale printed in the header: 'dalam ribuan' is "
                                "THOUSANDS, 'dalam jutaan' MILLIONS, a currency with no "
                                "scale word FULL. Never a number.",
                                "currency": "As printed: Rupiah is IDR, Dolar AS is USD.",
                                "statement_scope":
                                "CONSOLIDATED for Konsolidasian, else PARENT_ONLY."
                                }[field_name]}
    declared = FIELD_TYPES.get(field_name, TEXT)
    if declared is NUMBER:
        return {"type": "number"}
    if declared is NUMBER_LIST:
        return {"type": "array", "items": {"type": "number"}}
    return {"type": "string"}


def report_tool_schemas() -> list:
    """One report tool per statement group, carrying exactly that group's fields.

    Generated from GROUP_FIELDS so the agent is asked the same narrow questions the
    pipeline asks. That is what keeps the experiment about control flow: if the agent
    were asked for all nineteen fields at once, a difference in score would confound the
    loop with the prompt width the pipeline was deliberately narrowed away from.

    No report_equity -- GROUP_FIELDS["equity"] is empty, and a tool for it is a step
    spent on nothing.
    """
    from extract import ALWAYS, GROUP_FIELDS

    tools = []
    for group, fields in GROUP_FIELDS.items():
        if not fields:
            continue
        properties = {name: _json_type(name) for name in list(fields) + list(ALWAYS)}
        properties["pages"] = {
            "type": "array", "items": {"type": "integer"},
            "description": "The 1-indexed pages you READ these figures from. Grounding "
                           "checks the figures against these pages, so a page you did "
                           "not read is a figure that will be withdrawn."}
        tools.append({
            "name": f"report_{group}",
            "description": (f"Report the figures printed on the {group.replace('_', ' ')}. "
                            f"Copy each one exactly as printed: do not add, subtract, "
                            f"scale or convert anything. Omit any field this statement "
                            f"does not print."),
            "parameters": {"type": "object", "properties": properties,
                           "required": ["pages"]},
        })
    return tools


FINISH_TOOL = {
    "name": "finish",
    "description": ("Stop. Call this when every statement you can find has been reported, "
                    "or when one is genuinely not in this filing -- say which."),
    "parameters": {"type": "object",
                   "properties": {"reason": {"type": "string"},
                                  "not_found": {"type": "array",
                                                "items": {"type": "string"}}},
                   "required": ["reason"]},
}


def navigation_schemas(budget=None) -> list:
    """The four ways to look at the filing. The budget is stated in the description,
    where the model reads about the tool, rather than discovered by being refused."""
    images = getattr(budget, "max_images", None)
    pages = getattr(budget, "max_text_pages", None)
    return [
        {"name": "list_pages",
         "description": ("The title region of every page, so you can see the shape of the "
                         "filing before opening anything. Call this first. Calling it "
                         "twice returns the same thing."),
         "parameters": {"type": "object", "properties": {}}},
        {"name": "search_text",
         "description": ("Find where a phrase appears in the filing. Use this when a "
                         "statement's title is not visible in list_pages -- some filings "
                         "push the title behind a translation notice or split it across "
                         "bilingual columns, and some put the shareholder table a hundred "
                         "pages after the statements."),
         "parameters": {"type": "object",
                        "properties": {
                            "query": {"type": "string",
                                      "description": "A phrase, case-insensitive. Try "
                                                     "Indonesian and English."},
                            "max_hits": {"type": "integer",
                                         "description": f"Default 10, maximum {MAX_HITS}."}},
                        "required": ["query"]}},
        {"name": "read_page_text",
         "description": ("The text of one page or several, with lines that cannot carry a "
                         "figure removed. This is the cheap way to read, and reading a "
                         f"statement's pages together costs one step instead of one each "
                         f"(up to {MAX_PAGES_PER_READ} at a time)."
                         + (f" You may read at most {pages} pages in total." if pages else "")),
         "parameters": {"type": "object",
                        "properties": {"pages": {"type": "array",
                                                 "items": {"type": "integer"},
                                                 "description": "1-indexed page numbers, "
                                                                "e.g. [13, 14, 15]."},
                                       "page": {"type": "integer",
                                                "description": "A single 1-indexed page."},
                                       "condensed": {"type": "boolean",
                                                     "description": "Default true."}},
                        "required": []}},
        {"name": "read_page_image",
         "description": ("Render one page and look at it. Costs roughly fifteen times "
                         "what read_page_text costs for the same page; use it when the "
                         "text is unreadable or the columns are genuinely ambiguous."
                         + (f" You may render at most {images} pages." if images else "")),
         "parameters": {"type": "object",
                        "properties": {"page": {"type": "integer",
                                                "description": "1-indexed."}},
                        "required": ["page"]}},
    ]


def all_schemas(budget=None) -> list:
    return navigation_schemas(budget) + report_tool_schemas() + [FINISH_TOOL]
