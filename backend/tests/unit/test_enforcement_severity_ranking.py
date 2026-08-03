"""Unit tests for FR-007's severity-ranking rule (T052a).

When a single query trips more than one independent column/table-level
policy violation, the reported reason is chosen by a fixed severity
order — never by AST scan order:

    ENFORCEMENT_ERROR / NO_ACTIVE_POLICY / COLUMN_BLOCKED  (highest; any
    one alone rejects the whole query)
        > ROLE_GATE_MISMATCH
        > row-policy predicate injection (doesn't itself cause rejection)

`role_gate` (T063) is wired up in `enforcer.py`, adding the fourth tier:
`ENFORCEMENT_ERROR` > `NO_ACTIVE_POLICY` > `COLUMN_BLOCKED` >
`ROLE_GATE_MISMATCH`. Row-policy injection (T059/T060) is wired up too,
but it produces no distinct reason code of its own — its only failure
mode already falls under `ENFORCEMENT_ERROR` above — so it needs no
separate ranking tier here.
"""

from __future__ import annotations

import pytest
from src.api.deps import Caller
from src.config.domains import DomainConfig
from src.models.column_classification import Classification
from src.models.policy_artifact import PolicyAction, PolicyColumn, PolicyTable
from src.services.audit.audit_log import ActorRole, Decision, ReasonCode
from src.services.enforcement.enforcer import enforce
from src.services.enumeration.schema_enumerator import (
    ColumnSchema,
    DomainSchemaSnapshot,
    TableSchema,
)
from src.services.policy.policy_store import PolicyStore


def _caller() -> Caller:
    return Caller(role=ActorRole.ANALYST)


def _schema(**tables: list[str]) -> DomainSchemaSnapshot:
    return DomainSchemaSnapshot(
        domain="fintech",
        tables=[
            TableSchema(
                table_name=table_name,
                columns=[
                    ColumnSchema(column_name=column_name, data_type="text", cardinality_ratio=0.5)
                    for column_name in column_names
                ],
            )
            for table_name, column_names in tables.items()
        ],
    )


@pytest.fixture
def policy_store(tmp_path) -> PolicyStore:
    policy_dir = tmp_path / "policies" / "fintech"
    policy_dir.mkdir(parents=True)
    domain_config = DomainConfig(
        name="fintech",
        domain_dir=tmp_path / "domains" / "fintech",
        policy_dir=policy_dir,
        schema_sql_path=tmp_path / "schema.sql",
        seed_script_path=tmp_path / "seed.py",
        database_url=None,
    )
    return PolicyStore(domain_config)


def test_column_blocked_alone_is_reported_as_column_blocked(policy_store):
    """Sanity baseline: with no higher-severity violation present, the
    lowest-tier violation this file covers is still correctly reported."""
    policy_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "member_ssn": PolicyColumn(
                        action=PolicyAction.BLOCK, classification=Classification.PII_DIRECT
                    )
                },
            )
        ],
        approved_by="admin",
    )
    schema = _schema(claims=["member_ssn"])

    result = enforce("SELECT member_ssn FROM claims", schema, policy_store, _caller())

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.COLUMN_BLOCKED


def test_no_active_policy_outranks_column_blocked(policy_store):
    """A query referencing both a column absent from the published
    policy (NO_ACTIVE_POLICY) and a column explicitly blocked
    (COLUMN_BLOCKED) must report NO_ACTIVE_POLICY — the higher-severity
    reason — regardless of which column the AST happens to list first."""
    policy_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "member_ssn": PolicyColumn(
                        action=PolicyAction.BLOCK, classification=Classification.PII_DIRECT
                    )
                },
            )
        ],
        approved_by="admin",
    )
    schema = _schema(claims=["member_ssn", "unpublished_column"])

    # AST scan order lists the blocked column first; the ranking must
    # still surface NO_ACTIVE_POLICY, not COLUMN_BLOCKED.
    result = enforce(
        "SELECT member_ssn, unpublished_column FROM claims", schema, policy_store, _caller()
    )

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.NO_ACTIVE_POLICY

    # Reversing the column order in the AST must not change the outcome.
    reversed_result = enforce(
        "SELECT unpublished_column, member_ssn FROM claims", schema, policy_store, _caller()
    )

    assert reversed_result.decision == Decision.BLOCK
    assert reversed_result.reason_code == ReasonCode.NO_ACTIVE_POLICY


def test_enforcement_error_outranks_no_active_policy_and_column_blocked(policy_store):
    """A policy-load failure must win even though the query also
    references both an absent-from-policy column and a column that a
    (corrupted, unreadable) policy would have explicitly blocked."""
    policy_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "member_ssn": PolicyColumn(
                        action=PolicyAction.BLOCK, classification=Classification.PII_DIRECT
                    )
                },
            )
        ],
        approved_by="admin",
    )
    corrupted_path = policy_store._version_dir(1) / "policy.yaml"  # noqa: SLF001
    corrupted_path.write_text("not: [valid, policy, {shape")
    schema = _schema(claims=["member_ssn", "unpublished_column"])

    result = enforce(
        "SELECT member_ssn, unpublished_column FROM claims", schema, policy_store, _caller()
    )

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.ENFORCEMENT_ERROR


def test_column_blocked_outranks_role_gate_mismatch(policy_store):
    """T063: a query touching both a `role_gate` column the caller
    doesn't qualify for and an explicitly `block`ed column must report
    `COLUMN_BLOCKED` — the higher-severity reason — not whichever the
    AST scan happens to reach first."""
    policy_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "member_ssn": PolicyColumn(
                        action=PolicyAction.BLOCK, classification=Classification.PII_DIRECT
                    ),
                    "claim_amount": PolicyColumn(
                        action=PolicyAction.ROLE_GATE,
                        roles=["admin"],
                        classification=Classification.SENSITIVE_CATEGORY,
                    ),
                },
            )
        ],
        approved_by="admin",
    )
    schema = _schema(claims=["member_ssn", "claim_amount"])

    result = enforce("SELECT claim_amount, member_ssn FROM claims", schema, policy_store, _caller())

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.COLUMN_BLOCKED
