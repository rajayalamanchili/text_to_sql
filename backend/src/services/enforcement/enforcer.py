"""Deterministic enforcement node (research.md §5/§9, FR-007/FR-008/FR-009/FR-014).

`enforce()` is the single decision point that replaces the prior
prototype's LLM-self-report flaw (Constitution Principle I): its only
inputs are the raw SQL text, the domain's enumerated schema, and the
active policy artifact — never anything an LLM reports about its own
query. It owns the *entire* raw-SQL-to-decision pipeline, including its
own parsing, rather than trusting an already-parsed AST handed to it —
this matters concretely for FR-014's multi-statement check: `sqlglot`'s
single-statement parser (`parse_one`) silently wraps stacked statements
into one `Block` node instead of raising, so detecting "more than one
statement" requires `sqlglot.parse()` (which returns every statement) run
directly against the raw text, before any other check.

Scope of this module today (FR-007, FR-008, FR-009, FR-014, Scenario 11):
1. FR-014's DML/multi-statement guard — structurally prior to everything
   else, including policy resolution (spec.md: "The non-`SELECT`/DML
   check... and the question-to-schema mapping check remain structurally
   prior to all of the above"). Its rejections always report
   `policy_version_used=None`, since no policy version is resolved yet at
   this point.
2. `allow`/`block` decisions and default-closed handling for any
   column/table absent from the active policy or unresolvable against the
   schema (FR-007, FR-009).
3. Fail-closed `ENFORCEMENT_ERROR` handling for unparseable SQL, a
   policy-load failure, or any other unexpected internal error (Scenario 11).
4. Row-policy predicate injection (FR-008, Scenario 5): once a query would
   otherwise be allowed, every referenced table carrying a
   `row_policy_template` gets that predicate AND-merged into its `WHERE`
   clause (`row_predicate_injector.py`, T059) — this never itself causes a
   rejection, except that a missing/blank `Caller.tenant_id` for a table
   that needs it surfaces as `ENFORCEMENT_ERROR` (research.md §7), via the
   same catch-all `except Exception` this function already applies to its
   post-DML-guard checks.

`role_gate` (FR-008, Scenario 7) is added by a later task (T063) as a
separate branch in this same file.

Every rejection this function can currently produce ranks in FR-007's
fixed severity order (highest first): `ENFORCEMENT_ERROR` > `NO_ACTIVE_POLICY`
> `COLUMN_BLOCKED` — chosen deterministically, never by AST scan order,
when a single query trips more than one violation at once. The FR-014
guard (multi-statement / non-`SELECT`) ranks above all of these, per the
"structurally prior" rule above, by virtue of running and returning
first, not via `_SEVERITY_RANK`.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
import structlog
from sqlglot import exp

from src.api.deps import Caller
from src.models.policy_artifact import PolicyAction, PolicyArtifact
from src.services.audit.audit_log import Decision, ReasonCode, render_reason_message
from src.services.enforcement.column_resolver import ColumnResolutionError, resolve_columns
from src.services.enforcement.row_predicate_injector import inject_row_policies
from src.services.enumeration.schema_enumerator import DomainSchemaSnapshot
from src.services.policy.policy_store import PolicyStore

_logger = structlog.get_logger("steward.enforcement")

# FR-007's severity ranking for co-occurring violations, lowest number wins.
# ROLE_GATE_MISMATCH (T063) is not yet produced by this module; its rank is
# reserved here so the ordering stays correct once that branch lands.
# Row-policy injection (Scenario 5) produces no distinct reason of its own
# — its only failure mode already falls under ENFORCEMENT_ERROR above.
_SEVERITY_RANK: dict[ReasonCode, int] = {
    ReasonCode.ENFORCEMENT_ERROR: 0,
    ReasonCode.NO_ACTIVE_POLICY: 1,
    ReasonCode.COLUMN_BLOCKED: 2,
    ReasonCode.ROLE_GATE_MISMATCH: 3,
}


@dataclass(frozen=True)
class EnforcementResult:
    """The enforcement node's decision for one query (data-model.md's
    `allow`/`block`/`mask` decision plus its reason, pre-audit-log)."""

    decision: Decision
    reason_code: ReasonCode | None
    reason_message: str | None
    policy_version_used: int | None
    enforced_sql: str | None = None
    """The SQL text to actually execute on `ALLOW` — the caller-submitted
    SQL with every applicable `row_policy_template` AND-merged in (T059).
    Always `None` on `BLOCK`/error outcomes, since nothing executes."""


def _blocked(
    reason_code: ReasonCode, *, policy_version_used: int | None, **params: object
) -> EnforcementResult:
    return EnforcementResult(
        decision=Decision.BLOCK,
        reason_code=reason_code,
        reason_message=render_reason_message(reason_code, **params),
        policy_version_used=policy_version_used,
    )


def _enforcement_error(exc: Exception, *, policy_version_used: int | None) -> EnforcementResult:
    _logger.warning("enforcement_error", error=str(exc), error_type=type(exc).__name__)
    return _blocked(ReasonCode.ENFORCEMENT_ERROR, policy_version_used=policy_version_used)


def _load_active_policy(
    policy_store: PolicyStore,
) -> tuple[PolicyArtifact | None, EnforcementResult | None]:
    """Resolve the domain's active policy version once, distinguishing
    "never published" (Scenario 6, `NO_ACTIVE_POLICY`) from "a version is
    published but its file is missing/corrupted" (Scenario 11,
    `ENFORCEMENT_ERROR`) — `PolicyStore` itself only reports the latter as
    a plain `None`/exception, so that distinction is made here."""
    try:
        version = policy_store.active_version()
    except Exception as exc:  # noqa: BLE001 - fail closed on any load error
        return None, _enforcement_error(exc, policy_version_used=None)

    if version is None:
        return None, _blocked(ReasonCode.NO_ACTIVE_POLICY, policy_version_used=None)

    try:
        artifact = policy_store.get_version(version)
    except Exception as exc:  # noqa: BLE001 - fail closed on any load error
        return None, _enforcement_error(exc, policy_version_used=None)

    if artifact is None:
        return None, _enforcement_error(
            FileNotFoundError(f"active policy version {version} is missing"),
            policy_version_used=None,
        )
    return artifact, None


def _dml_guard(sql: str, dialect: str) -> tuple[exp.Expression | None, EnforcementResult | None]:
    """FR-014: reject unconditionally, before any policy is even loaded —
    (a) any input that parses into more than one SQL statement
    (`MULTIPLE_STATEMENTS_REJECTED`, checked before (b) so a stacked
    `SELECT ...; DROP TABLE ...;` is never evaluated as "just inspect the
    first statement"), and (b) any single statement whose root is not a
    `SELECT` (`DML_REJECTED`). Both rejections report
    `policy_version_used=None`, since this guard runs structurally prior
    to policy resolution (spec.md)."""
    try:
        statements = [statement for statement in sqlglot.parse(sql, read=dialect) if statement]
    except Exception as exc:  # noqa: BLE001 - unparseable SQL fails closed (Scenario 11)
        return None, _enforcement_error(exc, policy_version_used=None)

    if len(statements) == 0:
        return None, _enforcement_error(
            ValueError("no SQL statement found"), policy_version_used=None
        )
    if len(statements) > 1:
        return None, _blocked(ReasonCode.MULTIPLE_STATEMENTS_REJECTED, policy_version_used=None)

    statement = statements[0]
    if not isinstance(statement, exp.Select):
        return None, _blocked(ReasonCode.DML_REJECTED, policy_version_used=None)

    return statement, None


def enforce(
    sql: str,
    schema: DomainSchemaSnapshot,
    policy_store: PolicyStore,
    caller: Caller,
    *,
    dialect: str = "postgres",
) -> EnforcementResult:
    """Deterministically decide `allow`/`block` for `sql` against the
    domain's active policy. Parses `sql` itself and applies FR-014's
    DML/multi-statement guard before doing anything else; the active
    policy version is then resolved once and reused for every remaining
    check (FR-007 — a concurrent publish cannot affect this evaluation).
    `caller` is required for row-policy predicate injection (Scenario 5) —
    it's never consulted for column-level allow/block decisions."""
    statement, guard_error = _dml_guard(sql, dialect)
    if guard_error is not None:
        return guard_error

    artifact, error = _load_active_policy(policy_store)
    if error is not None:
        return error

    try:
        resolved_columns = resolve_columns(statement, schema)
    except ColumnResolutionError:
        # Anything the resolver couldn't tie to a known, policy-covered
        # table/column defaults closed (FR-009, Scenario 6) — this is not
        # an unexpected internal error, so it does not become
        # ENFORCEMENT_ERROR.
        return _blocked(ReasonCode.NO_ACTIVE_POLICY, policy_version_used=artifact.version)
    except Exception as exc:  # noqa: BLE001 - fail closed on any unexpected error
        return _enforcement_error(exc, policy_version_used=artifact.version)

    try:
        policy_columns = {
            (table.table_name, column_name): policy_column
            for table in artifact.tables
            for column_name, policy_column in table.columns.items()
        }

        no_active_policy_rank = _SEVERITY_RANK[ReasonCode.NO_ACTIVE_POLICY]
        no_active_policy = (no_active_policy_rank, ReasonCode.NO_ACTIVE_POLICY, {})

        violations: list[tuple[int, ReasonCode, dict[str, object]]] = []
        for resolved in resolved_columns:
            policy_column = policy_columns.get((resolved.table, resolved.column))
            if policy_column is None:
                violations.append(no_active_policy)
            elif policy_column.action == PolicyAction.ALLOW:
                continue
            elif policy_column.action == PolicyAction.BLOCK:
                violations.append(
                    (
                        _SEVERITY_RANK[ReasonCode.COLUMN_BLOCKED],
                        ReasonCode.COLUMN_BLOCKED,
                        {"column": resolved.column},
                    )
                )
            else:
                # PolicyAction.ROLE_GATE: real role-based evaluation is
                # T063's job, not yet wired up here. Defaulting to a
                # violation (rather than silently allowing) keeps this
                # fail-closed in the meantime (Constitution Principle II).
                violations.append(no_active_policy)

        if violations:
            violations.sort(key=lambda violation: violation[0])
            _, reason_code, params = violations[0]
            return _blocked(reason_code, policy_version_used=artifact.version, **params)

        # Scenario 5: never itself a distinct violation — a missing/blank
        # tenant for a table that needs it falls through to this block's
        # own `except Exception` below, becoming ENFORCEMENT_ERROR like any
        # other unexpected failure at this stage.
        enforced_statement = inject_row_policies(
            statement, artifact.tables, caller, dialect=dialect
        )

        return EnforcementResult(
            decision=Decision.ALLOW,
            reason_code=None,
            reason_message=None,
            policy_version_used=artifact.version,
            enforced_sql=enforced_statement.sql(dialect=dialect),
        )
    except Exception as exc:  # noqa: BLE001 - fail closed on any unexpected error
        return _enforcement_error(exc, policy_version_used=artifact.version)
