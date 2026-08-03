"""`ColumnClassification` model (data-model.md#ColumnClassification).

Represents the classification state of a single column at a point in
time. `confidence` is the *combined* score (research.md §4) that gates
auto-approval (FR-005) — never a raw heuristic or LLM score alone.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

AUTO_APPROVAL_CONFIDENCE_THRESHOLD = 0.85


class Classification(StrEnum):
    PII_DIRECT = "pii_direct"
    PII_INDIRECT = "pii_indirect"
    SENSITIVE_CATEGORY = "sensitive_category"
    BUSINESS = "business"
    UNCLASSIFIED = "unclassified"


class ClassificationSource(StrEnum):
    HEURISTIC = "heuristic"
    LLM = "llm"
    HUMAN = "human"


class ClassificationStatus(StrEnum):
    AUTO_APPROVED = "auto_approved"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ColumnClassification(BaseModel):
    """One column's classification record (data-model.md#ColumnClassification)."""

    id: UUID
    domain: str
    table_name: str
    column_name: str
    data_type: str
    cardinality_ratio: float = Field(ge=0.0, le=1.0)
    classification: Classification
    heuristic_score: float | None = Field(default=None, ge=0.0, le=1.0)
    llm_score: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    source: ClassificationSource
    status: ClassificationStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    llm_rationale: str | None = None

    @model_validator(mode="after")
    def _auto_approved_requires_confident_score(self) -> ColumnClassification:
        if (
            self.status == ClassificationStatus.AUTO_APPROVED
            and self.confidence < AUTO_APPROVAL_CONFIDENCE_THRESHOLD
        ):
            raise ValueError(
                f"status cannot be auto_approved with confidence {self.confidence} < "
                f"{AUTO_APPROVAL_CONFIDENCE_THRESHOLD} (FR-005)"
            )
        return self

    @model_validator(mode="after")
    def _approved_requires_review_metadata(self) -> ColumnClassification:
        if self.status == ClassificationStatus.APPROVED and (
            self.reviewed_by is None or self.reviewed_at is None
        ):
            raise ValueError(
                "status 'approved' requires non-null reviewed_by and reviewed_at (FR-013)"
            )
        return self
