"""
Per-field confidence, and the decision to abstain.

The score is NOT the model's own estimate of itself -- self-reported confidence is
poorly calibrated and costs nothing to inflate. It is computed from three signals
the system can check independently:

  grounding    Does this exact figure appear in the filing's text layer? A number
               the document does not contain was invented. This is the only direct
               anti-hallucination test available, and it is cheap because the text
               layer is already read for page selection.

  validation   Does the field appear in a failing structural rule (src/validate.py)?
               A balance sheet that does not balance implicates the fields in it.

  derivation   Was the value computed from components rather than read whole? A
               derived value inherits the weaker of its inputs -- it cannot be more
               trustworthy than the rows it came from.

Fields below ABSTAIN_THRESHOLD are set to None and recorded as abstentions. The
evaluator scores an abstention as `missed`, never as `wrong`: declining and
inventing are different behaviours and are counted separately.
"""

import os
import re
from dataclasses import dataclass, field as dc_field
from typing import Optional

ABSTAIN_THRESHOLD = float(os.getenv("CONFIDENCE_ABSTAIN_THRESHOLD", "0.55"))

# Weights sum to 1.0. Grounding dominates: a figure absent from the document is
# wrong regardless of how consistent the rest of the extraction looks.
W_GROUNDING = 0.60
W_VALIDATION = 0.25
W_DERIVATION = 0.15

# A field contradicted by a structural rule is capped below the abstention
# threshold. An error-severity rule is not a hint to weigh against other evidence --
# it is a demonstration that the value disagrees with the document, and no amount of
# grounding elsewhere should let it through.
ERROR_CONFIDENCE_CAP = 0.50

DERIVED_FROM = {
    "utang_bank": ("utang_bank_jangka_pendek", "utang_bank_bagian_lancar"),
    "ekuitas": ("total_ekuitas", "kepentingan_non_pengendali"),
}

NON_NUMERIC = ("period_end_date", "currency", "reporting_scale", "statement_scope")


@dataclass
class FieldScore:
    field: str
    value: object
    confidence: float
    grounded: Optional[bool]          # None when the check could not be run
    abstained: bool = False
    reasons: list = dc_field(default_factory=list)


def _indonesian_forms(value: float) -> list:
    """How this figure could legitimately be printed in the filing.

    Both grouping conventions are generated, because IDX filers use both: ARCI and
    JPFA print "694.671.337" (dot), EMAS prints "80,322,232" (comma, following the
    English column it sits beside). Checking only one convention reports every figure
    in the other kind of filing as absent, and the abstention layer then discards a
    perfectly good extraction -- which is exactly what EMAS did.

    Generating both is safe rather than lax: a comma-grouped string does not occur in
    a dot-grouped document, so the extra form cannot match the wrong number.
    """
    magnitude = abs(int(round(value)))
    with_commas = f"{magnitude:,}"
    with_dots = with_commas.replace(",", ".")

    forms = [with_dots, with_commas, str(magnitude)]
    if value < 0:
        forms += [f"({with_dots})", f"-{with_dots}",
                  f"({with_commas})", f"-{with_commas}"]
    return forms


# PDF text layers routinely break a number across a space -- CPIN's extracts
# "14.406" as "1 4.406". Searching the raw text alone reports the figure as absent
# and the guard then abstains on a value that is printed perfectly well. Removing
# spaces BETWEEN DIGITS repairs that without touching anything else; adjacent columns
# may run together ("26.340.959 25.149.999" -> "26.340.95925.149.999") but a
# substring search still finds either figure inside the join.
_DIGIT_GAP = re.compile(r"(?<=\d)[ \t]+(?=\d)")


def check_grounding(value, document_text: str) -> Optional[bool]:
    """Is this value printed in the document? None if it cannot be checked."""
    if not document_text or value is None:
        return None
    if isinstance(value, list):
        # A list of components (per-class share counts): grounded only if EVERY one
        # of them is printed. One invented class would otherwise ride along.
        checks = [check_grounding(v, document_text) for v in value]
        if not checks or any(c is False for c in checks):
            return False
        return None if any(c is None for c in checks) else True
    if isinstance(value, str):
        return None          # dates are reformatted to ISO; not comparable verbatim
    try:
        forms = _indonesian_forms(float(value))
    except (TypeError, ValueError):
        return None

    if any(form in document_text for form in forms):
        return True
    # Second pass over a copy with intra-number spacing repaired.
    return any(form in _DIGIT_GAP.sub("", document_text) for form in forms)


