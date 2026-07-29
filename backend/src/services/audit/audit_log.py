"""Audit log entry model, reason-code rendering, and writer.

Every classification and enforcement decision produces exactly one
`AuditLogEntry` (FR-010, data-model.md#AuditLogEntry). `reason_code` is
always one of a fixed enum, never a free-form string — `reason_message`
is rendered from that code's template (research.md §8), never authored
ad hoc at the call site, so querying by decision type (NFR-004) never
depends on string matching.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

import psycopg
import structlog
from pydantic import BaseModel, model_validator

_MIGRATION_PATH = Path(__file__).resolve().parents[2] / "db" / "migrations" / "0001_audit_log.sql"


class ActorRole(StrEnum):
    ANALYST = "analyst"
    ADMIN = "admin"


class Decision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    MASK = "mask"  # reserved for a future milestone (FR-010) — unused in M1
    CLASSIFY_AUTO_APPROVED = "classify_auto_approved"
    CLASSIFY_PENDING_REVIEW = "classify_pending_review"
    CLASSIFY_APPROVED = "classify_approved"
    CLASSIFY_REJECTED = "classify_rejected"


class ReasonCode(StrEnum):
    COLUMN_BLOCKED = "COLUMN_BLOCKED"
    NO_ACTIVE_POLICY = "NO_ACTIVE_POLICY"
    DML_REJECTED = "DML_REJECTED"
    MULTIPLE_STATEMENTS_REJECTED = "MULTIPLE_STATEMENTS_REJECTED"
    ROLE_GATE_MISMATCH = "ROLE_GATE_MISMATCH"
    SCHEMA_NOT_CLASSIFIED = "SCHEMA_NOT_CLASSIFIED"
    QUESTION_NOT_MAPPED = "QUESTION_NOT_MAPPED"
    ENFORCEMENT_ERROR = "ENFORCEMENT_ERROR"


# Rendered via str.format(**params). Wording matches spec.md's scenarios
# verbatim where one is given (Scenarios 4, 6, 7, 9, 10). spec.md does not
# give a literal message for MULTIPLE_STATEMENTS_REJECTED, SCHEMA_NOT_CLASSIFIED,
# or ENFORCEMENT_ERROR, and does not explain how NO_ACTIVE_POLICY and
# SCHEMA_NOT_CLASSIFIED differ (security.md checklist CHK008/CHK020, still
# open) — those three templates below are a reasonable best-effort, not a
# resolved spec citation, and should be revisited once that gap is closed.
_REASON_MESSAGE_TEMPLATES: dict[ReasonCode, str] = {
    ReasonCode.COLUMN_BLOCKED: "column blocked by policy: {column}",
    ReasonCode.NO_ACTIVE_POLICY: "schema not yet classified",
    ReasonCode.DML_REJECTED: "DML statement rejected: read-only queries only",
    ReasonCode.MULTIPLE_STATEMENTS_REJECTED: (
        "multiple statements rejected: only a single read-only query is allowed"
    ),
    ReasonCode.ROLE_GATE_MISMATCH: "column requires role: {role}",
    ReasonCode.SCHEMA_NOT_CLASSIFIED: "domain schema has not completed classification",
    ReasonCode.QUESTION_NOT_MAPPED: "question not mapped to schema",
    ReasonCode.ENFORCEMENT_ERROR: "enforcement error: unable to evaluate policy for this query",
}


def render_reason_message(reason_code: ReasonCode, **params: Any) -> str:
    """Render `reason_code`'s fixed template — never authored free-form at
    the call site (FR-010)."""
    return _REASON_MESSAGE_TEMPLATES[reason_code].format(**params)


class AuditLogEntry(BaseModel):
    """One row of the `audit_log` table (data-model.md#AuditLogEntry,
    backend/src/db/migrations/0001_audit_log.sql)."""

    model_config = {"frozen": True}

    id: UUID
    timestamp: datetime
    domain: str
    query_id: UUID
    actor_role: ActorRole
    decision: Decision
    reason_code: ReasonCode | None = None
    reason_message: str | None = None
    policy_version_used: int | None = None
    raw_query_hash: str | None = None

    @model_validator(mode="after")
    def _reason_code_and_message_paired(self) -> AuditLogEntry:
        if (self.reason_code is None) != (self.reason_message is None):
            raise ValueError("reason_code and reason_message must be set or null together")
        return self

    @classmethod
    def create(
        cls,
        *,
        domain: str,
        query_id: UUID,
        actor_role: ActorRole,
        decision: Decision,
        reason_code: ReasonCode | None = None,
        reason_params: dict[str, Any] | None = None,
        policy_version_used: int | None = None,
        raw_query_hash: str | None = None,
    ) -> AuditLogEntry:
        """Build an entry, rendering `reason_message` from `reason_code`'s
        template so callers never author a message string by hand."""
        reason_message = (
            render_reason_message(reason_code, **(reason_params or {}))
            if reason_code is not None
            else None
        )
        return cls(
            id=uuid4(),
            timestamp=datetime.now(UTC),
            domain=domain,
            query_id=query_id,
            actor_role=actor_role,
            decision=decision,
            reason_code=reason_code,
            reason_message=reason_message,
            policy_version_used=policy_version_used,
            raw_query_hash=raw_query_hash,
        )


def configure_logging() -> None:
    """Configure `structlog` for JSON-formatted structured logs
    (tech-stack.md Observability). Idempotent — safe to call more than once."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )


