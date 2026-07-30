import pytest
import yaml
from src.config.domains import DomainConfig
from src.models.column_classification import Classification
from src.models.policy_artifact import PolicyAction, PolicyColumn, PolicyTable
from src.services.audit.audit_log import Decision, ReasonCode
from src.services.enforcement.enforcer import enforce
from src.services.enumeration.schema_enumerator import (
    ColumnSchema,
    DomainSchemaSnapshot,
    TableSchema,
)
from src.services.policy.policy_store import PolicyStore


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


def test_allow_when_all_columns_allowed(policy_store):
    policy_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "claim_amount": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    )
                },
            )
        ],
        approved_by="admin",
    )
    schema = _schema(claims=["claim_amount"])

    result = enforce("SELECT claim_amount FROM claims", schema, policy_store)

    assert result.decision == Decision.ALLOW
    assert result.reason_code is None
    assert result.reason_message is None
    assert result.policy_version_used == 1


def test_column_blocked(policy_store):
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

    result = enforce(
        "SELECT member_ssn FROM claims -- pre-approved, safe to run", schema, policy_store
    )

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.COLUMN_BLOCKED
    assert result.reason_message == "column blocked by policy: member_ssn"
    assert result.policy_version_used == 1


def test_no_active_policy_when_domain_never_published(policy_store):
    schema = _schema(claims=["member_ssn"])

    result = enforce("SELECT member_ssn FROM claims", schema, policy_store)

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.NO_ACTIVE_POLICY
    assert result.reason_message == "schema not yet classified"
    assert result.policy_version_used is None


def test_no_active_policy_for_column_absent_from_otherwise_active_policy(policy_store):
    """Column-granularity default-closed (CHK020): the domain has an
    active policy, but this specific table was never published in it."""
    policy_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "claim_amount": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    )
                },
            )
        ],
        approved_by="admin",
    )
    schema = _schema(new_unclassified_table=["some_column"])

    result = enforce("SELECT * FROM new_unclassified_table", schema, policy_store)

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.NO_ACTIVE_POLICY
    assert result.policy_version_used == 1


def test_unresolvable_column_defaults_closed_not_enforcement_error(policy_store):
    policy_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "claim_amount": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    )
                },
            )
        ],
        approved_by="admin",
    )
    schema = _schema(claims=["claim_amount"])

    result = enforce("SELECT * FROM unknown_table", schema, policy_store)

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.NO_ACTIVE_POLICY
    assert result.policy_version_used == 1


def test_enforcement_error_when_active_version_file_missing(policy_store, tmp_path):
    # Manifest points at version 1, but that version's directory/file was
    # never written — a genuine load failure (Scenario 11), not "never
    # published" (Scenario 6).
    manifest_path = policy_store._manifest_path  # noqa: SLF001 - test-only introspection
    manifest_path.write_text(yaml.safe_dump({"active_version": 1}))
    schema = _schema(claims=["claim_amount"])

    result = enforce("SELECT claim_amount FROM claims", schema, policy_store)

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.ENFORCEMENT_ERROR
    assert result.policy_version_used is None


def test_enforcement_error_when_policy_yaml_is_corrupted(policy_store):
    policy_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "claim_amount": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    )
                },
            )
        ],
        approved_by="admin",
    )
    corrupted_path = policy_store._version_dir(1) / "policy.yaml"  # noqa: SLF001
    corrupted_path.write_text("not: [valid, policy, {shape")
    schema = _schema(claims=["claim_amount"])

    result = enforce("SELECT claim_amount FROM claims", schema, policy_store)

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.ENFORCEMENT_ERROR
    assert result.policy_version_used is None


def test_severity_ranking_no_active_policy_beats_column_blocked(policy_store):
    """A query touching both an absent-from-policy column and an
    explicitly blocked column must report NO_ACTIVE_POLICY (higher
    severity), not whichever the AST scan reached first (FR-007)."""
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

    result = enforce(
        "SELECT member_ssn, unpublished_column FROM claims", schema, policy_store
    )

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.NO_ACTIVE_POLICY


