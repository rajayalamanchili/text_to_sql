"""Minimal SQL proposal step (research.md §5/§9, FR-014).

Milestone 1 does not require production NL→SQL quality (spec.md "Out of
Scope": "SQL generation quality/accuracy improvements beyond what is
needed to demonstrate enforcement" are explicitly deferred) — this step
exists only to exercise the enforcement node end-to-end. It accepts
either a raw `sql` string (used as-is, e.g. Scenario 4's "LLM-generated
SQL query" is simulated by supplying `sql` directly) or a natural-
language `question`, mapped to schema via a deterministic pre-generation
token match — no LLM call is ever made to interpret the question.

A question whose tokens match none of the domain's known table/column
names raises `QuestionNotMappedError` before any SQL is built (FR-014,
Scenario 10) — "cannot be mapped" is determined here, prior to and
independent of generation quality.

Known gap: FR-014 also calls for matching against "a policy-configured
synonym list," but no such list exists anywhere in the current
`PolicyArtifact`/`policy-artifact.schema.yaml` shape (data-model.md) —
this only matches literal table/column name tokens. This is a
conservative gap (it can only make *more* questions look unmapped, never
fewer — never a security-relevant over-match), not a silent correctness
bug, but it should be resolved (likely via a `/speckit.clarify` session
extending the policy artifact schema) before this is considered a
complete implementation of FR-014's synonym requirement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.services.enumeration.schema_enumerator import DomainSchemaSnapshot, TableSchema

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+")


class QuestionNotMappedError(Exception):
    """Raised when a natural-language question's tokens match none of the
    domain's known table/column names (FR-014, Scenario 10). Callers MUST
    NOT generate or execute any SQL, and MUST NOT reveal which
    tables/columns exist, when this is raised."""


@dataclass(frozen=True)
class SqlProposal:
    sql: str


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_PATTERN.findall(text)}


def _match_table(question_tokens: set[str], schema: DomainSchemaSnapshot) -> TableSchema | None:
    for table in schema.tables:
        table_tokens = _tokenize(table.table_name)
        column_tokens = {
            token for column in table.columns for token in _tokenize(column.column_name)
        }
        if question_tokens & (table_tokens | column_tokens):
            return table
    return None


def propose_sql(
    schema: DomainSchemaSnapshot, *, question: str | None = None, sql: str | None = None
) -> SqlProposal:
    """Build a `SqlProposal` from either a raw `sql` string (used as-is,
    no mapping check performed) or a `question` (matched deterministically
    against `schema`, per FR-014). Exactly one of `question`/`sql` must be
    given (contracts/api.md's `/query` body accepts one or the other).

    Raises `QuestionNotMappedError` if `question` matches no known table.
    """
    if sql is not None:
        return SqlProposal(sql=sql)
    if question is None:
        raise ValueError("propose_sql requires either `question` or `sql`")

    question_tokens = _tokenize(question)
    matched_table = _match_table(question_tokens, schema)
    if matched_table is None:
        raise QuestionNotMappedError(f"question does not map to any known table: {question!r}")

    matched_columns = [
        column.column_name
        for column in matched_table.columns
        if column.column_name.lower() in question_tokens
    ]
    projection = ", ".join(matched_columns) if matched_columns else "*"
    return SqlProposal(sql=f"SELECT {projection} FROM {matched_table.table_name}")
