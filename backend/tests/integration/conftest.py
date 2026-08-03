"""Shared fixtures for the pytest-bdd behavioral scenario suite.

These tests exercise the real API against a real per-domain Postgres
instance (tech-stack.md: no mocking the enforcement/classification path,
Constitution Principle I) — they are skipped, not failed, when no
reachable database is configured, since that's an environment gap, not a
test failure. Point `HEALTHCARE_DATABASE_URL`/`FINTECH_DATABASE_URL` at a
running instance (e.g. `docker compose up -d`, see quickstart.md) to run
them for real.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from src.api.main import app

REPO_ROOT = Path(__file__).resolve().parents[3]


def _seed_script(domain: str) -> Path:
    return REPO_ROOT / "domains" / domain / "seed.py"


def _ensure_domain_db(domain: str) -> str:
    """Skip the test if `{DOMAIN}_DATABASE_URL` is unset/unreachable,
    otherwise ensure the domain's schema + synthetic data are seeded
    (idempotent — reuses domains/<domain>/seed.py directly, see T012/T013)
    and return the connection URL."""
    env_var = f"{domain.upper()}_DATABASE_URL"
    url = os.environ.get(env_var)
    if not url:
        pytest.skip(f"{env_var} not set — start docker compose to run integration tests")
    try:
        with psycopg.connect(url, connect_timeout=3):
            pass
    except psycopg.OperationalError as exc:
        pytest.skip(f"cannot reach {domain} database ({env_var}={url}): {exc}")

    subprocess.run(
        [sys.executable, str(_seed_script(domain)), "--database-url", url],
        check=True,
        capture_output=True,
        text=True,
    )
    return url


@pytest.fixture(scope="session")
def healthcare_db_url() -> str:
    return _ensure_domain_db("healthcare")


@pytest.fixture(scope="session")
def fintech_db_url() -> str:
    return _ensure_domain_db("fintech")


@pytest.fixture
def healthcare_db(healthcare_db_url):
    with psycopg.connect(healthcare_db_url) as conn:
        yield conn


@pytest.fixture
def fintech_db(fintech_db_url):
    with psycopg.connect(fintech_db_url) as conn:
        yield conn


@pytest.fixture
def api_client(healthcare_db_url, fintech_db_url):
    """A TestClient against the real FastAPI app. Depends on both domain DB
    fixtures so any scenario that hits `/domains/{domain}/...` can rely on
    that domain's database already being reachable and seeded."""
    with TestClient(app) as client:
        yield client
