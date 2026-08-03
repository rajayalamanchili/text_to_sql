from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api import classify


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(classify.router)
    return app


@pytest.fixture
def configured_domains(tmp_path, monkeypatch):
    domains_root = tmp_path / "domains"
    policies_root = tmp_path / "policies"
    for name in ("healthcare", "fintech"):
        (domains_root / name).mkdir(parents=True)
        (policies_root / name).mkdir(parents=True)
    monkeypatch.setenv("STEWARD_DOMAINS_DIR", str(domains_root))
    monkeypatch.setenv("STEWARD_POLICIES_DIR", str(policies_root))
    monkeypatch.setenv("HEALTHCARE_DATABASE_URL", "postgresql://healthcare-db/synthetic")
    monkeypatch.delenv("FINTECH_DATABASE_URL", raising=False)


def _fake_conn():
    """One table (`patients`) with a high-confidence column
    (`patient_ssn`, auto-approved by the heuristic pass alone, no LLM
    needed) and a low-confidence one (`notes`, routed through
    `NullLLMClient`, stays `pending_review`)."""
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    def execute(query, params=None):
        text = str(query)
        if "CREATE TABLE" in text:
            cursor._next = None
        elif "information_schema.tables" in text:
            cursor._next = [("patients",)]
        elif "information_schema.columns" in text:
            cursor._next = [("patient_ssn", "text"), ("notes", "text")]
        elif "count(DISTINCT" in text and "patient_ssn" in text:
            cursor._next = (10,)
        elif "count(DISTINCT" in text and "notes" in text:
            cursor._next = (2,)
        elif "count(*)" in text:
            cursor._next = (10,)
        elif "LIMIT" in text:
            cursor._next = [("short note",), ("short note",), ("another",)]
        elif "INSERT INTO column_classifications" in text or "INSERT INTO audit_log" in text:
            cursor._next = None
        else:
            raise AssertionError(f"unexpected query: {text}")

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = lambda: cursor._next
    cursor.fetchone.side_effect = lambda: cursor._next

    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn


def test_classify_returns_summary_counts(configured_domains):
    with patch("src.api.classify.psycopg.connect", return_value=_fake_conn()):
        client = TestClient(_build_test_app())
        response = client.post("/domains/healthcare/classify")

    assert response.status_code == 202
    body = response.json()
    assert body["columns_classified"] == 2
    assert body["auto_approved_count"] == 1
    assert body["pending_review_count"] == 1
    assert "run_id" in body


def test_unknown_domain_returns_404(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post("/domains/insurance/classify")

    assert response.status_code == 404


def test_domain_without_database_url_returns_503(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post("/domains/fintech/classify")

    assert response.status_code == 503


def _fake_conn_with_rows(rows):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    def execute(query, params=None):
        text = str(query)
        if "CREATE TABLE" in text:
            cursor._next = None
        elif "SELECT id, domain, table_name" in text:
            cursor._next = rows
        else:
            raise AssertionError(f"unexpected query: {text}")

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = lambda: cursor._next

    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn


def _classification_row(**overrides):
    row = {
        "id": uuid4(),
        "domain": "healthcare",
        "table_name": "patients",
        "column_name": "patient_ssn",
        "data_type": "text",
        "cardinality_ratio": 0.99,
        "classification": "pii_direct",
        "heuristic_score": 0.95,
        "llm_score": None,
        "confidence": 0.95,
        "source": "heuristic",
        "status": "auto_approved",
        "reviewed_by": None,
        "reviewed_at": None,
        "llm_rationale": None,
    }
    row.update(overrides)
    return tuple(row.values())


def test_list_classifications_returns_items(configured_domains):
    rows = [_classification_row()]
    with patch("src.api.classify.psycopg.connect", return_value=_fake_conn_with_rows(rows)):
        client = TestClient(_build_test_app())
        response = client.get("/domains/healthcare/classifications")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["table_name"] == "patients"
    assert items[0]["column_name"] == "patient_ssn"
    assert items[0]["classification"] == "pii_direct"
    assert items[0]["status"] == "auto_approved"


def test_list_classifications_empty_when_none_persisted(configured_domains):
    with patch("src.api.classify.psycopg.connect", return_value=_fake_conn_with_rows([])):
        client = TestClient(_build_test_app())
        response = client.get("/domains/healthcare/classifications")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_list_classifications_unknown_domain_returns_404(configured_domains):
    client = TestClient(_build_test_app())

    response = client.get("/domains/insurance/classifications")

    assert response.status_code == 404


def test_list_classifications_passes_table_and_column_filters(configured_domains):
    fake_conn = _fake_conn_with_rows([])
    with patch("src.api.classify.psycopg.connect", return_value=fake_conn):
        client = TestClient(_build_test_app())
        response = client.get(
            "/domains/healthcare/classifications",
            params={"table": "patients", "column": "patient_ssn"},
        )

    assert response.status_code == 200
    cursor = fake_conn.cursor.return_value
    (_query, params), _kwargs = cursor.execute.call_args
    assert params["table_name"] == "patients"
    assert params["column_name"] == "patient_ssn"
