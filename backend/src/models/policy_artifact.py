"""`PolicyArtifact`/`PolicyTable`/`PolicyColumn` models
(data-model.md#PolicyArtifact).

The versioned, deterministic-enforcement source of truth for one domain
(Constitution Principle IV) — persisted as YAML at
`policies/<domain>/<version>/policy.yaml`
(contracts/policy-artifact.schema.yaml). A table/column absent from a
published artifact is implicitly blocked (FR-009); that default-closed
behavior lives in the enforcement node (T048), not here — these models
only describe the artifact's own shape and publish-time validity.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from src.models.column_classification import Classification
from src.services.audit.audit_log import ActorRole

# FR-008 Clarifications (2026-07-27): the only supported row-policy
# placeholder in Milestone 1 — any other `:name` token is a policy-authoring
# error, rejected at publish time, not a runtime concern.
SUPPORTED_ROW_POLICY_PLACEHOLDER = ":current_tenant"
_PLACEHOLDER_PATTERN = re.compile(r":\w+")


class PolicyAction(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    ROLE_GATE = "role_gate"


class RoleMismatchAction(StrEnum):
    REJECT = "reject"
    EXCLUDE = "exclude"


class PolicyColumn(BaseModel):
    """One column's enforcement policy within a `PolicyTable` (FR-008)."""

    action: PolicyAction
    roles: list[ActorRole] = Field(default_factory=list)
    on_role_mismatch: RoleMismatchAction = RoleMismatchAction.REJECT
    classification: Classification

    @model_validator(mode="after")
    def _roles_required_iff_role_gate(self) -> PolicyColumn:
        if self.action == PolicyAction.ROLE_GATE and not self.roles:
            raise ValueError("roles must be non-empty when action == 'role_gate' (FR-008)")
        if self.action != PolicyAction.ROLE_GATE and self.roles:
            raise ValueError("roles must be empty unless action == 'role_gate' (FR-008)")
        return self


class PolicyTable(BaseModel):
    """One table's column policies plus its optional row-level predicate
    template (Scenario 5)."""

    table_name: str
    columns: dict[str, PolicyColumn] = Field(default_factory=dict)
    row_policy_template: str | None = None

    @model_validator(mode="after")
    def _row_policy_template_uses_only_supported_placeholder(self) -> PolicyTable:
        if self.row_policy_template is None:
            return self
        placeholders = set(_PLACEHOLDER_PATTERN.findall(self.row_policy_template))
        unsupported = placeholders - {SUPPORTED_ROW_POLICY_PLACEHOLDER}
        if unsupported:
            raise ValueError(
                f"row_policy_template for table {self.table_name!r} uses unsupported "
                f"placeholder(s) {sorted(unsupported)}; only "
                f"{SUPPORTED_ROW_POLICY_PLACEHOLDER!r} is supported in Milestone 1 (FR-008)"
            )
        return self


class PolicyArtifact(BaseModel):
    """A single published, versioned policy for one domain
    (data-model.md#PolicyArtifact). The active version per domain is
    resolved via `policies/<domain>/manifest.yaml` (research.md §6)."""

    domain: str
    version: int = Field(ge=1)
    tables: list[PolicyTable] = Field(default_factory=list)
    approved_by: str
    approved_at: datetime
