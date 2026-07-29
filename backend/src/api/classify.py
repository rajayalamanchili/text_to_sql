"""`POST /domains/{domain}/classify` and `GET /domains/{domain}/classifications`
(contracts/api.md, FR-002/FR-003)."""

from __future__ import annotations

import asyncio
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import Caller, get_caller, get_domain_config
from src.config.domains import DomainConfig
from src.graph.classification_graph import run_classification
from src.models.column_classification import ClassificationStatus
from src.services.audit.audit_log import AuditLogWriter, PostgresAuditLogSink
from src.services.classification.anthropic_client import build_default_llm_client
from src.services.classification.persistence import PostgresClassificationStore

router = APIRouter(prefix="/domains/{domain}", tags=["classification"])


@router.post("/classify", status_code=202)
def classify_domain_schema(
    domain: Annotated[DomainConfig, Depends(get_domain_config)],
    caller: Annotated[Caller, Depends(get_caller)],
) -> dict:
    """Run the classification graph (research.md §9) over `domain`'s
    schema: heuristic pass, then conditional LLM-assisted pass
    (FR-002, FR-003). Idempotent per schema snapshot — re-running
    re-classifies all columns from scratch (contracts/api.md).

    Uses the real Anthropic adapter (`anthropic_client.py`) when an API
    credential is configured, falling back to `NullLLMClient` otherwise
    — every low-confidence column then stays exactly at its heuristic-
    pass score, landing in `pending_review` rather than a fabricated
    auto-approval. Every persisted column also writes a `classify_*`
    `AuditLogEntry` (FR-010), all sharing one `run_id` — the same id
    returned to the caller below.
    """
    if not domain.database_url:
        raise HTTPException(
            status_code=503, detail=f"no database configured for domain {domain.name!r}"
        )

    with psycopg.connect(domain.database_url) as conn:
        audit_writer = AuditLogWriter(PostgresAuditLogSink(conn))
        store = PostgresClassificationStore(conn, audit_writer=audit_writer, actor_role=caller.role)
        records = asyncio.run(
            run_classification(
                domain=domain.name,
                conn=conn,
                llm_client=build_default_llm_client(),
                store=store,
            )
        )

    auto_approved_count = sum(
        1 for record in records if record.status == ClassificationStatus.AUTO_APPROVED
    )
    pending_review_count = sum(
        1 for record in records if record.status == ClassificationStatus.PENDING_REVIEW
    )

    return {
        "run_id": str(store.run_id),
        "columns_classified": len(records),
        "auto_approved_count": auto_approved_count,
        "pending_review_count": pending_review_count,
    }


@router.get("/classifications")
def list_domain_classifications(
    domain: Annotated[DomainConfig, Depends(get_domain_config)],
    caller: Annotated[Caller, Depends(get_caller)],
    table: str | None = None,
    column: str | None = None,
) -> dict:
    """List `ColumnClassification` records for `domain`, in **any**
    status — closes the gap neither `/review-queue` (pending-only) nor
    `/policy` (published, no confidence) can answer (contracts/api.md,
    T027a). Omit `table`/`column` to list every classified column."""
    del caller  # not role-gated (contract §Auth header); accepted for consistency
    if not domain.database_url:
        raise HTTPException(
            status_code=503, detail=f"no database configured for domain {domain.name!r}"
        )

    with psycopg.connect(domain.database_url) as conn:
        store = PostgresClassificationStore(conn)
        records = store.list_records(domain.name, table_name=table, column_name=column)

    return {"items": [record.model_dump(mode="json") for record in records]}
