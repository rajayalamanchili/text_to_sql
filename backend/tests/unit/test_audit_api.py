import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api import audit


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(audit.router)
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
    monkeypatch.setenv("FINTECH_DATABASE_URL", "postgresql://fintech-db/synthetic")


def _row(*, domain, decision="block", timestamp=None):
    return (
        uuid.uuid4(),
        timestamp or datetime.now(UTC),
        domain,
        uuid.uuid4(),
        "analyst",
        decision,
        "COLUMN_BLOCKED" if decision == "block" else None,
        "column blocked by policy: member_ssn" if decision == "block" else None,
        1,
        "hash",
    )


def _fake_conn(rows):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    def execute(sql_text, params=None):
        text = str(sql_text)
        if "CREATE TABLE" in text:
            cursor._next = None
        else:
            cursor._next = rows

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = lambda: cursor._next

    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn


def test_domain_filter_only_queries_that_domain(configured_domains):
    healthcare_rows = [_row(domain="healthcare")]

    with patch(
        "src.api.audit.psycopg.connect", return_value=_fake_conn(healthcare_rows)
    ) as mock_connect:
        client = TestClient(_build_test_app())
        response = client.get("/audit-log", params={"domain": "healthcare"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["domain"] == "healthcare"
    mock_connect.assert_called_once_with("postgresql://healthcare-db/synthetic")


def test_omitted_domain_queries_and_merges_all_domains(configured_domains):
    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = datetime(2026, 6, 1, tzinfo=UTC)

    def connect(url):
        if "healthcare" in url:
            return _fake_conn([_row(domain="healthcare", timestamp=older)])
        return _fake_conn([_row(domain="fintech", timestamp=newer)])

    with patch("src.api.audit.psycopg.connect", side_effect=connect):
        client = TestClient(_build_test_app())
        response = client.get("/audit-log")

    assert response.status_code == 200, response.text
    body = response.json()
    domains = {item["domain"] for item in body["items"]}
    assert domains == {"healthcare", "fintech"}
    # Merged results sorted newest-first across domains.
    assert body["items"][0]["domain"] == "fintech"
    assert body["items"][1]["domain"] == "healthcare"


def test_decision_filter_is_forwarded_to_the_query(configured_domains):
    rows = [_row(domain="healthcare", decision="allow")]
    captured = {}

    def connect(url):
        conn = _fake_conn(rows)
        captured["conn"] = conn
        return conn

    with patch("src.api.audit.psycopg.connect", side_effect=connect):
        client = TestClient(_build_test_app())
        response = client.get(
            "/audit-log", params={"domain": "healthcare", "decision": "allow"}
        )

    assert response.status_code == 200, response.text
    cursor = captured["conn"].cursor()
    _, params = cursor.execute.call_args.args
    assert params["decision"] == "allow"


def test_unknown_domain_returns_404(configured_domains):
    client = TestClient(_build_test_app())

    response = client.get("/audit-log", params={"domain": "insurance"})

    assert response.status_code == 404


def test_domain_without_database_url_returns_empty_items(tmp_path, monkeypatch):
    domains_root = tmp_path / "domains"
    policies_root = tmp_path / "policies"
    (domains_root / "healthcare").mkdir(parents=True)
    (policies_root / "healthcare").mkdir(parents=True)
    monkeypatch.setenv("STEWARD_DOMAINS_DIR", str(domains_root))
    monkeypatch.setenv("STEWARD_POLICIES_DIR", str(policies_root))
    monkeypatch.delenv("HEALTHCARE_DATABASE_URL", raising=False)

    client = TestClient(_build_test_app())
    response = client.get("/audit-log", params={"domain": "healthcare"})

    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}