def _derived_from(extraction) -> dict:
    """Which fields were computed rather than read, for THIS extraction.

    total_share is only derived when the issuer splits its share capital into classes
    (JPFA does, ARCI does not). Deriving it unconditionally would grade a directly
    read count against components that are not there.
    """
    derived = dict(DERIVED_FROM)
    if getattr(extraction, "total_share_components", None):
        derived["total_share"] = ("total_share_components",)
    return derived


def score_extraction(extraction, document_text: str, issues: list) -> dict:
    """Score every populated field. Returns {field: FieldScore}."""
    implicated = {f for issue in issues for f in issue.fields if issue.severity == "error"}
    warned = {f for issue in issues for f in issue.fields if issue.severity == "warning"}
    DERIVED = _derived_from(extraction)

    scores = {}
    for name in extraction.__dataclass_fields__:
        value = getattr(extraction, name)
        if value is None:
            continue

        reasons = []

        if name in NON_NUMERIC:
            grounded = None
            grounding_score = 0.75          # unverifiable, neither trusted nor doubted
            reasons.append("not verifiable verbatim")
        else:
            grounded = check_grounding(value, document_text)
            if grounded is True:
                grounding_score = 1.0
            elif grounded is False:
                grounding_score = 0.0
                reasons.append("value does not appear in the document")
            else:
                grounding_score = 0.5
                reasons.append("no text layer to verify against")

        if name in implicated:
            validation_score = 0.0
            reasons.append("implicated in a failing validation rule")
        elif name in warned:
            validation_score = 0.5
            reasons.append("implicated in a validation warning")
        else:
            validation_score = 1.0

        if name in DERIVED:
            parts = [scores.get(p) for p in DERIVED[name]]
            known = [p.confidence for p in parts if p]
            # A derived value is only as good as its weakest input.
            derivation_score = min(known) if known else 0.4
            if not known:
                reasons.append("derived, but components were not scored")
            else:
                reasons.append(f"derived from {', '.join(DERIVED[name])}")
        else:
            derivation_score = 1.0

        confidence = (W_GROUNDING * grounding_score
                      + W_VALIDATION * validation_score
                      + W_DERIVATION * derivation_score)

        if name in implicated:
            confidence = min(confidence, ERROR_CONFIDENCE_CAP)

        scores[name] = FieldScore(name, value, round(confidence, 3), grounded,
                                  reasons=reasons)

    # Derived values are a special case for grounding. utang_bank is a SUM, so it
    # is correctly absent from the document -- testing it verbatim would punish the
    # right answer. Grade it on the rows it was computed from instead, which is what
    # actually has to be read correctly.
    for name, parts in DERIVED.items():
        if name not in scores:
            continue
        known = [scores[p] for p in parts if p in scores]
        if not known:
            continue
        s = scores[name]
        inherited = min(p.confidence for p in known)
        grounding_score = min(
            1.0 if p.grounded else 0.5 if p.grounded is None else 0.0 for p in known)
        validation_score = 0.0 if name in implicated else (0.5 if name in warned else 1.0)
        derived_confidence = (W_GROUNDING * grounding_score
                              + W_VALIDATION * validation_score
                              + W_DERIVATION * inherited)
        if name in implicated:
            derived_confidence = min(derived_confidence, ERROR_CONFIDENCE_CAP)
        s.confidence = round(derived_confidence, 3)
        s.grounded = None
        s.reasons = [f"derived from {', '.join(parts)}; graded on those rows"]
        if validation_score == 0.0:
            s.reasons.append("implicated in a failing validation rule")

    return scores


def apply_abstention(extraction, scores: dict, threshold: float = None) -> list:
    """Blank fields the system is not confident enough to assert. Returns their names.

    Setting the value to None is deliberate: a low-confidence number that stays in
    the output will be used by something downstream. Abstention has to remove the
    value, not merely annotate it.
    """
    threshold = ABSTAIN_THRESHOLD if threshold is None else threshold
    abstained = []
    for name, score in scores.items():
        if score.confidence < threshold:
            setattr(extraction, name, None)
            score.abstained = True
            abstained.append(name)
    return abstained
