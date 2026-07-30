"""`POST /domains/{domain}/query` (contracts/api.md, research.md §9).

Wires the query graph (T050) into the API layer: parse the auth-stub
role, run the graph, and map its decision onto the HTTP contract's
varying shapes — `200` with `rows` on `allow`, `403` with
`{reason_code, reason_message}` on every other decision, one consistent
body shape regardless of which reason applies.

`QuestionNotMappedError` (FR-014, Scenario 10) is handled here as an
interim measure: the HTTP-level contract (`200`, no SQL run, no schema
revealed) is satisfied, but this path does not yet write its own audit
log entry, since `query_graph.py` has no `Decision` value yet for "no
policy was evaluated at all" — closing that gap is `tasks.md`'s T056,
not this endpoint's.
"""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator

from src.api.deps import Caller, get_caller, get_domain_config
from src.config.domains import DomainConfig
from src.graph.query_graph import run_query
from src.services.audit.audit_log import AuditLogWriter, Decision, PostgresAuditLogSink, ReasonCode
from src.services.generation.sql_proposal import QuestionNotMappedError
from src.services.policy.policy_store import PolicyStore

router = APIRouter(prefix="/domains/{domain}", tags=["query"])


class QueryRequest(BaseModel):
    question: str | None = None
    sql: str | None = None

    @model_validator(mode="after")
    def _exactly_one_of_question_or_sql(self) -> QueryRequest:
        if (self.question is None) == (self.sql is None):
            raise ValueError("exactly one of `question` or `sql` must be provided")
        return self


@router.post("/query")
def query_domain(
    domain: Annotated[DomainConfig, Depends(get_domain_config)],
    caller: Annotated[Caller, Depends(get_caller)],
    body: QueryRequest,
) -> JSONResponse:
    if not domain.database_url:
        raise HTTPException(
            status_code=503, detail=f"no database configured for domain {domain.name!r}"
        )

    with psycopg.connect(domain.database_url) as conn:
        policy_store = PolicyStore(domain)
        audit_writer = AuditLogWriter(PostgresAuditLogSink(conn))
        try:
            result = asyncio.run(
                run_query(
                    domain=domain.name,
                    conn=conn,
                    caller=caller,
                    policy_store=policy_store,
                    audit_writer=audit_writer,
                    question=body.question,
                    sql=body.sql,
                )
            )
        except QuestionNotMappedError:
            return JSONResponse(
                status_code=200,
                content=jsonable_encoder(
                    {
                        "query_id": uuid4(),
                        "reason_code": ReasonCode.QUESTION_NOT_MAPPED,
                        "reason_message": "question not mapped to schema",
                    }
                ),
            )

    if result.decision == Decision.ALLOW:
        return JSONResponse(
            status_code=200,
            content=jsonable_encoder(
                {
                    "query_id": result.query_id,
                    "rows": result.rows,
                    "policy_version_used": result.policy_version_used,
                }
            ),
        )

    return JSONResponse(
        status_code=403,
        content=jsonable_encoder(
            {
                "query_id": result.query_id,
                "reason_code": result.reason_code,
                "reason_message": result.reason_message,
                "policy_version_used": result.policy_version_used,
            }
        ),
    )
