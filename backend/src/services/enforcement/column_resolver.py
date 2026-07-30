"""sqlglot-based column resolver (research.md §5, FR-007/FR-009).

Given an already-parsed single `SELECT` statement (the DML/statement-type
guard runs upstream, in the enforcement node — this module never sees a
non-`SELECT` root) and the domain's enumerated schema, resolves every
column reference — expanding `SELECT *`/`table.*`, joins, CTEs, and
subqueries — to concrete `(table, column)` pairs naming only real, known
base tables.

Uses sqlglot's own `qualify()` optimizer pass rather than hand-rolled AST
traversal (Constitution Principle I: a real, testable, AST-level check —
`qualify()` is exactly the mechanism sqlglot itself uses to bind every
column/wildcard to its source table across joins, CTEs, and subqueries,
so this never depends on anything the LLM reports about its own query).

Fails closed: any column, unexpandable wildcard, or table reference that
cannot be tied to a known base table in the given schema raises
`ColumnResolutionError` for the *whole* query (FR-009, Scenario 6) —
never a partial result a caller could mistake for "nothing sensitive
found here."
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp
from sqlglot.errors import OptimizeError
from sqlglot.optimizer.qualify import qualify

from src.services.enumeration.schema_enumerator import DomainSchemaSnapshot


@dataclass(frozen=True)
class ResolvedColumn:
    """One concrete `table.column` a query touches, post-resolution."""

    table: str
    column: str


class ColumnResolutionError(Exception):
    """Raised when `resolve_columns` cannot tie every column, wildcard, or
    table reference in a query to a known base table in the domain's
    schema. Callers (the enforcement node, T048) MUST treat this as a
    default-closed rejection (FR-009, Scenario 6) — not as an unexpected
    internal error."""


def _schema_dict(schema: DomainSchemaSnapshot) -> dict[str, dict[str, str]]:
    return {
        table.table_name: {column.column_name: column.data_type for column in table.columns}
        for table in schema.tables
    }


def _is_unexpanded_wildcard(projection: exp.Expression) -> bool:
    """True for a `*`/`table.*` projection sqlglot could not expand into
    concrete columns — which only happens when its table isn't in the
    given schema."""
    return isinstance(projection, exp.Star) or (
        isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
    )


def resolve_columns(
    statement: exp.Expression, schema: DomainSchemaSnapshot, *, dialect: str = "postgres"
) -> list[ResolvedColumn]:
    """Resolve every column `statement` (a parsed single `SELECT`) touches
    to concrete `(table, column)` pairs, expanding `SELECT *`/`table.*`,
    joins, CTEs, and subqueries via sqlglot's `qualify()` pass.

    Raises `ColumnResolutionError` if any reference — a column, an
    unexpandable wildcard, or a table name itself — cannot be tied to a
    table present in `schema`. FR-009's default-closed rule applies to
    the whole query in that case, not just the offending reference.
    """
    schema_dict = _schema_dict(schema)

    try:
        qualified = qualify(
            statement.copy(),
            schema=schema_dict,
            dialect=dialect,
            infer_schema=False,
            validate_qualify_columns=True,
        )
    except OptimizeError as exc:
        raise ColumnResolutionError(f"could not resolve columns: {exc}") from exc

    cte_aliases = {cte.alias for cte in qualified.find_all(exp.CTE)}
    # sqlglot reports `exp.Column.table` as whatever name is in scope for
    # that reference — the alias, if the query gave the table one, else
    # the real table name — so every real base-table reference needs
    # mapping back through its alias to compare against `schema_dict`.
    alias_to_table = {
        table_node.alias_or_name: table_node.name
        for table_node in qualified.find_all(exp.Table)
        if table_node.name not in cte_aliases
    }

    for table_node in qualified.find_all(exp.Table):
        if table_node.name in cte_aliases:
            continue
        if table_node.name not in schema_dict:
            raise ColumnResolutionError(f"unknown table: {table_node.name!r}")

    for select in qualified.find_all(exp.Select):
        for projection in select.expressions:
            if _is_unexpanded_wildcard(projection):
                raise ColumnResolutionError(
                    "could not expand a '*' projection against a known table"
                )

    resolved = set()
    for column in qualified.find_all(exp.Column):
        table_name = alias_to_table.get(column.table, column.table)
        if table_name in schema_dict:
            resolved.add(ResolvedColumn(table=table_name, column=column.name))
    return sorted(resolved, key=lambda rc: (rc.table, rc.column))
