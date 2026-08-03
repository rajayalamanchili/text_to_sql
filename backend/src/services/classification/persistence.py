"""Postgres-backed `ClassificationStore` (data-model.md#ColumnClassification).

One row per (domain, table_name, column_name) in the domain's own
Postgres instance — same per-domain storage pattern as `audit_log`
(tech-stack.md). Re-classifying a column upserts its row rather than
appending a new one, matching the `/classify` endpoint's "re-running
re-classifies all columns from scratch" contract (contracts/api.md):
any prior human-review state (`reviewed_by`/`reviewed_at`) is cleared on
every upsert, since a freshly computed classification supersedes
whatever an admin previously approved/rejected for the old value.

Every save also writes a `classify_*` `AuditLogEntry` (FR-010) via an
injected `AuditLogWriter` — `reason_code`/`policy_version_used` are null
for classification-stage entries (data-model.md#AuditLogEntry). All
saves from one `PostgresClassificationStore` instance share a single
`run_id` as `query_id`, correlating every column decision from one
`/classify` call (the same id returned to the caller as `run_id`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg

from src.models.column_classification import (
    Classification,
    ClassificationSource,
    ClassificationStatus,
    ColumnClassification,
)
from src.services.audit.audit_log import ActorRole, AuditLogEntry, AuditLogWriter, Decision

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "0002_column_classifications.sql"
)

_DECISION_FOR_STATUS: dict[ClassificationStatus, Decision] = {
    ClassificationStatus.AUTO_APPROVED: Decision.CLASSIFY_AUTO_APPROVED,
    ClassificationStatus.PENDING_REVIEW: Decision.CLASSIFY_PENDING_REVIEW,
    ClassificationStatus.APPROVED: Decision.CLASSIFY_APPROVED,
    ClassificationStatus.REJECTED: Decision.CLASSIFY_REJECTED,
}

_UPSERT_SQL = """
    INSERT INTO column_classifications (
        id, domain, table_name, column_name, data_type, cardinality_ratio,
        classification, heuristic_score, llm_score, confidence, source,
        status, reviewed_by, reviewed_at, llm_rationale
    )
    VALUES (
        %(id)s, %(domain)s, %(table_name)s, %(column_name)s, %(data_type)s,
        %(cardinality_ratio)s, %(classification)s, %(heuristic_score)s,
        %(llm_score)s, %(confidence)s, %(source)s, %(status)s, NULL, NULL,
        %(llm_rationale)s
    )
    ON CONFLICT (domain, table_name, column_name) DO UPDATE SET
        id = EXCLUDED.id,
        data_type = EXCLUDED.data_type,
        cardinality_ratio = EXCLUDED.cardinality_ratio,
        classification = EXCLUDED.classification,
        heuristic_score = EXCLUDED.heuristic_score,
        llm_score = EXCLUDED.llm_score,
        confidence = EXCLUDED.confidence,
        source = EXCLUDED.source,
        status = EXCLUDED.status,
        reviewed_by = NULL,
        reviewed_at = NULL,
        llm_rationale = EXCLUDED.llm_rationale
"""

_SELECT_SQL = """
    SELECT id, domain, table_name, column_name, data_type, cardinality_ratio,
           classification, heuristic_score, llm_score, confidence, source,
           status, reviewed_by, reviewed_at, llm_rationale
    FROM column_classifications
    WHERE domain = %(domain)s
      AND (%(table_name)s::text IS NULL OR table_name = %(table_name)s)
      AND (%(column_name)s::text IS NULL OR column_name = %(column_name)s)
    ORDER BY table_name, column_name
"""

_SELECT_BY_ID_SQL = """
    SELECT id, domain, table_name, column_name, data_type, cardinality_ratio,
           classification, heuristic_score, llm_score, confidence, source,
           status, reviewed_by, reviewed_at, llm_rationale
    FROM column_classifications
    WHERE domain = %(domain)s AND id = %(id)s
"""

_UPDATE_REVIEW_SQL = """
    UPDATE column_classifications
    SET status = %(status)s, reviewed_by = %(reviewed_by)s, reviewed_at = %(reviewed_at)s
    WHERE id = %(id)s
"""

_UPDATE_RECLASSIFY_SQL = """
    UPDATE column_classifications
    SET classification = %(classification)s, source = %(source)s, status = %(status)s,
        reviewed_by = %(reviewed_by)s, reviewed_at = %(reviewed_at)s
    WHERE id = %(id)s
