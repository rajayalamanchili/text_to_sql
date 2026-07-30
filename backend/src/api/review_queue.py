"""`GET /domains/{domain}/review-queue` (contracts/api.md, FR-013).

A `status == "pending_review"`-filtered view of T027a's classification
store — not a separate one (tasks.md T032).
"""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.deps import Caller, get_caller, get_domain_config, require_admin
from src.config.domains import DomainConfig
from src.models.column_classification import Classification, ClassificationStatus
from src.services.audit.audit_log import AuditLogWriter, PostgresAuditLogSink
from src.services.classification.persistence import PostgresClassificationStore

router = APIRouter(prefix="/domains/{domain}", tags=["review-queue"])


@router.get("/review-queue")
def list_review_queue(
    domain: Annotated[DomainConfig, Depends(get_domain_config)],
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    """List `ColumnClassification` records with `status == "pending_review"`,
    including `heuristic_score`, `llm_score`, `confidence`, and
    `llm_rationale` as source signals for the reviewer (contracts/api.md)."""
    del caller  # read-only; not role-gated (only approve/reject/reclassify are, contracts/api.md)
    if not domain.database_url:
        raise HTTPException(
            status_code=503, detail=f"no database configured for domain {domain.name!r}"
        )

    with psycopg.connect(domain.database_url) as conn:
        store = PostgresClassificationStore(conn)
        records = store.list_records(domain.name)

    pending = [record for record in records if record.status == ClassificationStatus.PENDING_REVIEW]
    return {"items": [record.model_dump(mode="json") for record in pending]}


@router.post("/review-queue/{column_id}/approve")
def approve_review_queue_column(
    domain: Annotated[DomainConfig, Depends(get_domain_config)],
    caller: Annotated[Caller, Depends(require_admin)],
    column_id: UUID,
) -> dict:
    """Transition a `pending_review` column to `approved`, admin-only
    (contracts/api.md, FR-013, Scenario 8). `require_admin` rejects any
    non-admin caller with 403 before this body runs, leaving the
    underlying record unchanged (data-model.md State Transitions)."""
    if not domain.database_url:
        raise HTTPException(
            status_code=503, detail=f"no database configured for domain {domain.name!r}"
        )

    with psycopg.connect(domain.database_url) as conn:
        audit_writer = AuditLogWriter(PostgresAuditLogSink(conn))
        store = PostgresClassificationStore(conn, audit_writer=audit_writer, actor_role=caller.role)
        record = _get_pending_record_or_error(store, domain.name, column_id)
        updated = asyncio.run(store.approve(record, reviewed_by=caller.role.value))

    return updated.model_dump(mode="json")


@router.post("/review-queue/{column_id}/reject")
def reject_review_queue_column(
    domain: Annotated[DomainConfig, Depends(get_domain_config)],
    caller: Annotated[Caller, Depends(require_admin)],
    column_id: UUID,
) -> dict:
    """Transition a `pending_review` column to `rejected`, admin-only.
    Same auth/audit rules as `approve` (contracts/api.md)."""
    if not domain.database_url:
        raise HTTPException(
            status_code=503, detail=f"no database configured for domain {domain.name!r}"
        )

    with psycopg.connect(domain.database_url) as conn:
        audit_writer = AuditLogWriter(PostgresAuditLogSink(conn))
        store = PostgresClassificationStore(conn, audit_writer=audit_writer, actor_role=caller.role)
        record = _get_pending_record_or_error(store, domain.name, column_id)
        updated = asyncio.run(store.reject(record, reviewed_by=caller.role.value))

    return updated.model_dump(mode="json")


class ReclassifyRequest(BaseModel):
    classification: Classification


@router.post("/review-queue/{column_id}/reclassify")
def reclassify_review_queue_column(
    domain: Annotated[DomainConfig, Depends(get_domain_config)],
    caller: Annotated[Caller, Depends(require_admin)],
    column_id: UUID,
    body: ReclassifyRequest,
) -> dict:
    """Overwrite a `pending_review` column's classification with an
    admin-supplied value, set `source = "human"`, and transition to
    `approved`. Same auth/audit rules as `approve` (contracts/api.md)."""
    if not domain.database_url:
        raise HTTPException(
            status_code=503, detail=f"no database configured for domain {domain.name!r}"
        )

    with psycopg.connect(domain.database_url) as conn:
        audit_writer = AuditLogWriter(PostgresAuditLogSink(conn))
        store = PostgresClassificationStore(conn, audit_writer=audit_writer, actor_role=caller.role)
        record = _get_pending_record_or_error(store, domain.name, column_id)
        updated = asyncio.run(
            store.reclassify(
                record, classification=body.classification, reviewed_by=caller.role.value
            )
        )

    return updated.model_dump(mode="json")


def _get_pending_record_or_error(store: PostgresClassificationStore, domain: str, column_id: UUID):
    """Shared lookup for approve/reject: 404 on an unknown column id, 409
    if it's not currently `pending_review` (data-model.md State
    Transitions only defines that as the source state for either action)."""
    record = store.get_by_id(domain, column_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no classification record {column_id}")
    if record.status != ClassificationStatus.PENDING_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"column {column_id} is {record.status.value}, not pending_review",
        )
    return record
