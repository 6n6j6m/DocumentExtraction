"""
Response shapes for the HTTP API.

These are pydantic models rather than plain dicts for one reason that matters: the
API is the contract a caller writes code against, and a contract that drifts silently
is worse than no contract. A typed response fails here, in this process, when a field
is renamed -- rather than at the caller's parser, a week later.

The models deliberately mirror what the pipeline already produces. Nothing is
computed here; a route handler that starts reshaping figures is a route handler that
has become a second implementation of the extractor.

One shape decision worth stating: abstentions are returned **explicitly**, both as the
list of names and as `abstained: true` on the field, even though the value itself is
already `null`. A caller cannot otherwise tell "the filing does not report this" from
"we read something and did not trust it" -- and those call for opposite responses. The
first is a fact about the document; the second is an invitation to look at the page.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FieldConfidence(BaseModel):
    """Why a field is or is not trusted."""
    confidence: float = Field(..., description="0-1, computed from grounding, "
                                               "validation and derivation")
    grounded: Optional[bool] = Field(None, description="True if the figure appears "
                                                       "verbatim in the document; "
                                                       "None if it could not be checked")
    abstained: bool = Field(False, description="Value was removed for being below "
                                               "the confidence threshold")
    reasons: List[str] = []
    withheld_value: Optional[Any] = Field(None, description="The figure abstention "
                                                            "removed, so the withdrawal "
                                                            "can be judged later")


class ValidationIssueModel(BaseModel):
    """A structural rule that fired, independent of any ground truth."""
    rule: str
    severity: str = Field(..., description="error = contradicts the document; "
                                           "warning = suspicious but possible")
    message: str
    fields: List[str] = Field(default_factory=list,
                              description="Fields implicated, so confidence can "
                                          "penalise precisely")


class CostModel(BaseModel):
    amount: Optional[float] = Field(None, description="null when no price is "
                                                      "configured for the model")
    currency: str = "USD"
    reason: Optional[str] = Field(None, description="Why amount is null")
    per_model: List[Dict[str, Any]] = []


class TokenCounts(BaseModel):
    input: Optional[int] = None
    output: Optional[int] = None


class UsageModel(BaseModel):
    """What this extraction cost, in calls, tokens, money and milliseconds."""
    llm_calls: int = 0
    tokens: TokenCounts = TokenCounts()
    latency_ms: Dict[str, int] = Field(default_factory=dict,
                                       description="Per stage: select_pages, "
                                                   "read_text, extract, assess")
    cost: CostModel = CostModel()
    notes: List[str] = []


class ExtractionResponse(BaseModel):
    """One filing, as printed. Conversion to Rupiah is the caller's business.

    The API returns figures in the currency and scale the filing itself uses. It does
    NOT normalise, because normalisation needs the filing's disclosed exchange rate
    and reporting scale, and folding it in here would put a second copy of that logic
    behind an HTTP boundary where the evaluation harness could not reach it. One
    implementation, in `normalize.py`, used by every caller.
    """
    filename: str
    pages_selected: List[int] = Field(default_factory=list,
                                      description="1-indexed, as a human would cite them")
    extraction: Dict[str, Any] = Field(..., description="Field values as printed in "
                                                        "the filing")
    confidence: Dict[str, FieldConfidence] = {}
    abstained: List[str] = []
    issues: List[ValidationIssueModel] = []
    usage: UsageModel = UsageModel()


class BatchItem(BaseModel):
    """One document's outcome inside a batch.

    `status` exists so a failure is data rather than an exception: a batch of fifty
    filings in which one PDF is corrupt should return forty-nine results and one
    explanation, not a 500 and nothing.
    """
    filename: str
    status: str = Field(..., description='"ok" or "error"')
    error: Optional[str] = None
    result: Optional[ExtractionResponse] = None


class BatchResponse(BaseModel):
    count: int
    ok: int
    failed: int
    results: List[BatchItem]
    usage: UsageModel = Field(UsageModel(), description="Totalled across the batch")


class HealthResponse(BaseModel):
    status: str
    provider: str
    model: str
    input_mode: str
    git_commit: Optional[str] = None
    provider_reachable: Optional[bool] = Field(
        None, description="null unless ?deep=true; a shallow check does not call out")
    checked: str = Field("shallow", description='"shallow" or "deep"')


class SchemaField(BaseModel):
    name: str
    type: str
    scored: bool = Field(..., description="Whether the evaluator scores this field")
    derived_from: Optional[List[str]] = Field(
        None, description="Present when the value is computed in code rather than read")
    description: Optional[str] = None


class SchemaResponse(BaseModel):
    """The field contract, served from the same definitions the extractor uses."""
    fields: List[SchemaField]
    scored_fields: List[str]
    abstain_threshold: float