"""


class PostgresClassificationStore:
    """Implements the classification graph's `ClassificationStore`
    protocol (`src/graph/classification_graph.py`) against Postgres."""

    def __init__(
        self,
        conn: psycopg.Connection,
        *,
        audit_writer: AuditLogWriter | None = None,
        actor_role: ActorRole = ActorRole.ANALYST,
        run_id: UUID | None = None,
    ) -> None:
        self._conn = conn
        self._audit_writer = audit_writer
        self._actor_role = actor_role
        self.run_id = run_id or uuid4()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_MIGRATION_PATH.read_text())
        self._conn.commit()

    async def save(self, record: ColumnClassification) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                _UPSERT_SQL,
                {
                    "id": record.id,
                    "domain": record.domain,
                    "table_name": record.table_name,
                    "column_name": record.column_name,
                    "data_type": record.data_type,
                    "cardinality_ratio": record.cardinality_ratio,
                    "classification": record.classification.value,
                    "heuristic_score": record.heuristic_score,
                    "llm_score": record.llm_score,
                    "confidence": record.confidence,
                    "source": record.source.value,
                    "status": record.status.value,
                    "llm_rationale": record.llm_rationale,
                },
            )
        self._conn.commit()
        if self._audit_writer is not None:
            await self._audit_writer.write(
                AuditLogEntry.create(
                    domain=record.domain,
                    query_id=self.run_id,
                    actor_role=self._actor_role,
                    decision=_DECISION_FOR_STATUS[record.status],
                )
            )

    def list_records(
        self, domain: str, *, table_name: str | None = None, column_name: str | None = None
    ) -> list[ColumnClassification]:
        with self._conn.cursor() as cur:
            cur.execute(
                _SELECT_SQL,
                {"domain": domain, "table_name": table_name, "column_name": column_name},
            )
            rows = cur.fetchall()
        return [_row_to_record(row) for row in rows]

    def get_by_id(self, domain: str, column_id: UUID) -> ColumnClassification | None:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_BY_ID_SQL, {"domain": domain, "id": column_id})
            row = cur.fetchone()
        return _row_to_record(row) if row is not None else None

    async def approve(
        self, record: ColumnClassification, *, reviewed_by: str
    ) -> ColumnClassification:
        """Transition `record` from `pending_review` to `approved`
        (data-model.md State Transitions), setting `reviewed_by`/
        `reviewed_at` and writing a `classify_approved` `AuditLogEntry`
        keyed by the column's own id, since this action — unlike a
        `/classify` run — has no shared `run_id` to correlate against
        (contracts/api.md, Scenario 8)."""
        updated = record.model_copy(
            update={
                "status": ClassificationStatus.APPROVED,
                "reviewed_by": reviewed_by,
                "reviewed_at": datetime.now(UTC),
            }
        )
        with self._conn.cursor() as cur:
            cur.execute(
                _UPDATE_REVIEW_SQL,
                {
                    "id": updated.id,
                    "status": updated.status.value,
                    "reviewed_by": updated.reviewed_by,
                    "reviewed_at": updated.reviewed_at,
                },
            )
        self._conn.commit()
        if self._audit_writer is not None:
            await self._audit_writer.write(
                AuditLogEntry.create(
                    domain=updated.domain,
                    query_id=updated.id,
                    actor_role=self._actor_role,
                    decision=Decision.CLASSIFY_APPROVED,
                )
            )
        return updated

    async def reject(
        self, record: ColumnClassification, *, reviewed_by: str
    ) -> ColumnClassification:
        """Transition `record` from `pending_review` to `rejected`
        (data-model.md State Transitions), setting `reviewed_by`/
        `reviewed_at` and writing a `classify_rejected` `AuditLogEntry`
        keyed by the column's own id, mirroring `approve` (contracts/api.md)."""
        updated = record.model_copy(
            update={
                "status": ClassificationStatus.REJECTED,
                "reviewed_by": reviewed_by,
                "reviewed_at": datetime.now(UTC),
            }
        )
        with self._conn.cursor() as cur:
            cur.execute(
                _UPDATE_REVIEW_SQL,
                {
                    "id": updated.id,
                    "status": updated.status.value,
                    "reviewed_by": updated.reviewed_by,
                    "reviewed_at": updated.reviewed_at,
                },
            )
        self._conn.commit()
        if self._audit_writer is not None:
            await self._audit_writer.write(
                AuditLogEntry.create(
                    domain=updated.domain,
                    query_id=updated.id,
                    actor_role=self._actor_role,
                    decision=Decision.CLASSIFY_REJECTED,
                )
            )
        return updated

    async def reclassify(
        self, record: ColumnClassification, *, classification: Classification, reviewed_by: str
    ) -> ColumnClassification:
        """Overwrite `record`'s classification with an admin-supplied
        value, set `source = "human"`, and transition to `approved`
        (contracts/api.md `reclassify`, data-model.md State Transitions).
        Writes a `classify_approved` `AuditLogEntry`, same decision as a
        plain `approve` since the resulting status is identical."""
        updated = record.model_copy(
            update={
                "classification": classification,
                "source": ClassificationSource.HUMAN,
                "status": ClassificationStatus.APPROVED,
                "reviewed_by": reviewed_by,
                "reviewed_at": datetime.now(UTC),
            }
        )
        with self._conn.cursor() as cur:
            cur.execute(
                _UPDATE_RECLASSIFY_SQL,
                {
                    "id": updated.id,
                    "classification": updated.classification.value,
                    "source": updated.source.value,
                    "status": updated.status.value,
                    "reviewed_by": updated.reviewed_by,
                    "reviewed_at": updated.reviewed_at,
                },
            )
        self._conn.commit()
        if self._audit_writer is not None:
            await self._audit_writer.write(
                AuditLogEntry.create(
                    domain=updated.domain,
                    query_id=updated.id,
                    actor_role=self._actor_role,
                    decision=Decision.CLASSIFY_APPROVED,
                )
            )
        return updated


def _row_to_record(row: tuple) -> ColumnClassification:
    (
        id_,
        domain,
        table_name,
        column_name,
        data_type,
        cardinality_ratio,
        classification,
        heuristic_score,
        llm_score,
        confidence,
        source,
        status,
        reviewed_by,
        reviewed_at,
        llm_rationale,
    ) = row
    return ColumnClassification(
        id=id_,
        domain=domain,
        table_name=table_name,
        column_name=column_name,
        data_type=data_type,
        cardinality_ratio=cardinality_ratio,
        classification=Classification(classification),
        heuristic_score=heuristic_score,
        llm_score=llm_score,
        confidence=confidence,
        source=ClassificationSource(source),
        status=ClassificationStatus(status),
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        llm_rationale=llm_rationale,
    )
