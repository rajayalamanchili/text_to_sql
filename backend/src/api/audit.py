"""`GET /audit-log` (contracts/api.md, NFR-004).

Each domain's `audit_log` table lives in that domain's own Postgres
instance (tech-stack.md: "same instance pattern as domain data" —
matching `column_classifications`), not one shared cross-domain
database. Querying across all domains (the `domain` param omitted) means
connecting to every configured domain separately and merging results,
not a single cross-domain SQL query.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.deps import Caller, get_caller
from src.config.domains import DomainConfig, UnknownDomainError, get_domain, list_domains
from src.services.audit.audit_log import AuditLogEntry, Decision, PostgresAuditLogSink

router = APIRouter(tags=["audit"])


def _list_for_domain(
    domain_config: DomainConfig,
    *,
    from_ts: datetime | None,
    to_ts: datetime | None,
    decision: Decision | None,
) -> list[AuditLogEntry]:
    if not domain_config.database_url:
        return []
    with psycopg.connect(domain_config.database_url) as conn:
        sink = PostgresAuditLogSink(conn)
        return sink.list_entries(from_ts=from_ts, to_ts=to_ts, decision=decision)


@router.get("/audit-log")
def get_audit_log(
    caller: Annotated[Caller, Depends(get_caller)],
    domain: str | None = None,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    decision: Decision | None = None,
) -> dict:
    """List `AuditLogEntry` records, filterable by `domain`, a
    `[from, to]` time range, and `decision` (contracts/api.md, NFR-004).
    `domain` is optional — omit it to query across every configured
    domain."""
    del caller  # read-only; not role-gated (contracts/api.md Auth header)

    if domain is not None:
        try:
            domains_to_query = [get_domain(domain)]
        except UnknownDomainError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    else:
        domains_to_query = list_domains()

    entries: list[AuditLogEntry] = []
    for domain_config in domains_to_query:
        entries.extend(
            _list_for_domain(domain_config, from_ts=from_ts, to_ts=to_ts, decision=decision)
        )

    entries.sort(key=lambda entry: entry.timestamp, reverse=True)
    return {"items": [entry.model_dump(mode="json") for entry in entries]}
