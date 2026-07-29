from unittest.mock import MagicMock

from src.services.enumeration.schema_enumerator import enumerate_schema


def _fake_conn(*, tables, columns_by_table, row_counts, distinct_counts):
    """A fake psycopg connection whose single cursor mock replays
    canned `fetchall`/`fetchone` results in call order, so the test
    verifies the enumerator's query *sequence* and *result shaping*
    without a real Postgres instance."""
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    fetchall_results = [[(t,) for t in tables]] + [columns_by_table[t] for t in tables]
    fetchone_results = []
    for t in tables:
        if not columns_by_table[t]:
            continue
        fetchone_results.append((row_counts[t],))
        for column_name, _ in columns_by_table[t]:
            fetchone_results.append((distinct_counts[(t, column_name)],))

    cursor.fetchall.side_effect = fetchall_results
    cursor.fetchone.side_effect = fetchone_results

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def test_enumerate_schema_computes_cardinality_ratio_from_counts():
    conn, cursor = _fake_conn(
        tables=["patients"],
        columns_by_table={"patients": [("patient_ssn", "text"), ("gender", "text")]},
        row_counts={"patients": 100},
        distinct_counts={("patients", "patient_ssn"): 99, ("patients", "gender"): 2},
    )

    snapshot = enumerate_schema("healthcare", conn)

    assert snapshot.domain == "healthcare"
    assert [t.table_name for t in snapshot.tables] == ["patients"]
    columns = {c.column_name: c for c in snapshot.tables[0].columns}
    assert columns["patient_ssn"].data_type == "text"
    assert columns["patient_ssn"].cardinality_ratio == 0.99
    assert columns["gender"].cardinality_ratio == 0.02


def test_enumerate_schema_handles_empty_table_without_division_by_zero():
    conn, _ = _fake_conn(
        tables=["claims"],
        columns_by_table={"claims": [("claim_amount", "numeric")]},
        row_counts={"claims": 0},
        distinct_counts={("claims", "claim_amount"): 0},
    )

    snapshot = enumerate_schema("fintech", conn)

    assert snapshot.tables[0].columns[0].cardinality_ratio == 0.0


def test_enumerate_schema_never_selects_raw_column_values():
    conn, cursor = _fake_conn(
        tables=["accounts"],
        columns_by_table={"accounts": [("balance", "numeric")]},
        row_counts={"accounts": 10},
        distinct_counts={("accounts", "balance"): 5},
    )

    enumerate_schema("fintech", conn)

    executed_queries = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
    assert "information_schema" in executed_queries
    assert "count(*)" in executed_queries or "count(DISTINCT" in executed_queries
    assert "SELECT balance" not in executed_queries
    assert "SELECT *" not in executed_queries


def test_enumerate_schema_multiple_tables_no_columns_edge_case():
    conn, _ = _fake_conn(
        tables=["empty_table", "patients"],
        columns_by_table={"empty_table": [], "patients": [("gender", "text")]},
        row_counts={"patients": 4},
        distinct_counts={("patients", "gender"): 2},
    )

    snapshot = enumerate_schema("healthcare", conn)

    assert [t.table_name for t in snapshot.tables] == ["empty_table", "patients"]
    assert snapshot.tables[0].columns == []
