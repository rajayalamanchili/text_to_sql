"""Classification LangGraph graph (research.md §9).

`enumerate_schema -> heuristic_classify -> [confidence gate] ->
llm_classify (conditional) -> persist`. The confidence-gate edge skips
the `llm_classify` node entirely when every column already cleared the
auto-approval threshold on the heuristic pass alone (research.md §4);
when it does run, it still only calls the LLM for the subset of columns
still below threshold, never re-scoring an already-confident column.

Runtime dependencies (the open DB connection, the LLM client, and the
persistence store) are injected via LangGraph's `context_schema`
mechanism rather than living in graph state, so state itself stays pure
data and nothing requires the connection/client to be picklable/
checkpointable. `ClassificationStore` is a structural protocol (mirrors
`AuditLogSink` in `services/audit/audit_log.py`) — its concrete
implementation (persistence.py, T027) is what actually writes
`classify_*` audit log entries; this graph only calls `store.save`.

Raw sample values fetched for the LLM pass are masked immediately inside
`llm_classify_node` and never appear in graph state — only the resulting
`LLMResult` (already scrubbed of any value fragment, research.md §3)
does (Constitution Principle I).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict, runtime_checkable
from uuid import uuid4

import psycopg
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from psycopg import sql

from src.models.column_classification import (
    AUTO_APPROVAL_CONFIDENCE_THRESHOLD,
    ClassificationStatus,
    ColumnClassification,
)
from src.services.classification.confidence import CombinedResult, combine_confidence
from src.services.classification.heuristic_classifier import HeuristicResult, classify_heuristically
from src.services.classification.llm_classifier import (
    LLMClassifierClient,
    LLMResult,
    classify_with_llm,
)
from src.services.classification.masking import mask_column_profile
from src.services.enumeration.schema_enumerator import (
    ColumnSchema,
    DomainSchemaSnapshot,
    enumerate_schema,
)

DEFAULT_SAMPLE_SIZE = 20


@runtime_checkable
class ClassificationStore(Protocol):
    """Persistence hook for a classified column (T027, data-model.md).
    Left injectable rather than importing a concrete DB module here —
    no persistence module exists yet in this milestone's task sequence."""

    async def save(self, record: ColumnClassification) -> None: ...


@dataclass
class ClassificationGraphContext:
    domain: str
    conn: psycopg.Connection
    llm_client: LLMClassifierClient
    store: ClassificationStore


class ClassificationGraphState(TypedDict, total=False):
    snapshot: DomainSchemaSnapshot
    heuristic_results: dict[str, HeuristicResult]
    llm_results: dict[str, LLMResult]
    classifications: list[ColumnClassification]


def _column_key(table_name: str, column_name: str) -> str:
    return f"{table_name}.{column_name}"


def enumerate_node(
    state: ClassificationGraphState, runtime: Runtime[ClassificationGraphContext]
) -> dict:
    snapshot = enumerate_schema(runtime.context.domain, runtime.context.conn)
    return {"snapshot": snapshot}


def heuristic_classify_node(
    state: ClassificationGraphState, runtime: Runtime[ClassificationGraphContext]
) -> dict:
    results: dict[str, HeuristicResult] = {}
    for table in state["snapshot"].tables:
        for column in table.columns:
            results[_column_key(table.table_name, column.column_name)] = classify_heuristically(
                column
            )
    return {"heuristic_results": results}


def confidence_gate(
    state: ClassificationGraphState, runtime: Runtime[ClassificationGraphContext]
) -> str:
    needs_llm = any(
        result.score < AUTO_APPROVAL_CONFIDENCE_THRESHOLD
        for result in state["heuristic_results"].values()
    )
    return "llm_classify" if needs_llm else "persist"


