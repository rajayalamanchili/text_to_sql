"""Domain configuration loader (FR-011, data-model.md#Domain).

A "domain" is config only: a `domains/<name>/` + `policies/<name>/`
directory pair. Domains are discovered by listing `domains/`'s
subdirectories rather than any hardcoded name list, so adding a third
domain never requires an engine code change (Constitution Principle IV).
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class UnknownDomainError(ValueError):
    """Raised when a requested domain name isn't a configured domain."""

    def __init__(self, name: str, configured: list[str]) -> None:
        super().__init__(f"Unknown domain {name!r}; configured domains: {configured}")
        self.name = name
        self.configured = configured


class DomainConfig(BaseModel):
    """Config-time identity of one domain's directory pair."""

    model_config = {"frozen": True}

    name: str
    domain_dir: Path
    policy_dir: Path
    schema_sql_path: Path
    seed_script_path: Path
    database_url: str | None


def _find_project_root(start: Path) -> Path:
    """Walk upward from `start` for the nearest ancestor containing both
    `domains/` and `policies/` — works whether the backend runs from a
    repo checkout (`backend/src/...`) or the Docker image, where
    `domains/`/`policies/` are mounted as direct children of the working
    directory (docker-compose.yml)."""
    for candidate in (start, *start.parents):
        if (candidate / "domains").is_dir() and (candidate / "policies").is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate a project root (a directory containing both "
        f"'domains/' and 'policies/') above {start}"
    )


def _domains_root() -> Path:
    override = os.environ.get("STEWARD_DOMAINS_DIR")
    if override:
        return Path(override)
    return _find_project_root(Path(__file__).resolve()) / "domains"


def _policies_root() -> Path:
    override = os.environ.get("STEWARD_POLICIES_DIR")
    if override:
        return Path(override)
    return _find_project_root(Path(__file__).resolve()) / "policies"


def _build_domain_config(domain_dir: Path, policies_root: Path) -> DomainConfig:
    name = domain_dir.name
    return DomainConfig(
        name=name,
        domain_dir=domain_dir,
        policy_dir=policies_root / name,
        schema_sql_path=domain_dir / "schema.sql",
        seed_script_path=domain_dir / "seed.py",
        database_url=os.environ.get(f"{name.upper()}_DATABASE_URL"),
    )


def list_domains() -> list[DomainConfig]:
    """All configured domains, discovered from the `domains/` directory
    convention — never a hardcoded domain list (FR-011)."""
    domains_root = _domains_root()
    policies_root = _policies_root()
    return sorted(
        (
            _build_domain_config(child, policies_root)
            for child in domains_root.iterdir()
            if child.is_dir()
        ),
        key=lambda domain: domain.name,
    )


def get_domain(name: str) -> DomainConfig:
    """Look up one configured domain by name.

    Raises `UnknownDomainError` if `name` isn't configured — callers
    (e.g. the `{domain}` path-param dependency) treat that as a fail-closed
    404, per Constitution Principle II applied to domain resolution.
    """
    domains = list_domains()
    for domain in domains:
        if domain.name == name:
            return domain
    raise UnknownDomainError(name, [domain.name for domain in domains])
