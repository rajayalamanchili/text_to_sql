"""Deterministic enforcement node (research.md §5/§9, FR-007/FR-008/FR-009).

`enforce()` is the single decision point that replaces the prior
prototype's LLM-self-report flaw (Constitution Principle I): its only
inputs are the parsed SQL AST, the domain's enumerated schema, and the
active policy artifact — never anything an LLM reports about its own
query.

Scope of this module today: `allow`/`block` decisions and default-closed
handling for any column/table absent from the active policy or
unresolvable against the schema (FR-007, FR-009), plus fail-closed
`ENFORCEMENT_ERROR` handling for a policy-load failure or any other
unexpected internal error (FR-007, Scenario 11). `role_gate` (FR-008,
Scenario 7), row-policy predicate injection (Scenario 5), and the
upstream non-`SELECT`/multi-statement guard (FR-014) are added by later
tasks (T063, T059/T060, T055 respectively) as separate branches in this
same file — `statement` here is assumed already validated as a single
parsed `SELECT` by that upstream guard.

Every rejection this function can currently produce ranks in FR-007's
fixed severity order (highest first): `ENFORCEMENT_ERROR` > `NO_ACTIVE_POLICY`
> `COLUMN_BLOCKED` — chosen deterministically, never by AST scan order,
when a single query trips more than one violation at once.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlglot import exp

from src.models.policy_artifact import PolicyAction, PolicyArtifact
from src.services.audit.audit_log import Decision, ReasonCode, render_reason_message
from src.services.enforcement.column_resolver import ColumnResolutionError, resolve_columns
from src.services.enumeration.schema_enumerator import DomainSchemaSnapshot
from src.services.policy.policy_store import PolicyStore

_logger = structlog.get_logger("steward.enforcement")

# FR-007's severity ranking for co-occurring violations, lowest number wins.
# ROLE_GATE_MISMATCH (T063) and row-policy injection (T059/T060) are not
# yet produced by this module; their rank is reserved here so the ordering
# stays correct once those branches land.
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


def enforce(
    statement: exp.Expression, schema: DomainSchemaSnapshot, policy_store: PolicyStore
) -> EnforcementResult:
    """Deterministically decide `allow`/`block` for `statement` (an
    already-validated single `SELECT`) against the domain's active
    policy, resolved once at the start of this call and reused for every
    check (FR-007 — a concurrent publish cannot affect this evaluation)."""
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

        return EnforcementResult(
            decision=Decision.ALLOW,
            reason_code=None,
            reason_message=None,
            policy_version_used=artifact.version,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed on any unexpected error
        return _enforcement_error(exc, policy_version_used=artifact.version)