async def llm_classify_node(
    state: ClassificationGraphState, runtime: Runtime[ClassificationGraphContext]
) -> dict:
    columns_by_key: dict[str, ColumnSchema] = {
        _column_key(table.table_name, column.column_name): column
        for table in state["snapshot"].tables
        for column in table.columns
    }

    llm_results: dict[str, LLMResult] = {}
    for key, heuristic in state["heuristic_results"].items():
        if heuristic.score >= AUTO_APPROVAL_CONFIDENCE_THRESHOLD:
            continue
        table_name, column_name = key.split(".", 1)
        column = columns_by_key[key]
        sample_values = _fetch_sample_values(runtime.context.conn, table_name, column_name)
        profile = mask_column_profile(column, sample_values)
        llm_results[key] = await classify_with_llm(profile, runtime.context.llm_client)
    return {"llm_results": llm_results}


async def persist_node(
    state: ClassificationGraphState, runtime: Runtime[ClassificationGraphContext]
) -> dict:
    llm_results = state.get("llm_results", {})
    classifications: list[ColumnClassification] = []
    for table in state["snapshot"].tables:
        for column in table.columns:
            key = _column_key(table.table_name, column.column_name)
            heuristic = state["heuristic_results"][key]
            llm = llm_results.get(key)
            combined = combine_confidence(heuristic, llm)
            record = _build_record(
                runtime.context.domain, table.table_name, column, combined, heuristic, llm
            )
            await runtime.context.store.save(record)
            classifications.append(record)
    return {"classifications": classifications}


def _build_record(
    domain: str,
    table_name: str,
    column: ColumnSchema,
    combined: CombinedResult,
    heuristic: HeuristicResult,
    llm: LLMResult | None,
) -> ColumnClassification:
    status = (
        ClassificationStatus.AUTO_APPROVED
        if combined.confidence >= AUTO_APPROVAL_CONFIDENCE_THRESHOLD
        else ClassificationStatus.PENDING_REVIEW
    )
    return ColumnClassification(
        id=uuid4(),
        domain=domain,
        table_name=table_name,
        column_name=column.column_name,
        data_type=column.data_type,
        cardinality_ratio=column.cardinality_ratio,
        classification=combined.classification,
        heuristic_score=heuristic.score,
        llm_score=llm.score if llm is not None else None,
        confidence=combined.confidence,
        source=combined.source,
        status=status,
        llm_rationale=llm.rationale if llm is not None else None,
    )


def _fetch_sample_values(
    conn: psycopg.Connection, table_name: str, column_name: str, limit: int = DEFAULT_SAMPLE_SIZE
) -> list[object]:
    """Fetch up to `limit` raw values for `column_name`, for masking
    only — the caller (`llm_classify_node`) must mask this list
    immediately and never let it escape into graph state or a log."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT {} FROM {} LIMIT %s").format(
                sql.Identifier(column_name), sql.Identifier(table_name)
            ),
            (limit,),
        )
        return [row[0] for row in cur.fetchall()]


def build_classification_graph():
    graph = StateGraph(
        state_schema=ClassificationGraphState, context_schema=ClassificationGraphContext
    )
    graph.add_node("enumerate", enumerate_node)
    graph.add_node("heuristic_classify", heuristic_classify_node)
    graph.add_node("llm_classify", llm_classify_node)
    graph.add_node("persist", persist_node)

    graph.add_edge(START, "enumerate")
    graph.add_edge("enumerate", "heuristic_classify")
    graph.add_conditional_edges(
        "heuristic_classify",
        confidence_gate,
        {"llm_classify": "llm_classify", "persist": "persist"},
    )
    graph.add_edge("llm_classify", "persist")
    graph.add_edge("persist", END)

    return graph.compile()


async def run_classification(
    *,
    domain: str,
    conn: psycopg.Connection,
    llm_client: LLMClassifierClient,
    store: ClassificationStore,
) -> list[ColumnClassification]:
    """Run the full classification pipeline for `domain` and return the
    persisted `ColumnClassification` records."""
    context = ClassificationGraphContext(
        domain=domain, conn=conn, llm_client=llm_client, store=store
    )
    result = await build_classification_graph().ainvoke({}, context=context)
    return result["classifications"]
