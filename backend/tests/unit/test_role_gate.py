import sqlglot
from src.services.enforcement.role_gate import find_excludable_projection
from src.services.enumeration.schema_enumerator import (
    ColumnSchema,
    DomainSchemaSnapshot,
    TableSchema,
)


def _schema(**tables: list[str]) -> DomainSchemaSnapshot:
    return DomainSchemaSnapshot(
        domain="healthcare",
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


def test_finds_bare_column_in_flat_select_list():
    schema = _schema(patients=["patient_id", "diagnosis_code"])
    statement = _parse("SELECT patient_id, diagnosis_code FROM patients")

    projection = find_excludable_projection(statement, "patients", "diagnosis_code", schema)

    assert projection is not None
    assert projection is statement.expressions[1]


def test_finds_aliased_table_reference():
    schema = _schema(patients=["diagnosis_code"])
    statement = _parse("SELECT p.diagnosis_code FROM patients p")

    projection = find_excludable_projection(statement, "patients", "diagnosis_code", schema)

    assert projection is statement.expressions[0]


def test_finds_column_projection_with_its_own_alias():
    schema = _schema(patients=["diagnosis_code"])
    statement = _parse("SELECT diagnosis_code AS dc FROM patients")

    projection = find_excludable_projection(statement, "patients", "diagnosis_code", schema)

    assert projection is statement.expressions[0]


def test_returns_none_when_wrapped_in_aggregate():
    schema = _schema(patients=["diagnosis_code"])
    statement = _parse("SELECT COUNT(diagnosis_code) FROM patients")

    assert find_excludable_projection(statement, "patients", "diagnosis_code", schema) is None


def test_returns_none_when_only_referenced_in_where_clause():
    schema = _schema(patients=["patient_id", "diagnosis_code"])
    statement = _parse("SELECT patient_id FROM patients WHERE diagnosis_code = 'X'")

    assert find_excludable_projection(statement, "patients", "diagnosis_code", schema) is None


def test_returns_none_on_select_star():
    schema = _schema(patients=["patient_id", "diagnosis_code"])
    statement = _parse("SELECT * FROM patients")

    assert find_excludable_projection(statement, "patients", "diagnosis_code", schema) is None


def test_returns_none_on_qualified_table_star():
    schema = _schema(patients=["patient_id", "diagnosis_code"], encounters=["encounter_id"])
    statement = _parse("SELECT p.*, e.encounter_id FROM patients p JOIN encounters e ON true")

    assert find_excludable_projection(statement, "patients", "diagnosis_code", schema) is None


def test_returns_none_when_column_not_referenced_at_all():
    schema = _schema(patients=["patient_id", "diagnosis_code"])
    statement = _parse("SELECT patient_id FROM patients")

    assert find_excludable_projection(statement, "patients", "diagnosis_code", schema) is None


def test_returns_none_when_looking_for_a_table_the_query_never_references():
    schema = _schema(patients=["patient_id"])
    statement = _parse("SELECT patient_id FROM patients")

    assert find_excludable_projection(statement, "unknown_table", "diagnosis_code", schema) is None


def test_does_not_match_same_column_name_on_a_different_table():
    schema = _schema(patients=["diagnosis_code"], conditions=["diagnosis_code"])
    statement = _parse("SELECT diagnosis_code FROM patients")

    assert find_excludable_projection(statement, "conditions", "diagnosis_code", schema) is None
