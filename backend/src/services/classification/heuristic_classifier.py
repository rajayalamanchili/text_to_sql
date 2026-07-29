"""Heuristic classification pass (FR-002, research.md §1-2).

Scores a column from three signals only — column name pattern, data
type, and cardinality ratio — never any row-level value (that is the
LLM-assisted pass's job, T022/T003, and even then only on masked
input). Confidence is capped at 0.95 so a heuristic match alone never
claims absolute certainty (research.md §1), and any string/text column
that doesn't confidently match a name pattern defaults to
`sensitive_category` at low confidence — never `business` — matching
Scenario 3's fail-closed guarantee at this layer itself (research.md §2,
Constitution Principle II).

The name-pattern dictionary is generic across domains and consulted by
this module, never branched on by domain name (Constitution Principle IV).
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from src.models.column_classification import Classification
from src.services.enumeration.schema_enumerator import ColumnSchema

MAX_HEURISTIC_CONFIDENCE = 0.95
NAME_MATCH_BASE_CONFIDENCE = 0.9
NAME_MATCH_HIGH_CARDINALITY_CONFIDENCE = 0.95
ADVERSARIAL_FREE_TEXT_CONFIDENCE = 0.5  # research.md §2: capped at <= 0.6
NO_SIGNAL_DEFAULT_CONFIDENCE = 0.7
_HIGH_CARDINALITY_THRESHOLD = 0.9

# Ordered most- to least-sensitive: the first pattern that matches a
# column name wins, so a name matching more than one category's regex
# (unlikely given these keyword sets, but not impossible) resolves to the
# more sensitive category rather than an arbitrary one (research.md §1).
_NAME_PATTERNS: tuple[tuple[re.Pattern[str], Classification], ...] = (
    (re.compile(r"ssn|social_security|name", re.IGNORECASE), Classification.PII_DIRECT),
    (re.compile(r"email|phone|address|zip", re.IGNORECASE), Classification.PII_INDIRECT),
    (
        re.compile(r"diagnosis|icd|cpt|account_number|balance", re.IGNORECASE),
        Classification.SENSITIVE_CATEGORY,
    ),
)

_STRING_TYPES = {"text", "character varying", "varchar", "character", "char", "citext"}


class HeuristicResult(BaseModel):
    """One column's heuristic-pass proposal (research.md §1)."""

    model_config = {"frozen": True}

    classification: Classification
    score: float
    signal: str  # human-readable rationale, audit-only — never an enforcement input


def classify_heuristically(column: ColumnSchema) -> HeuristicResult:
    """Run the heuristic pass for one column (FR-002)."""
    name_match = _match_name_pattern(column.column_name)
    if name_match is not None:
        return HeuristicResult(
            classification=name_match,
            score=_score_for_name_match(name_match, column),
            signal=f"name_pattern:{name_match.value}",
        )

    if _is_string_type(column.data_type):
        # No dictionary term matched and it's a string/text column: could
        # be free-text narrative (Scenario 3) or an unlabeled identifier —
        # either way, never guess `business` for it (research.md §2).
        return HeuristicResult(
            classification=Classification.SENSITIVE_CATEGORY,
            score=ADVERSARIAL_FREE_TEXT_CONFIDENCE,
            signal="adversarial_free_text_default",
        )

    return HeuristicResult(
        classification=Classification.BUSINESS,
        score=NO_SIGNAL_DEFAULT_CONFIDENCE,
        signal="no_signal_non_string_default",
    )


def _match_name_pattern(column_name: str) -> Classification | None:
    for pattern, classification in _NAME_PATTERNS:
        if pattern.search(column_name):
            return classification
    return None


def _score_for_name_match(classification: Classification, column: ColumnSchema) -> float:
    score = NAME_MATCH_BASE_CONFIDENCE
    if (
        classification == Classification.PII_DIRECT
        and _is_string_type(column.data_type)
        and column.cardinality_ratio >= _HIGH_CARDINALITY_THRESHOLD
    ):
        # Near-1.0 uniqueness on a string column is a strong pii_direct
        # signal (research.md §1, Scenario 1's patient_ssn) — boosts, but
        # still respects the global heuristic cap below.
        score = NAME_MATCH_HIGH_CARDINALITY_CONFIDENCE
    return min(score, MAX_HEURISTIC_CONFIDENCE)


def _is_string_type(data_type: str) -> bool:
    return data_type.lower() in _STRING_TYPES
