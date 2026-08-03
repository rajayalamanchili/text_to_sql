"""Role-gate exclusion helper (FR-008, Scenario 7).

`on_role_mismatch: exclude` lets a `role_gate` column be silently dropped
from a query's results instead of rejecting the whole query outright —
but FR-008 defines that only for one narrow shape: the column referenced
directly, unwrapped, in the query's own flat top-level `SELECT` list.
Every other shape — inside an aggregate/function (e.g.
`COUNT(diagnosis_code)`), via `SELECT *`, or referenced only in a
`WHERE`/`JOIN` clause and never actually selected — is unsupported for
`exclude` and the caller MUST treat it as `reject` instead (spec.md
FR-008 Clarifications, Session 2026-07-27). This module only answers
"is this one of the supported shapes, and if so which AST node is it" —
deciding what to do with that answer (reject vs. actually remove the
node, and whether removing it would leave no projections at all) is the
enforcement node's job (`enforcer.py`, T063).
"""

from __future__ import annotations

from sqlglot import exp
from sqlglot.errors import OptimizeError
from sqlglot.optimizer.qualify import qualify

from src.services.enumeration.schema_enumerator import DomainSchemaSnapshot


def _is_wildcard(projection: exp.Expression) -> bool:
    return isinstance(projection, exp.Star) or (
        isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
    )


def find_excludable_projection(
    statement: exp.Select,
    table: str,
    column: str,
    schema: DomainSchemaSnapshot,
    *,
    dialect: str = "postgres",
) -> exp.Expression | None:
    """Return the bare projection node in `statement`'s own top-level
    `SELECT` list that resolves to `table.column`, if `exclude` can apply
    to it. Returns `None` for every unsupported shape.

    A `SELECT *`/`table.*` anywhere in the top-level projection list
    disqualifies the whole statement from consideration — this function
    doesn't track wildcard expansion positionally, so it can't safely
    tell which expanded column came from which original projection.
    """
    if any(_is_wildcard(projection) for projection in statement.expressions):
        return None

    schema_dict = {
        table_schema.table_name: {
            column_schema.column_name: column_schema.data_type
            for column_schema in table_schema.columns
        }
        for table_schema in schema.tables
    }
    try:
        qualified = qualify(
            statement.copy(),
            schema=schema_dict,
            dialect=dialect,
            infer_schema=False,
            validate_qualify_columns=True,
        )
    except OptimizeError:
        return None

    cte_aliases = {cte.alias for cte in qualified.find_all(exp.CTE)}
    alias_to_table = {
        table_node.alias_or_name: table_node.name
        for table_node in qualified.find_all(exp.Table)
        if table_node.name not in cte_aliases
    }

    for index, projection in enumerate(qualified.expressions):
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        if not isinstance(inner, exp.Column):
            continue
        resolved_table = alias_to_table.get(inner.table, inner.table)
        if resolved_table == table and inner.name == column:
            # Positional correspondence with the original statement holds
            # because `qualify()` only annotates/wraps existing top-level
            # projections here — it never adds, removes, or reorders them
            # (the one case it does expand, `SELECT *`, was ruled out
            # above).
            return statement.expressions[index]
    return None