_logger = structlog.get_logger("steward.audit_log")


@runtime_checkable
class AuditLogSink(Protocol):
    """Persistence hook for the `audit_log` Postgres table. Left as a
    protocol rather than hardcoding a driver here, so callers that don't
    need durable persistence (e.g. a unit test) can pass `None` to
    `AuditLogWriter` and still get the structured log line. `PostgresAuditLogSink`
    below is the concrete Milestone 1 implementation."""

    async def save(self, entry: AuditLogEntry) -> None: ...


class PostgresAuditLogSink:
    """Writes `AuditLogEntry` rows into the `audit_log` table
    (`db/migrations/0001_audit_log.sql`) on an already-open, per-domain
    connection — same per-domain storage pattern as
    `column_classifications` (tech-stack.md)."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_MIGRATION_PATH.read_text())
        self._conn.commit()

    async def save(self, entry: AuditLogEntry) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (
                    id, "timestamp", domain, query_id, actor_role, decision,
                    reason_code, reason_message, policy_version_used, raw_query_hash
                ) VALUES (
                    %(id)s, %(timestamp)s, %(domain)s, %(query_id)s, %(actor_role)s,
                    %(decision)s, %(reason_code)s, %(reason_message)s,
                    %(policy_version_used)s, %(raw_query_hash)s
                )
                """,
                {
                    "id": entry.id,
                    "timestamp": entry.timestamp,
                    "domain": entry.domain,
                    "query_id": entry.query_id,
                    "actor_role": entry.actor_role.value,
                    "decision": entry.decision.value,
                    "reason_code": entry.reason_code.value if entry.reason_code else None,
                    "reason_message": entry.reason_message,
                    "policy_version_used": entry.policy_version_used,
                    "raw_query_hash": entry.raw_query_hash,
                },
            )
        self._conn.commit()


class AuditLogWriter:
    """Writes one `AuditLogEntry` to the structured event log (always) and,
    if a sink is configured, to the `audit_log` Postgres table (Constitution
    Principle VIII, NFR-004)."""

    def __init__(self, sink: AuditLogSink | None = None) -> None:
        self._sink = sink

    async def write(self, entry: AuditLogEntry) -> None:
        _logger.info("audit_log_entry", **entry.model_dump(mode="json"))
        if self._sink is not None:
            await self._sink.save(entry)