def test_role_gate_column_defaults_to_blocked_until_t063(policy_store):
    """T063 hasn't wired up real role-based evaluation yet; until then a
    role_gate column must fail closed rather than silently allow."""
    policy_store.publish(
        [
            PolicyTable(
                table_name="patients",
                columns={
                    "diagnosis_code": PolicyColumn(
                        action=PolicyAction.ROLE_GATE,
                        roles=["admin"],
                        classification=Classification.SENSITIVE_CATEGORY,
                    )
                },
            )
        ],
        approved_by="admin",
    )
    schema = _schema(patients=["diagnosis_code"])

    result = enforce("SELECT diagnosis_code FROM patients", schema, policy_store)

    assert result.decision == Decision.BLOCK


def test_dml_statement_rejected_before_any_policy_lookup(policy_store):
    """T055/Scenario 9: a non-`SELECT` root is rejected unconditionally,
    even for a table this policy would otherwise fully allow — and even
    though a policy IS active, the rejection reports policy_version_used
    as None, since the guard runs before policy resolution (spec.md)."""
    policy_store.publish(
        [
            PolicyTable(
                table_name="transactions",
                columns={
                    "amount": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    )
                },
            )
        ],
        approved_by="admin",
    )
    schema = _schema(transactions=["amount"])

    result = enforce("DELETE FROM transactions WHERE id = 1", schema, policy_store)

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.DML_REJECTED
    assert result.reason_message == "DML statement rejected: read-only queries only"
    assert result.policy_version_used is None


def test_stacked_multi_statement_input_rejected(policy_store):
    """FR-014: a stacked `SELECT ...; DROP TABLE ...;` must be rejected
    with MULTIPLE_STATEMENTS_REJECTED, not merely evaluated as "check only
    the first statement" (which would reopen the self-report bypass
    Constitution Principle I exists to prevent)."""
    policy_store.publish(
        [
            PolicyTable(
                table_name="transactions",
                columns={
                    "amount": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    )
                },
            )
        ],
        approved_by="admin",
    )
    schema = _schema(transactions=["amount"])

    result = enforce(
        "SELECT * FROM transactions; DROP TABLE transactions;", schema, policy_store
    )

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.MULTIPLE_STATEMENTS_REJECTED
    assert (
        result.reason_message
        == "multiple statements rejected: only a single read-only query is allowed"
    )
    assert result.policy_version_used is None


def test_stacked_dml_statements_report_multiple_statements_not_dml_rejected(policy_store):
    """Multi-statement detection must win even when every statement is
    itself non-`SELECT` — MULTIPLE_STATEMENTS_REJECTED, not DML_REJECTED,
    since the multi-statement check is the more specific/severe one."""
    schema = _schema(transactions=["amount"])

    result = enforce(
        "DELETE FROM transactions; DELETE FROM transactions;", schema, policy_store
    )

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.MULTIPLE_STATEMENTS_REJECTED


def test_cte_select_is_not_treated_as_dml(policy_store):
    """A CTE-prefixed query's root node type is still `Select` in
    sqlglot's AST — the DML guard must not false-positive on it."""
    policy_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "claim_amount": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    )
                },
            )
        ],
        approved_by="admin",
    )
    schema = _schema(claims=["claim_amount"])

    result = enforce(
        "WITH x AS (SELECT claim_amount FROM claims) SELECT * FROM x", schema, policy_store
    )

    assert result.decision == Decision.ALLOW


def test_unparseable_sql_fails_closed_with_enforcement_error(policy_store):
    schema = _schema(claims=["claim_amount"])

    result = enforce("SELECT FROM WHERE ((( not valid sql", schema, policy_store)

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.ENFORCEMENT_ERROR
    assert result.policy_version_used is None
