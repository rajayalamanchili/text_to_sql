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

Deliberately NOT yet handled here (later tasks, same file):
- The non-`SELECT`/multi-statement DML guard (FR-014) — T055.
- `role_gate` and row-policy predicate injection — T063, T059/T060 (both
  inside `enforcer.py`, which this graph already calls through).
- `question`'s "cannot be mapped to schema" case (FR-014, Scenario 10):
  `propose_sql` (T049) already detects this and raises
  `QuestionNotMappedError`, but this graph does not catch it — the exact
  contract (HTTP 200, its own audit-log `decision` value, since neither
  `allow`/`block` fits "no policy was evaluated at all") is T056's job to
  define and test against Scenario 10, not guessed at here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID, uuid4

import psycopg
import sqlglot
import structlog
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
from src.services.generation.sql_proposal import propose_sql
from src.services.policy.policy_store import PolicyStore

_logger = structlog.get_logger("steward.query_graph")


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


def _sql_parse_failure(exc: Exception) -> EnforcementResult:
    """A raw/generated SQL string that `sqlglot` itself can't parse fails
    closed exactly like any other unexpected enforcement-path error
    (Scenario 11) — this happens before `enforce()` is even reachable, so
    it can't rely on that function's own try/except."""
    _logger.warning("sql_parse_failure", error=str(exc), error_type=type(exc).__name__)
    return EnforcementResult(
        decision=Decision.BLOCK,
        reason_code=ReasonCode.ENFORCEMENT_ERROR,
        reason_message=render_reason_message(ReasonCode.ENFORCEMENT_ERROR),
        policy_version_used=None,
    )


def generate_node(state: QueryGraphState, runtime: Runtime[QueryGraphContext]) -> dict:
    schema = enumerate_schema(runtime.context.domain, runtime.context.conn)
    proposal = propose_sql(schema, question=state.get("question"), sql=state.get("sql"))
    return {"sql": proposal.sql}


def enforce_node(state: QueryGraphState, runtime: Runtime[QueryGraphContext]) -> dict:
    schema = enumerate_schema(runtime.context.domain, runtime.context.conn)
    try:
        statement = sqlglot.parse_one(state["sql"], read="postgres")
    except Exception as exc:  # noqa: BLE001 - fail closed on unparseable SQL
        return {"enforcement": _sql_parse_failure(exc)}
    result = enforce(statement, schema, runtime.context.policy_store)
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
    entry = AuditLogEntry.create(
        domain=runtime.context.domain,
        query_id=state["query_id"],
        actor_role=runtime.context.caller.role,
        decision=enforcement.decision,
        reason_code=enforcement.reason_code,
        reason_message=enforcement.reason_message,
        policy_version_used=enforcement.policy_version_used,
        raw_query_hash=hashlib.sha256(state["sql"].encode()).hexdigest(),
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
    graph.add_edge("generate", "enforce")
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

    Raises `QuestionNotMappedError` (from `sql_proposal.py`) if `question`
    cannot be mapped to any known table — see this module's docstring for
    why that case is deliberately not handled here yet.
    """
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
