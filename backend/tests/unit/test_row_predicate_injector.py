import pytest
import sqlglot
from src.api.deps import Caller
from src.models.policy_artifact import PolicyTable
from src.services.audit.audit_log import ActorRole
from src.services.enforcement.row_predicate_injector import (
    TenantResolutionError,
    inject_row_policies,
)


def _parse(sql: str):
    return sqlglot.parse_one(sql, read="postgres")


def _caller(tenant_id: str | None) -> Caller:
    return Caller(role=ActorRole.ANALYST, tenant_id=tenant_id)


def _governed(table_name: str = "claims", template: str = "tenant_id = :current_tenant"):
    return [PolicyTable(table_name=table_name, row_policy_template=template)]


def test_no_governed_tables_returns_statement_untouched():
    statement = _parse("SELECT claim_id FROM claims")
    result = inject_row_policies(statement, [PolicyTable(table_name="claims")], _caller(None))
    assert result.sql(dialect="postgres") == statement.sql(dialect="postgres")


def test_governed_table_not_referenced_is_untouched():
    statement = _parse("SELECT customer_id FROM customers")
    result = inject_row_policies(statement, _governed(), _caller(None))
    assert result.sql(dialect="postgres") == statement.sql(dialect="postgres")
    assert result.args.get("where") is None


def test_injects_predicate_when_no_existing_where():
    statement = _parse("SELECT claim_id FROM claims")
    result = inject_row_policies(statement, _governed(), _caller("tenant-001"))
    assert (
        result.sql(dialect="postgres")
        == "SELECT claim_id FROM claims WHERE claims.tenant_id = 'tenant-001'"
    )


def test_and_merges_with_existing_where():
    statement = _parse("SELECT claim_id FROM claims WHERE claim_status = 'approved'")
    result = inject_row_policies(statement, _governed(), _caller("tenant-001"))
    assert result.sql(dialect="postgres") == (
        "SELECT claim_id FROM claims WHERE claim_status = 'approved' "
        "AND claims.tenant_id = 'tenant-001'"
    )


def test_wraps_existing_or_condition_to_preserve_precedence():
    """AND-ing onto a bare `a OR b` without parenthesizing `a OR b` first
    would silently change semantics (`a OR (b AND policy)` instead of
    `(a OR b) AND policy`) — the exact bug spec.md's Scenario 5
    clarification calls out."""
    statement = _parse(
        "SELECT claim_id FROM claims WHERE claim_status = 'approved' OR claim_status = 'paid'"
    )
    result = inject_row_policies(statement, _governed(), _caller("tenant-001"))
    assert result.sql(dialect="postgres") == (
        "SELECT claim_id FROM claims WHERE (claim_status = 'approved' OR claim_status = 'paid') "
        "AND claims.tenant_id = 'tenant-001'"
    )


def test_original_statement_is_not_mutated():
    statement = _parse("SELECT claim_id FROM claims")
    original_sql = statement.sql(dialect="postgres")
    inject_row_policies(statement, _governed(), _caller("tenant-001"))
    assert statement.sql(dialect="postgres") == original_sql
    assert statement.args.get("where") is None


def test_qualifies_predicate_with_table_alias():
    statement = _parse("SELECT c.claim_id FROM claims c")
    result = inject_row_policies(statement, _governed(), _caller("tenant-001"))
    assert result.sql(dialect="postgres") == (
        "SELECT c.claim_id FROM claims AS c WHERE c.tenant_id = 'tenant-001'"
    )


def test_injects_into_each_self_join_occurrence_separately():
    statement = _parse(
        "SELECT a.claim_id FROM claims a JOIN claims b ON a.customer_id = b.customer_id"
    )
    result = inject_row_policies(statement, _governed(), _caller("tenant-001"))
    sql = result.sql(dialect="postgres")
    assert "a.tenant_id = 'tenant-001'" in sql
    assert "b.tenant_id = 'tenant-001'" in sql
    assert sql.count("tenant_id = 'tenant-001'") == 2


def test_injects_inside_cte_body_not_at_outer_reference():
    statement = _parse("WITH recent AS (SELECT claim_id FROM claims) SELECT claim_id FROM recent")
    result = inject_row_policies(statement, _governed(), _caller("tenant-001"))
    sql = result.sql(dialect="postgres")
    assert "claims.tenant_id = 'tenant-001'" in sql
    # The outer SELECT (over the CTE alias `recent`, not a real table) must
    # not itself gain a `recent.tenant_id` predicate.
    assert "recent.tenant_id" not in sql


def test_untouched_table_in_policy_list_has_no_row_policy():
    statement = _parse("SELECT customer_id FROM customers")
    result = inject_row_policies(
        statement, [PolicyTable(table_name="customers", row_policy_template=None)], _caller(None)
    )
    assert result.args.get("where") is None


def test_missing_tenant_raises_when_governed_table_referenced():
    statement = _parse("SELECT claim_id FROM claims")
    with pytest.raises(TenantResolutionError):
        inject_row_policies(statement, _governed(), _caller(None))


def test_blank_tenant_raises_when_governed_table_referenced():
    statement = _parse("SELECT claim_id FROM claims")
    with pytest.raises(TenantResolutionError):
        inject_row_policies(statement, _governed(), _caller("   "))


def test_missing_tenant_is_fine_if_governed_table_not_touched():
    statement = _parse("SELECT customer_id FROM customers")
    result = inject_row_policies(statement, _governed(), _caller(None))
    assert result.args.get("where") is None


def test_query_graph_can_execute_resulting_sql_text():
    """The injector's output must round-trip through `.sql()` into
    directly executable text — this is what the enforcement node (T060)
    will hand to `execute_node` in place of the caller-submitted SQL."""
    statement = _parse("SELECT claim_id FROM claims WHERE claim_status = 'approved'")
    result = inject_row_policies(statement, _governed(), _caller("tenant-001"))
    reparsed = sqlglot.parse_one(result.sql(dialect="postgres"), read="postgres")
    assert reparsed.sql(dialect="postgres") == result.sql(dialect="postgres")
