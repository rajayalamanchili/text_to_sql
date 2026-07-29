"""LLM-assisted classification pass (FR-003, research.md §3).

Runs only for columns whose heuristic-pass confidence lands below the
auto-approval threshold, and only ever on masked input
(`MaskedColumnProfile`, T021) — never a raw value (Constitution
Principle I). `render_prompt` builds the prompt from that profile alone,
so it can never contain a value fragment.

The concrete model provider is injected via `LLMClassifierClient`, a
small structural protocol (mirrors `AuditLogSink` in
`services/audit/audit_log.py`), so this module never hardcodes a vendor
SDK — tech-stack.md requires a provider-agnostic interface (Anthropic
primary, OpenAI secondary/configurable); no concrete adapter exists yet
in this milestone's task sequence.

The LLM's rationale is stored for audit only and is never treated as an
enforcement input (Constitution Principle I) — nothing downstream of
this module may branch on `LLMResult.rationale`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from src.models.column_classification import Classification
from src.services.classification.masking import MaskedColumnProfile

MAX_LLM_CONFIDENCE = 0.99  # a single LLM call never claims absolute (1.0) certainty


class LLMClassificationResponse(BaseModel):
    """Raw model output, before this module's clamping is applied."""

    classification: Classification
    confidence: float
    rationale: str


@runtime_checkable
class LLMClassifierClient(Protocol):
    """Structural interface any concrete provider adapter (Anthropic,
    OpenAI, ...) implements. Callers depend only on this Protocol, never
    a vendor SDK type."""

    async def classify_column(self, profile: MaskedColumnProfile) -> LLMClassificationResponse: ...


class LLMResult(BaseModel):
    """One column's LLM-assisted-pass proposal (research.md §3), clamped
    and ready for confidence combination (T023)."""

    model_config = {"frozen": True}

    classification: Classification
    score: float
    rationale: str  # audit-only — never an enforcement input (Principle I)


def render_prompt(profile: MaskedColumnProfile) -> str:
    """Deterministically render the LLM prompt from `profile` alone, so
    the prompt can never contain a raw value — only the masked fields
    research.md §3 specifies."""
    return (
        "Classify this database column's data sensitivity.\n"
        f"Column name: {profile.column_name}\n"
        f"Data type: {profile.data_type}\n"
        f"Cardinality ratio (distinct/total): {profile.cardinality_ratio:.4f}\n"
        f"Value length: min={profile.min_length} max={profile.max_length} "
        f"avg={profile.avg_length:.1f}\n"
        f"Generalized value patterns (not real values): {profile.pattern_classes}\n"
        "Respond with exactly one classification "
        "(pii_direct, pii_indirect, sensitive_category, business, or unclassified), "
        "a confidence between 0 and 1, and a short rationale."
    )


async def classify_with_llm(profile: MaskedColumnProfile, client: LLMClassifierClient) -> LLMResult:
    """Run the LLM-assisted pass for one column, on masked input only
    (FR-003)."""
    response = await client.classify_column(profile)
    score = max(0.0, min(response.confidence, MAX_LLM_CONFIDENCE))
    return LLMResult(
        classification=response.classification,
        score=score,
        rationale=response.rationale,
    )
