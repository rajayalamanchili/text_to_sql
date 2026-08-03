import pytest
import sqlglot
from src.services.enforcement.column_resolver import (
    ColumnResolutionError,
    ResolvedColumn,
    resolve_columns,
)
from src.services.enumeration.schema_enumerator import (
    ColumnSchema,
    DomainSchemaSnapshot,
    TableSchema,
)


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


def _parse(sql: str):
    return sqlglot.parse_one(sql, read="postgres")


def test_resolves_simple_select():
    schema = _schema(claims=["member_ssn", "claim_amount"])
    resolved = resolve_columns(_parse("SELECT member_ssn FROM claims"), schema)
    assert resolved == [ResolvedColumn(table="claims", column="member_ssn")]


def test_expands_select_star():
    schema = _schema(claims=["member_ssn", "claim_amount"])
    resolved = resolve_columns(_parse("SELECT * FROM claims"), schema)
    assert set(resolved) == {
        ResolvedColumn(table="claims", column="member_ssn"),
        ResolvedColumn(table="claims", column="claim_amount"),
    }


def test_expands_qualified_table_star():
    schema = _schema(claims=["member_ssn"], customers=["customer_id"])
    resolved = resolve_columns(
        _parse("SELECT c.*, cu.customer_id FROM claims c JOIN customers cu ON true"), schema
    )
    assert ResolvedColumn(table="claims", column="member_ssn") in resolved
    assert ResolvedColumn(table="customers", column="customer_id") in resolved
    assert all(rc.table in {"claims", "customers"} for rc in resolved)


def test_resolves_join_with_aliases():
    """Aliased table references (`p`, `e`) must resolve back to their real
    table names — including columns only referenced in the JOIN
    condition, not just the SELECT list, since policy must cover those
    too."""
    schema = _schema(
        patients=["patient_id", "patient_ssn"], encounters=["encounter_id", "patient_id"]
    )
    resolved = resolve_columns(
        _parse(
            "SELECT p.patient_ssn FROM patients p JOIN encounters e ON p.patient_id = e.patient_id"
        ),
        schema,
    )
    assert set(resolved) == {
        ResolvedColumn(table="patients", column="patient_ssn"),
        ResolvedColumn(table="patients", column="patient_id"),
        ResolvedColumn(table="encounters", column="patient_id"),
    }


def test_resolves_cte_to_underlying_table():
    schema = _schema(patients=["patient_id", "patient_ssn"])
    resolved = resolve_columns(
        _parse("WITH x AS (SELECT patient_ssn FROM patients) SELECT * FROM x"), schema
    )
    # Only the real base table/column appears — the CTE alias itself is not
    # a policy-covered entity.
    assert resolved == [ResolvedColumn(table="patients", column="patient_ssn")]


def test_resolves_subquery_to_underlying_table():
    schema = _schema(patients=["patient_id", "patient_ssn"])
    resolved = resolve_columns(
        _parse("SELECT * FROM (SELECT patient_ssn FROM patients) sub"), schema
    )
    assert resolved == [ResolvedColumn(table="patients", column="patient_ssn")]


def test_resolves_correlated_subquery_in_where_clause():
    schema = _schema(
        patients=["patient_id", "patient_ssn"], encounters=["encounter_id", "patient_id"]
    )
    resolved = resolve_columns(
        _parse(
            "SELECT patient_ssn FROM patients WHERE patient_id IN "
            "(SELECT patient_id FROM encounters)"
        ),
        schema,
    )
    assert set(resolved) == {
        ResolvedColumn(table="patients", column="patient_ssn"),
        ResolvedColumn(table="patients", column="patient_id"),
        ResolvedColumn(table="encounters", column="patient_id"),
    }


def test_count_star_is_not_treated_as_unresolved_wildcard():
    schema = _schema(claims=["member_ssn"])
    resolved = resolve_columns(_parse("SELECT COUNT(*) FROM claims"), schema)
    assert resolved == []


def test_unknown_table_with_star_raises():
    schema = _schema(claims=["member_ssn"])
    with pytest.raises(ColumnResolutionError):
        resolve_columns(_parse("SELECT * FROM new_unclassified_table"), schema)


def test_unknown_table_referenced_only_via_join_raises():
    """An unrecognized table joined in (even if none of its columns are
    directly selected) must still fail closed — not silently pass through
    just because no column happened to be pulled from it."""
    schema = _schema(claims=["member_ssn"])
    with pytest.raises(ColumnResolutionError):
        resolve_columns(
            _parse(
                "SELECT claims.member_ssn FROM claims "
                "JOIN unknown_table u ON claims.member_ssn = u.id"
            ),
            schema,
        )


def test_unknown_column_raises():
    schema = _schema(claims=["member_ssn"])
    with pytest.raises(ColumnResolutionError):
        resolve_columns(_parse("SELECT nonexistent_column FROM claims"), schema)


def test_non_ascii_identifiers_resolve_when_known():
    schema = _schema(**{"médecins": ["nom_complet"]})
    resolved = resolve_columns(_parse('SELECT nom_complet FROM "médecins"'), schema)
    assert resolved == [ResolvedColumn(table="médecins", column="nom_complet")]


def test_non_ascii_unknown_table_fails_closed():
    schema = _schema(claims=["member_ssn"])
    with pytest.raises(ColumnResolutionError):
        resolve_columns(_parse('SELECT * FROM "médecins"'), schema)
