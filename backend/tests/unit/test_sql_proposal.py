import pytest
from src.services.enumeration.schema_enumerator import (
    ColumnSchema,
    DomainSchemaSnapshot,
    TableSchema,
)
from src.services.generation.sql_proposal import QuestionNotMappedError, propose_sql


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


def test_raw_sql_passthrough_bypasses_mapping():
    schema = _schema(claims=["member_ssn"])

    proposal = propose_sql(schema, sql="SELECT member_ssn FROM claims")

    assert proposal.sql == "SELECT member_ssn FROM claims"


def test_raw_sql_passthrough_ignores_schema_entirely():
    """Even a totally empty schema must not block raw `sql` input — no
    mapping check applies to it (Scenario 4's flow)."""
    schema = _schema()

    proposal = propose_sql(schema, sql="SELECT member_ssn FROM claims")

    assert proposal.sql == "SELECT member_ssn FROM claims"


def test_question_matching_table_name_builds_select_star():
    schema = _schema(claims=["member_ssn", "claim_amount"])

    proposal = propose_sql(schema, question="show me all claims")

    assert proposal.sql == "SELECT * FROM claims"


def test_question_matching_column_name_projects_only_that_column():
    schema = _schema(claims=["member_ssn", "claim_amount"])

    proposal = propose_sql(schema, question="what is the claim_amount for claims")

    assert proposal.sql == "SELECT claim_amount FROM claims"


def test_question_matching_only_a_column_name_finds_its_table():
    schema = _schema(patients=["patient_id", "patient_ssn"])

    proposal = propose_sql(schema, question="what is the patient_ssn")

    assert proposal.sql == "SELECT patient_ssn FROM patients"


def test_irrelevant_question_raises_question_not_mapped():
    schema = _schema(claims=["member_ssn"])

    with pytest.raises(QuestionNotMappedError):
        propose_sql(schema, question="what is the weather today?")


def test_requires_exactly_one_of_question_or_sql():
    schema = _schema(claims=["member_ssn"])

    with pytest.raises(ValueError):
        propose_sql(schema)
