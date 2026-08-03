from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from src.api import policy
from src.api.deps import AdminRoleRequiredError


def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(AdminRoleRequiredError)
    async def handle_admin_role_required(request: Request, exc: AdminRoleRequiredError):
        del request
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    app.include_router(policy.router)
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
    return policies_root


def _classification_row(**overrides):
    row = {
        "id": uuid4(),
        "domain": "fintech",
        "table_name": "claims",
        "column_name": "member_ssn",
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


def _fake_conn(rows):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False

    def execute(query, params=None):
        text = str(query)
        if "CREATE TABLE" in text:
            cursor._next = None
        elif "SELECT id, domain, table_name" in text:
            cursor._next = rows
        elif "INSERT INTO audit_log" in text:
            cursor._next = None
        else:
            raise AssertionError(f"unexpected query: {text}")

    cursor.execute.side_effect = execute
    cursor.fetchall.side_effect = lambda: cursor._next

    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn


def test_publish_builds_artifact_from_approved_classifications_only(configured_domains):
    rows = [
        _classification_row(
            column_name="member_ssn", classification="pii_direct", status="auto_approved"
        ),
        _classification_row(
            column_name="claim_amount", classification="business", status="auto_approved"
        ),
        _classification_row(
            column_name="notes", classification="sensitive_category", status="pending_review"
        ),
    ]
    with patch("src.api.policy.psycopg.connect", return_value=_fake_conn(rows)):
        client = TestClient(_build_test_app())
        response = client.post(
            "/domains/fintech/policy/publish", headers={"X-Steward-Role": "admin"}
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"] == 1
    assert body["approved_by"] == "admin"
    table = next(t for t in body["tables"] if t["table_name"] == "claims")
    assert table["columns"]["member_ssn"]["action"] == "block"
    assert table["columns"]["claim_amount"]["action"] == "allow"
    assert "notes" not in table["columns"], "pending_review column must not be published"


def test_publish_writes_versioned_yaml_and_manifest(configured_domains):
    rows = [_classification_row()]
    with patch("src.api.policy.psycopg.connect", return_value=_fake_conn(rows)):
        client = TestClient(_build_test_app())
        client.post("/domains/fintech/policy/publish", headers={"X-Steward-Role": "admin"})

    policy_dir = configured_domains / "fintech"
    manifest = yaml.safe_load((policy_dir / "manifest.yaml").read_text())
    assert manifest["active_version"] == 1
    artifact_yaml = yaml.safe_load((policy_dir / "1" / "policy.yaml").read_text())
    assert artifact_yaml["domain"] == "fintech"
    assert artifact_yaml["tables"][0]["columns"]["member_ssn"]["action"] == "block"


def test_analyst_cannot_publish_policy(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post("/domains/fintech/policy/publish", headers={"X-Steward-Role": "analyst"})

    assert response.status_code == 403
    assert response.json() == {"error": "admin role required"}


def test_publish_unknown_domain_returns_404(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post("/domains/insurance/policy/publish", headers={"X-Steward-Role": "admin"})

    assert response.status_code == 404


def test_publish_domain_without_database_url_returns_503(configured_domains):
    client = TestClient(_build_test_app())

    response = client.post(
        "/domains/healthcare/policy/publish", headers={"X-Steward-Role": "admin"}
    )

    assert response.status_code == 503


def test_get_policy_returns_404_when_never_published(configured_domains):
    client = TestClient(_build_test_app())

    response = client.get("/domains/fintech/policy")

    assert response.status_code == 404


def test_get_policy_returns_active_artifact_after_publish(configured_domains):
    rows = [_classification_row()]
    with patch("src.api.policy.psycopg.connect", return_value=_fake_conn(rows)):
        client = TestClient(_build_test_app())
        client.post("/domains/fintech/policy/publish", headers={"X-Steward-Role": "admin"})

        response = client.get("/domains/fintech/policy")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == 1
    assert body["tables"][0]["columns"]["member_ssn"]["action"] == "block"


def test_get_policy_unknown_domain_returns_404(configured_domains):
    client = TestClient(_build_test_app())

    response = client.get("/domains/insurance/policy")

    assert response.status_code == 404
