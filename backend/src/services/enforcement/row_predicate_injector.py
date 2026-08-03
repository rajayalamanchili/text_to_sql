"""Row-predicate injector (research.md §5.4, FR-008, Scenario 5).

For every base-table reference a query makes to a table carrying a
`row_policy_template` (e.g. `"tenant_id = :current_tenant"`), AND-merges
that predicate into the *owning* `SELECT`'s `WHERE` clause — creating the
clause if it's absent, and wrapping any existing `WHERE` condition rather
than overwriting or stripping it (spec.md Clarifications, Session
2026-07-23: "wraps the LLM's existing `WHERE` clause in parentheses and
ANDs it with the policy's own predicate... can only ever narrow the
result set, never widen it, regardless of what the LLM's clause
contains"). This is pure AST manipulation via `sqlglot` — never string
concatenation, so the guardrail itself can't introduce an injection-style
bug (research.md §5).

The `:current_tenant` placeholder is bound from `Caller.tenant_id`
(`X-Steward-Tenant`, research.md §7) as a quoted SQL literal, never
interpolated into template text. Milestone 1 supports exactly this one
placeholder name — `PolicyTable`'s own publish-time validator already
guarantees no other `:name` token can appear in a `row_policy_template`
(`src/models/policy_artifact.py`) — so this module introduces no general
placeholder-resolution mechanism (research.md §7).

A table referenced more than once in the same query (self-join, a
governed table appearing in two different subqueries) gets the predicate
injected once per occurrence, each correctly qualified by that
occurrence's own alias, so every instance is scoped — not just the
first one found.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

from src.api.deps import Caller
from src.models.policy_artifact import SUPPORTED_ROW_POLICY_PLACEHOLDER, PolicyTable

_PLACEHOLDER_NAME = SUPPORTED_ROW_POLICY_PLACEHOLDER.removeprefix(":")


class TenantResolutionError(Exception):
    """Raised when a query references a table whose `row_policy_template`
    needs `:current_tenant` but `Caller.tenant_id` is absent or malformed
    (research.md §7, data-model.md#Caller, spec.md FR-008/Scenario 5).
    Callers (the enforcement node, T060) MUST treat this as a fail-closed
    `ENFORCEMENT_ERROR` — a tenant-resolution failure, not a distinct
    policy violation."""


def inject_row_policies(
    statement: exp.Expression,
    tables: list[PolicyTable],
    caller: Caller,
    *,
    dialect: str = "postgres",
) -> exp.Expression:
    """Return a copy of `statement` with every governed table's
    `row_policy_template` AND-merged into its owning `SELECT`'s `WHERE`
    clause. Tables with no `row_policy_template` (or not referenced at
    all) are untouched; if none of `tables` carries one, `statement` is
    returned unchanged.

    Raises `TenantResolutionError` if any referenced governed table's
    template needs `:current_tenant` and `caller.tenant_id` is
    absent/blank.
    """
    templates = {
        table.table_name: table.row_policy_template for table in tables if table.row_policy_template
    }
    if not templates:
        return statement

    result = statement.copy()
    cte_aliases = {cte.alias for cte in result.find_all(exp.CTE)}

    # Group by owning SELECT (by identity) since the same governed table
    # can be referenced more than once within one SELECT (self-join).
    predicates_by_select: dict[int, tuple[exp.Select, list[exp.Condition]]] = {}

    for table_node in result.find_all(exp.Table):
        if table_node.name in cte_aliases:
            continue
        template = templates.get(table_node.name)
        if template is None:
            continue

        owning_select = table_node.find_ancestor(exp.Select)
        if owning_select is None:
            raise TenantResolutionError(
                f"cannot resolve an owning SELECT for row-policy-governed table {table_node.name!r}"
            )

        predicate = _bind_predicate(template, table_node.alias_or_name, caller, dialect=dialect)
        key = id(owning_select)
        _, predicates = predicates_by_select.setdefault(key, (owning_select, []))
        predicates.append(predicate)

    for owning_select, predicates in predicates_by_select.values():
        _merge_where(owning_select, predicates)

    return result


def _bind_predicate(
    template: str, table_alias: str, caller: Caller, *, dialect: str
) -> exp.Condition:
    """Parse `template` and bind its `:current_tenant` placeholder (if
    any) to `caller.tenant_id` as a quoted literal, then qualify every
    bare column reference with `table_alias` so the predicate applies to
    this specific table occurrence, not just whichever one happens to be
    unaliased."""
    predicate = sqlglot.parse_one(template, into=exp.Condition, read=dialect)

    placeholder = predicate.find(exp.Placeholder)
    if placeholder is not None:
        if placeholder.this != _PLACEHOLDER_NAME:
            # `PolicyTable`'s publish-time validator already rejects any
            # other placeholder name (src/models/policy_artifact.py); this
            # is a defensive backstop, not a reachable path in practice.
            raise TenantResolutionError(
                f"unsupported row-policy placeholder {placeholder.this!r}; only "
                f"{SUPPORTED_ROW_POLICY_PLACEHOLDER!r} is supported in Milestone 1"
            )
        tenant_id = caller.tenant_id.strip() if caller.tenant_id else ""
        if not tenant_id:
            raise TenantResolutionError(
                "row policy requires Caller.tenant_id (X-Steward-Tenant header), "
                "but it is absent or blank"
            )
        placeholder.replace(exp.Literal.string(tenant_id))

    for column in predicate.find_all(exp.Column):
        if not column.table:
            column.set("table", exp.to_identifier(table_alias))

    return predicate


def _merge_where(select: exp.Select, predicates: list[exp.Condition]) -> None:
    combined = predicates[0]
    for predicate in predicates[1:]:
        combined = combined.and_(predicate)

    existing = select.args.get("where")
    merged = existing.this.and_(combined) if existing is not None else combined
    select.set("where", exp.Where(this=merged))
