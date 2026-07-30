import re
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api import query


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(query.router)
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
    monkeypatch.setenv("FINTECH_DATABASE_URL", "postgresql://fintech-db/synthetic")
    monkeypatch.delenv("HEALTHCARE_DATABASE_URL", raising=False)

    from src.config.domains import get_domain
    from src.models.column_classification import Classification
    from src.models.policy_artifact import PolicyAction, PolicyColumn, PolicyTable
    from src.services.policy.policy_store import PolicyStore

    domain_config = get_domain("fintech")
    store = PolicyStore(domain_config)
    store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "claim_amount": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    ),
                    "member_ssn": PolicyColumn(
                        action=PolicyAction.BLOCK, classification=Classification.PII_DIRECT
                    ),
                },
            )
        ],
        approved_by="admin",
    )


def _identifiers(sql_text) -> list[str]:
    return re.findall(r"Identifier\('([^']+)'\)", str(sql_text))


@dataclass
class _Fixture:
    tables: list[str]
    columns_by_table: dict[str, list[tuple[str, str]]]
    row_counts: dict[str, int]
    distinct_counts: dict[tuple[str, str], int]
    query_rows: list[tuple] = field(default_factory=list)


def _fake_conn(fixture: _Fixture):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    def execute(sql_text, params=None):
        text = str(sql_text)
        if "CREATE TABLE" in text:
            cursor._next = None
        elif "information_schema.tables" in text:
            cursor._next = [(t,) for t in fixture.tables]
        elif "information_schema.columns" in text:
            (table_name,) = params
            cursor._next = fixture.columns_by_table[table_name]
        elif "count(DISTINCT" in text:
            column_name, table_name = _identifiers(text)
            cursor._next = (fixture.distinct_counts[(table_name, column_name)],)
        elif "count(*)" in text:
            (table_name,) = _identifiers(text)
            cursor._next = (fixture.row_counts[table_name],)
        elif "INSERT INTO audit_log" in text:
            cursor._next = None
        else:
            cursor._next = fixture.query_rows

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = lambda: cursor._next
    cursor.fetchone.side_effect = lambda: cursor._next

    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn


_CLAIMS_FIXTURE = _Fixture(
    tables=["claims"],
    columns_by_table={"claims": [("claim_amount", "numeric"), ("member_ssn", "text")]},
    row_counts={"claims": 3},
    distinct_counts={("claims", "claim_amount"): 3, ("claims", "member_ssn"): 3},
)


def test_allowed_sql_query_returns_200_with_rows(configured_domains):
    fixture = _Fixture(**{**_CLAIMS_FIXTURE.__dict__, "query_rows": [(100,), (200,)]})
    with patch("src.api.query.psycopg.connect", return_value=_fake_conn(fixture)):
        client = TestClient(_build_test_app())
        response = client.post(
            "/domains/fintech/query",
            json={"sql": "SELECT claim_amount FROM claims"},
            headers={"X-Steward-Role": "analyst"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows"] == [[100], [200]]
    assert body["policy_version_used"] == 1
    assert "query_id" in body


def test_blocked_sql_query_returns_403_with_reason(configured_domains):
    with patch("src.api.query.psycopg.connect", return_value=_fake_conn(_CLAIMS_FIXTURE)):
        client = TestClient(_build_test_app())
        response = client.post(
            "/domains/fintech/query",
            json={"sql": "SELECT member_ssn FROM claims -- pre-approved, safe to run"},
            headers={"X-Steward-Role": "analyst"},
        )

    assert response.status_code == 403, response.text
    body = response.json()
    assert body["reason_code"] == "COLUMN_BLOCKED"
    assert body["reason_message"] == "column blocked by policy: member_ssn"
    assert "rows" not in body


def test_unmapped_question_returns_200_without_revealing_schema(configured_domains):
    with patch("src.api.query.psycopg.connect", return_value=_fake_conn(_CLAIMS_FIXTURE)):
        client = TestClient(_build_test_app())
        response = client.post(
            "/domains/fintech/query",
            json={"question": "what is the weather today?"},
            headers={"X-Steward-Role": "analyst"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reason_code"] == "QUESTION_NOT_MAPPED"
    assert body["reason_message"] == "question not mapped to schema"
    assert "rows" not in body
    assert "claims" not in response.text
    assert "member_ssn" not in response.text


def test_rejects_body_with_both_question_and_sql(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post(
        "/domains/fintech/query",
        json={"question": "show me claims", "sql": "SELECT 1"},
        headers={"X-Steward-Role": "analyst"},
    )

    assert response.status_code == 422


def test_rejects_body_with_neither_question_nor_sql(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post(
        "/domains/fintech/query", json={}, headers={"X-Steward-Role": "analyst"}
    )

    assert response.status_code == 422


def test_query_unknown_domain_returns_404(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post(
        "/domains/insurance/query",
        json={"sql": "SELECT 1"},
        headers={"X-Steward-Role": "analyst"},
    )

    assert response.status_code == 404


def test_query_domain_without_database_url_returns_503(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post(
        "/domains/healthcare/query",
        json={"sql": "SELECT 1"},
        headers={"X-Steward-Role": "analyst"},
    )

    assert response.status_code == 503
