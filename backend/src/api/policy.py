"""`POST /domains/{domain}/policy/publish` and `GET /domains/{domain}/policy`
(contracts/api.md, FR-006/FR-007).

Publish builds a `PolicyArtifact` from every currently `approved`/
`auto_approved` `ColumnClassification` for the domain. The
classification→action mapping is a pure, deterministic two-outcome
function (spec.md Amendments, 2026-07-30): `business` → `allow`, every
other classification → `block` (fail-closed default, Constitution
Principle II). `role_gate` and any `row_policy_template` are never
auto-derived here — both are manual, post-publish overrides applied
directly to the published YAML (see tasks.md T061/T064), since no
classification-stage input carries that information in Milestone 1.
"""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import Caller, get_caller, get_domain_config, require_admin
from src.config.domains import DomainConfig
from src.models.column_classification import (
    Classification,
    ClassificationStatus,
    ColumnClassification,
)
from src.models.policy_artifact import PolicyAction, PolicyArtifact, PolicyColumn, PolicyTable
from src.services.audit.audit_log import (
    AuditLogEntry,
    AuditLogWriter,
    Decision,
    PostgresAuditLogSink,
)
from src.services.classification.persistence import PostgresClassificationStore
from src.services.policy.policy_store import PolicyStore

router = APIRouter(prefix="/domains/{domain}", tags=["policy"])

_PUBLISHABLE_STATUSES = {ClassificationStatus.APPROVED, ClassificationStatus.AUTO_APPROVED}


def _action_for(classification: Classification) -> PolicyAction:
    """`business` is the only classification treated as safe to allow by
    default; everything else defaults closed (spec.md Amendments,
    2026-07-30)."""
    return PolicyAction.ALLOW if classification == Classification.BUSINESS else PolicyAction.BLOCK


def _build_tables(records: list[ColumnClassification]) -> list[PolicyTable]:
    tables: dict[str, dict[str, PolicyColumn]] = {}
    for record in records:
        if record.status not in _PUBLISHABLE_STATUSES:
            continue
        columns = tables.setdefault(record.table_name, {})
        columns[record.column_name] = PolicyColumn(
            action=_action_for(record.classification),
            classification=record.classification,
        )
    return [
        PolicyTable(table_name=table_name, columns=columns)
        for table_name, columns in sorted(tables.items())
    ]


@router.post("/policy/publish", status_code=201)
def publish_domain_policy(
    domain: Annotated[DomainConfig, Depends(get_domain_config)],
    caller: Annotated[Caller, Depends(require_admin)],
) -> PolicyArtifact:
    """Publish a new policy version built from all currently `approved`
    classifications, admin-only (contracts/api.md, FR-006)."""
    if not domain.database_url:
        raise HTTPException(
            status_code=503, detail=f"no database configured for domain {domain.name!r}"
        )

    with psycopg.connect(domain.database_url) as conn:
        classification_store = PostgresClassificationStore(conn)
        records = classification_store.list_records(domain.name)
        tables = _build_tables(records)

        policy_store = PolicyStore(domain)
        artifact = policy_store.publish(tables, approved_by=caller.role.value)

        audit_writer = AuditLogWriter(PostgresAuditLogSink(conn))
        asyncio.run(
            audit_writer.write(
                AuditLogEntry.create(
                    domain=domain.name,
                    query_id=uuid4(),
                    actor_role=caller.role,
                    decision=Decision.POLICY_PUBLISHED,
                    policy_version_used=artifact.version,
                )
            )
        )

    return artifact


@router.get("/policy")
def get_domain_policy(
    domain: Annotated[DomainConfig, Depends(get_domain_config)],
    caller: Annotated[Caller, Depends(get_caller)],
) -> PolicyArtifact:
    """Return the currently active `PolicyArtifact` for `domain`, or 404
    if none has ever been published — callers MUST treat 404 as "nothing
    is allowed" (FR-009), not an error to retry past."""
    del caller  # read-only; not role-gated (contracts/api.md Auth header)
    artifact = PolicyStore(domain).get_active()
    if artifact is None:
        raise HTTPException(
            status_code=404, detail=f"no policy has ever been published for domain {domain.name!r}"
        )
    return artifact
