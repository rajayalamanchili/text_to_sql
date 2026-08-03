from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api import schema


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(schema.router)
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
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    cursor.fetchall.side_effect = [
        [("patients",)],  # list tables
        [("patient_ssn", "text")],  # list columns for "patients"
    ]
    cursor.fetchone.side_effect = [
        (10,),  # row count
        (10,),  # distinct count
    ]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn


def test_enumerate_returns_tables_and_columns(configured_domains):
    with patch("src.api.schema.psycopg.connect", return_value=_fake_conn()):
        client = TestClient(_build_test_app())
        response = client.post("/domains/healthcare/schema/enumerate")

    assert response.status_code == 200
    assert response.json() == {
        "tables": [
            {
                "table_name": "patients",
                "columns": [
                    {"column_name": "patient_ssn", "data_type": "text", "cardinality_ratio": 1.0}
                ],
            }
        ]
    }


def test_enumerate_response_contains_only_structural_metadata(configured_domains):
    with patch("src.api.schema.psycopg.connect", return_value=_fake_conn()):
        client = TestClient(_build_test_app())
        response = client.post("/domains/healthcare/schema/enumerate")

    table = response.json()["tables"][0]
    column = table["columns"][0]
    assert set(table.keys()) == {"table_name", "columns"}
    assert set(column.keys()) == {"column_name", "data_type", "cardinality_ratio"}


def test_unknown_domain_returns_404(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post("/domains/insurance/schema/enumerate")

    assert response.status_code == 404


def test_domain_without_database_url_returns_503(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post("/domains/fintech/schema/enumerate")

    assert response.status_code == 503
