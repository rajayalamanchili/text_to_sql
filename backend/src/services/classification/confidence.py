"""Confidence combination logic (FR-002, FR-003, FR-005, research.md §4).

Combines a heuristic-pass proposal with an optional LLM-pass proposal
into one `CombinedResult`, per a fixed, fully auditable rule that never
lets an optimistic pass silently outvote a conservative one:

- If the LLM pass didn't run (heuristic alone cleared the auto-approval
  threshold), the combined result is just the heuristic's.
- If both passes agree on classification, combined confidence is the
  max of the two.
- If they disagree, the more sensitive category always wins — regardless
  of either confidence score — by the fixed risk order `business <
  pii_indirect < sensitive_category < pii_direct` (`unclassified` never
  wins), and combined confidence is the min of the two, biasing toward
  human review rather than auto-approval (Constitution Principle II/III).
"""

from __future__ import annotations

from pydantic import BaseModel

from src.models.column_classification import Classification, ClassificationSource
from src.services.classification.heuristic_classifier import HeuristicResult
from src.services.classification.llm_classifier import LLMResult

_RISK_ORDER: dict[Classification, int] = {
    Classification.BUSINESS: 0,
    Classification.PII_INDIRECT: 1,
    Classification.SENSITIVE_CATEGORY: 2,
    Classification.PII_DIRECT: 3,
}
# `unclassified` is deliberately absent from _RISK_ORDER — _rank's -1
# fallback keeps it below every real category, so it is never picked as
# the "more sensitive" winner (research.md §4).


class CombinedResult(BaseModel):
    """The classification pipeline's combined output for one column,
    ready to persist as a `ColumnClassification` (data-model.md)."""

    model_config = {"frozen": True}

    classification: Classification
    confidence: float
    source: ClassificationSource


def combine_confidence(heuristic: HeuristicResult, llm: LLMResult | None) -> CombinedResult:
    """Combine a heuristic proposal with an optional LLM proposal
    (research.md §4)."""
    if llm is None:
        return CombinedResult(
            classification=heuristic.classification,
            confidence=heuristic.score,
            source=ClassificationSource.HEURISTIC,
        )

    if heuristic.classification == llm.classification:
        return CombinedResult(
            classification=heuristic.classification,
            confidence=max(heuristic.score, llm.score),
            source=ClassificationSource.LLM,
        )

    if _rank(heuristic.classification) >= _rank(llm.classification):
        winner, winner_source = heuristic.classification, ClassificationSource.HEURISTIC
    else:
        winner, winner_source = llm.classification, ClassificationSource.LLM

    return CombinedResult(
        classification=winner,
        confidence=min(heuristic.score, llm.score),
        source=winner_source,
    )


def _rank(classification: Classification) -> int:
    return _RISK_ORDER.get(classification, -1)
