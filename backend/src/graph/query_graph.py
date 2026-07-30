"""Query LangGraph graph (research.md §9, §5).

`generate_sql -> deterministic_enforce -> execute (only if enforcement
passes) -> audit_log`, mirroring `classification_graph.py`'s pattern:
runtime dependencies (the open DB connection, the caller, the policy
store, the audit writer) are injected via `context_schema`; graph state
stays pure data.

Schema metadata for column resolution reuses the same `enumerate_schema`
classification uses (FR-001) rather than a lighter query-time-only
variant — Milestone 1's scope doesn't call for that optimization; revisit
only if NFR-002/eval benchmarking flags it as a real bottleneck.

`enforce_node` passes `state["sql"]` straight through as raw text — the
non-`SELECT`/multi-statement DML guard (FR-014, T055) and all SQL parsing
now live entirely inside `enforce()` (`enforcer.py`), which owns parsing
so it can distinguish "more than one statement" from "one parseable
statement" itself, rather than this graph pre-parsing and silently
collapsing that distinction.

`question`'s "cannot be mapped to schema" case (FR-014, Scenario 10, T056):
`propose_sql` (T049) raises `QuestionNotMappedError` before generating any
SQL; `generate_node` catches it and stores a synthetic `EnforcementResult`
directly in state (`decision=Decision.QUESTION_NOT_MAPPED`,
`reason_code=ReasonCode.QUESTION_NOT_MAPPED`, `policy_version_used=None`
— no policy was ever resolved, since this never reaches `enforce_node`).
A conditional edge then routes straight to `audit`, skipping `enforce`
and `execute` entirely, so no SQL is ever generated or run — FR-010's
audit-completeness rule still gets its one entry either way.

Deliberately NOT yet handled here (later tasks, same file):
- `role_gate` and row-policy predicate injection — T063, T059/T060 (both
  inside `enforcer.py`, which this graph already calls through).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID, uuid4

import psycopg
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from src.api.deps import Caller
from src.services.audit.audit_log import (
    AuditLogEntry,
    AuditLogWriter,
    Decision,
    ReasonCode,
    render_reason_message,
)
from src.services.enforcement.enforcer import EnforcementResult, enforce
from src.services.enumeration.schema_enumerator import enumerate_schema
from src.services.generation.sql_proposal import QuestionNotMappedError, propose_sql
from src.services.policy.policy_store import PolicyStore


@dataclass
class QueryGraphContext:
    domain: str
    conn: psycopg.Connection
    caller: Caller
    policy_store: PolicyStore
    audit_writer: AuditLogWriter


class QueryGraphState(TypedDict, total=False):
    question: str | None
    sql: str | None
    query_id: UUID
    enforcement: EnforcementResult
    rows: list[tuple] | None


@dataclass(frozen=True)
class QueryResult:
    """The outcome of one `run_query` call — the shape `contracts/api.md`'s
    `/query` endpoint (T051) will render into its response body."""

    query_id: UUID
    decision: Decision
    reason_code: ReasonCode | None
    reason_message: str | None
    policy_version_used: int | None
    rows: list[tuple] | None


def generate_node(state: QueryGraphState, runtime: Runtime[QueryGraphContext]) -> dict:
    schema = enumerate_schema(runtime.context.domain, runtime.context.conn)
    try:
        proposal = propose_sql(schema, question=state.get("question"), sql=state.get("sql"))
    except QuestionNotMappedError:
        # FR-014/Scenario 10: no SQL is generated at all — `sql` stays
        # unset, which `_route_after_generate` uses to skip straight to
        # `audit`, and `policy_version_used` stays null since no policy
        # is ever resolved for this outcome.
        return {
            "enforcement": EnforcementResult(
                decision=Decision.QUESTION_NOT_MAPPED,
                reason_code=ReasonCode.QUESTION_NOT_MAPPED,
                reason_message=render_reason_message(ReasonCode.QUESTION_NOT_MAPPED),
                policy_version_used=None,
            )
        }
    return {"sql": proposal.sql}


def _route_after_generate(state: QueryGraphState, runtime: Runtime[QueryGraphContext]) -> str:
    del runtime
    return "enforce" if state.get("sql") is not None else "audit"


def enforce_node(state: QueryGraphState, runtime: Runtime[QueryGraphContext]) -> dict:
    schema = enumerate_schema(runtime.context.domain, runtime.context.conn)
    result = enforce(state["sql"], schema, runtime.context.policy_store)
    return {"enforcement": result}


def execute_node(state: QueryGraphState, runtime: Runtime[QueryGraphContext]) -> dict:
    if state["enforcement"].decision != Decision.ALLOW:
        return {"rows": None}
    with runtime.context.conn.cursor() as cur:
        cur.execute(state["sql"])
        rows = cur.fetchall()
    return {"rows": rows}


async def audit_node(state: QueryGraphState, runtime: Runtime[QueryGraphContext]) -> dict:
    enforcement = state["enforcement"]
    sql = state.get("sql")
    entry = AuditLogEntry.create(
        domain=runtime.context.domain,
        query_id=state["query_id"],
        actor_role=runtime.context.caller.role,
        decision=enforcement.decision,
        reason_code=enforcement.reason_code,
        reason_message=enforcement.reason_message,
        policy_version_used=enforcement.policy_version_used,
        raw_query_hash=hashlib.sha256(sql.encode()).hexdigest() if sql is not None else None,
    )
    await runtime.context.audit_writer.write(entry)
    return {}


def build_query_graph():
    graph = StateGraph(state_schema=QueryGraphState, context_schema=QueryGraphContext)
    graph.add_node("generate", generate_node)
    graph.add_node("enforce", enforce_node)
    graph.add_node("execute", execute_node)
    graph.add_node("audit", audit_node)

    graph.add_edge(START, "generate")
    graph.add_conditional_edges(
        "generate", _route_after_generate, {"enforce": "enforce", "audit": "audit"}
    )
    graph.add_edge("enforce", "execute")
    graph.add_edge("execute", "audit")
    graph.add_edge("audit", END)

    return graph.compile()


async def run_query(
    *,
    domain: str,
    conn: psycopg.Connection,
    caller: Caller,
    policy_store: PolicyStore,
    audit_writer: AuditLogWriter,
    question: str | None = None,
    sql: str | None = None,
) -> QueryResult:
    """Run the query graph for one request and return its outcome.

    A `question` that cannot be mapped to any known table (FR-014,
    Scenario 10) does not raise — it returns a `QueryResult` with
    `decision=Decision.QUESTION_NOT_MAPPED`, `rows=None`, and
    `policy_version_used=None` (see this module's docstring)."""
    context = QueryGraphContext(
        domain=domain,
        conn=conn,
        caller=caller,
        policy_store=policy_store,
        audit_writer=audit_writer,
    )
    query_id = uuid4()
    final_state = await build_query_graph().ainvoke(
        {"question": question, "sql": sql, "query_id": query_id}, context=context
    )
    enforcement = final_state["enforcement"]
    return QueryResult(
        query_id=query_id,
        decision=enforcement.decision,
        reason_code=enforcement.reason_code,
        reason_message=enforcement.reason_message,
        policy_version_used=enforcement.policy_version_used,
        rows=final_state.get("rows"),
    )
