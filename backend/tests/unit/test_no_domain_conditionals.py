"""Cross-domain regression check (FR-011, Success Criteria): the engine
codebase must run both healthcare and fintech with zero domain-specific
code paths. Domain names may appear in `domains/`, `policies/`, and
tests/fixtures — never in `backend/src` itself, which is what this test
enforces so a stray `if domain == "healthcare"` regresses CI immediately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_SRC = REPO_ROOT / "backend" / "src"
DOMAINS_DIR = REPO_ROOT / "domains"


def _configured_domain_names() -> list[str]:
    return sorted(child.name for child in DOMAINS_DIR.iterdir() if child.is_dir())


def _engine_source_files() -> list[Path]:
    return sorted(ENGINE_SRC.rglob("*.py"))


def test_at_least_two_domains_are_configured():
    # Guards against the substring checks below vacuously passing if the
    # `domains/` directory is ever emptied out.
    domains = _configured_domain_names()
    assert set(domains) >= {"fintech", "healthcare"}


@pytest.mark.parametrize(
    "source_file", _engine_source_files(), ids=lambda p: str(p.relative_to(ENGINE_SRC))
)
def test_engine_source_file_has_no_domain_name_literal(source_file):
    text = source_file.read_text().lower()
    found = [name for name in _configured_domain_names() if name.lower() in text]
    assert not found, (
        f"{source_file.relative_to(REPO_ROOT)} references configured domain "
        f"name(s) {found} — domain identity must stay in domains/policies "
        f"config, not engine source (FR-011, Constitution Principle IV)"
    )
