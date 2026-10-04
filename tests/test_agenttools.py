#!/usr/bin/env python3
"""
The agent's tools, before there is an agent.

The first test in this file is the one the whole branch rests on. The repo argues, at
README:651, that "the pages are known before any model runs, so there is nothing for an
agent to decide". That is true exactly as far as the deterministic page selector is
true — and the selector needed four hand-written patches because some filings put their
statement titles outside the 250-character region it reads.

If a plain full-text search finds those titles, the agent has something real to decide.
If it does not, the README is right and this branch is theatre. So that test is written
first, and it runs against a real filing whenever the archive is present.

No model, no API key, no network.

Run:  python -m pytest tests/test_agenttools.py -v
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import page_select as ps                                   # noqa: E402
from agenttools import (AgentBudget, ToolContext, all_schemas,  # noqa: E402
                        read_page_image, read_page_text, run_tool, search_text)

ARCHIVE = Path.home() / "FinancialReport"
ARCI = ROOT / "data" / "raw" / "Q1_2022_ARCI.pdf"

# The head of LSIP Q4 2025 page 15, copied from the filing. The title starts at
# character 240 and runs past 250, so the old region read "LAPORAN POSIS" and matched
# nothing. Both company names appear twice because the page is bilingual in two columns.
NOTICE = ("The original consolidated financial statements included herein are in "
          "Indonesian language. PT PERUSAHAAN PERKEBUNAN PT PERUSAHAAN PERKEBUNAN "
          "LONDON SUMATRA INDONESIA TBK LONDON SUMATRA INDONESIA TBK DAN ENTITAS "
          "ANAKNYA AND ITS SUBSIDIARIES ")


def _fake_ctx(texts: dict) -> ToolContext:
    """A context over supplied page text, so a tool can be tested without a PDF."""
    ctx = ToolContext(pdf_path="none.pdf", total_pages=len(texts))
    ctx.texts = texts
    ctx.titles = {n: (t or "")[:400] for n, t in texts.items()}
    return ctx


# --- the test the branch rests on -------------------------------------------------

def test_search_finds_a_title_the_title_region_cannot_see():
    """A phrase search has no 250-character region, so the four patches buy it nothing.

    The synthetic half reproduces the LSIP layout exactly: a translation notice long
    enough that the statement title starts past character 250. The old selector saw the
    notice and nothing else, and all eighteen LSIP filings fell back to "the first ten
    pages" -- a cover, a directors' statement and seven pages of auditor's report.
    """
    body = (NOTICE + "LAPORAN POSISI KEUANGAN CONSOLIDATED STATEMENT OF "
            "KONSOLIDASIAN FINANCIAL POSITION\nTotal aset 1.234.567")
    assert 230 < len(NOTICE) < 250, "the title must start just past the old region"
    texts = {0: "DAFTAR ISI", 1: body}

    # The selector as it was BEFORE the patches: the raw first 250 characters.
    assert not ps._MARKER_RE.search(body[:250]), "the old region cannot see this title"
    # And as it is now, with the notice stripped -- the patch that fixed it.
    assert ps._is_statement_title(ps._title_head(body))

    hits = search_text(_fake_ctx(texts), {"query": "POSISI KEUANGAN"}).payload["hits"]
    assert [h["page"] for h in hits] == [2], "search finds it with no rule about notices"


@pytest.mark.skipif(not (ARCHIVE / "LSIP" / "Q4_2025_LSIP.pdf").exists(),
                    reason="the filing archive is not on this machine")
def test_search_finds_the_real_statements_the_old_region_missed():
    """LSIP Q4 2025, measured rather than imagined.

    The unpatched title region finds ZERO statement pages in this filing. The patched
    one finds pages 14-19. A search for a SHORT phrase finds 14 and 15 -- the balance
    sheet -- with no rule about translation notices at all.

    The phrase has to be short: "LAPORAN POSISI KEUANGAN KONSOLIDASIAN" never appears
    contiguously, because the Indonesian and English columns interleave. That is a fact
    about these filings the agent's prompt has to carry, and it is recorded here.
    """
    from pdftext import page_titles
    pdf = ARCHIVE / "LSIP" / "Q4_2025_LSIP.pdf"
    titles = page_titles(str(pdf))

    unpatched = [n for n, t in titles.items() if ps._MARKER_RE.search((t or "")[:250])]
    patched = [n + 1 for n, t in titles.items()
               if ps._is_statement_title(ps._title_head(t or ""))]
    assert unpatched == [], "this is the filing that fell back to its first ten pages"
    assert patched, "the patched selector does find them"

    ctx = ToolContext.for_pdf(str(pdf))
    found = [h["page"] for h in
             search_text(ctx, {"query": "POSISI KEUANGAN", "max_hits": 8}).payload["hits"]]
    assert set(found) & set(patched), "search reaches pages the old region could not"

    whole = [h["page"] for h in search_text(
        ctx, {"query": "LAPORAN POSISI KEUANGAN KONSOLIDASIAN"}).payload["hits"]]
    assert not (set(whole) & set(patched)), \
        "the full title never appears contiguously -- the prompt must ask for short phrases"


# --- every failure is a payload ---------------------------------------------------

def test_a_page_outside_the_document_is_refused_with_its_range():
    """A model told "invalid page" asks for the same page again."""
    result = run_tool(_fake_ctx({0: "a", 1: "b"}), "read_page_text", {"page": 300})
    assert result.error_kind == "page_out_of_range"
    assert "300 does not exist" in result.payload["error"]
    assert "(1-2)" in result.payload["error"]


def test_a_malformed_page_argument_is_refused_not_raised():
    result = run_tool(_fake_ctx({0: "a"}), "read_page_text", {"page": "five"})
    assert result.error_kind == "malformed_args"
    assert "whole number between 1 and 1" in result.payload["error"]


def test_an_unknown_tool_is_answered_with_the_ones_that_exist():
    result = run_tool(_fake_ctx({0: "a"}), "read_pdf", {})
    assert result.error_kind == "unknown_tool"
    assert "read_page_text" in result.payload["available"]


def test_a_search_phrase_is_escaped_rather_than_compiled():
    """The model supplies phrases, never patterns. An unbalanced bracket is a bracket."""
    ctx = _fake_ctx({0: "Modal saham (Seri A) 1.000", 1: "nothing here"})
    result = run_tool(ctx, "search_text", {"query": "(Seri A"})
    assert result.error_kind is None
    assert [h["page"] for h in result.payload["hits"]] == [1]


def test_an_empty_query_is_refused_with_an_example():
    result = run_tool(_fake_ctx({0: "a"}), "search_text", {"query": "   "})
    assert result.error_kind == "malformed_args"
    assert "POSISI KEUANGAN" in result.payload["error"]


# --- budgets ----------------------------------------------------------------------

def test_the_text_budget_refuses_the_tool_but_not_the_run():
    """A refusal budget ends a tool call, never the loop: the agent can still finish."""
    ctx = _fake_ctx({n: f"page {n}" for n in range(10)})
    budget = AgentBudget(max_text_pages=2)
    for page in (1, 2):
        assert read_page_text(ctx, {"page": page}, budget=budget).error_kind is None
    refused = read_page_text(ctx, {"page": 3}, budget=budget)
    assert refused.error_kind == "budget"
    assert "text budget exhausted" in refused.payload["error"]
    # A page already read is not a new page, so re-reading it is still allowed.
    assert read_page_text(ctx, {"page": 1}, budget=budget).error_kind is None


@pytest.mark.skipif(not ARCI.exists(), reason="Q1_2022_ARCI.pdf not present")
def test_the_image_budget_counts_pages_not_calls():
    ctx = ToolContext.for_pdf(str(ARCI))
    budget = AgentBudget(max_images=1)
    first = read_page_image(ctx, {"page": 5}, budget=budget)
    assert first.image_b64 and first.error_kind is None
    assert read_page_image(ctx, {"page": 5}, budget=budget).error_kind is None, \
        "the same page again is cached, not a second render"
    refused = read_page_image(ctx, {"page": 6}, budget=budget)
    assert refused.error_kind == "budget" and refused.image_b64 is None


# --- the schemas ------------------------------------------------------------------

def test_the_report_tools_carry_exactly_their_own_group_s_fields():
    """Generated from GROUP_FIELDS, so the agent is asked the same narrow questions the
    pipeline asks. Asked for all nineteen fields at once, a score difference would
    confound the loop with the prompt width the pipeline was deliberately narrowed from.
    """
    from extract import ALWAYS, GROUP_FIELDS
    schemas = {t["name"]: t for t in all_schemas(AgentBudget())}

    assert "report_equity" not in schemas, "equity answers nothing; a tool for it is a wasted step"
    for group, fields in GROUP_FIELDS.items():
        if not fields:
            continue
        properties = schemas[f"report_{group}"]["parameters"]["properties"]
        assert set(properties) == set(fields) | set(ALWAYS) | {"pages"}
        assert schemas[f"report_{group}"]["parameters"]["required"] == ["pages"]

    balance = schemas["report_balance_sheet"]["parameters"]["properties"]
    assert balance["aset"] == {"type": "number"}
    assert balance["kas_components"] == {"type": "array", "items": {"type": "number"}}
    assert balance["period_end_date"]["type"] == "string"


def test_the_metadata_fields_are_enums_the_model_cannot_miss():
    """Measured, not guessed: on the first real pass the model answered reporting_scale
    "1000", the validator rejected it as an unrecognised scale, and the confidence layer
    withdrew the field on both filings. The schema is where that belongs."""
    schemas = {t["name"]: t for t in all_schemas(AgentBudget())}
    properties = schemas["report_balance_sheet"]["parameters"]["properties"]
    assert properties["reporting_scale"]["enum"] == ["FULL", "THOUSANDS", "MILLIONS",
                                                     "BILLIONS"]
    assert properties["currency"]["enum"] == ["IDR", "USD"]
    assert properties["statement_scope"]["enum"] == ["CONSOLIDATED", "PARENT_ONLY"]

    # The enum must be what the validator accepts, or the schema teaches a wrong answer
    # that then fails one layer later -- which is the bug this test was written from.
    from schema import FinancialStatementExtraction
    from validate import validate
    for scale in properties["reporting_scale"]["enum"]:
        issues = validate(FinancialStatementExtraction(currency="IDR", reporting_scale=scale))
        assert not any(i.rule == "reporting_scale" for i in issues), scale
    rejected = validate(FinancialStatementExtraction(currency="IDR", reporting_scale="1000"))
    assert any(i.rule == "reporting_scale" for i in rejected), "the observed wrong answer"


def test_several_pages_can_be_read_in_one_step():
    """A statement spans two or three pages. Reading them one per turn spent four of
    thirteen steps on one filing, and the filing that ran out of budget ran out while
    still looking for the shareholder table."""
    ctx = _fake_ctx({n: f"PAGE {n + 1} Total aset 1.111.111" for n in range(20)})
    result = read_page_text(ctx, {"pages": [13, 14, 15]})
    assert [p["page"] for p in result.payload["pages"]] == [13, 14, 15]
    assert result.meta["pages"] == 3
    assert ctx.pages_opened == {13, 14, 15}
    # One page still answers in the single-page shape, so nothing about it changed.
    assert read_page_text(ctx, {"page": 2}).payload["page"] == 2


def test_reading_more_pages_than_the_budget_allows_is_refused_as_a_whole():
    """Three pages when two remain is refused, not silently half-served."""
    ctx = _fake_ctx({n: f"page {n}" for n in range(20)})
    budget = AgentBudget(max_text_pages=2)
    refused = read_page_text(ctx, {"pages": [1, 2, 3]}, budget=budget)
    assert refused.error_kind == "budget"
    assert ctx.pages_opened == set(), "a refused read opens nothing"


def test_the_budget_is_stated_in_the_tool_the_model_reads():
    """A ceiling discovered by being refused costs a step to learn."""
    schemas = {t["name"]: t for t in all_schemas(AgentBudget(max_images=3, max_text_pages=9))}
    assert "at most 3 pages" in schemas["read_page_image"]["description"]
    assert "at most 9 pages in total" in schemas["read_page_text"]["description"]


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
