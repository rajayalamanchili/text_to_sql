"""Synthetic-data safeguard test (FR-012, Constitution Principle VII):
`domains/healthcare/seed.py` and `domains/fintech/seed.py` must only ever
construct data via the checked-in Faker/Synthea-style generators, and
must only ever resolve their target database from this project's own
`{DOMAIN}_DATABASE_URL` convention (`backend/src/config/domains.py`) or
an explicit local `--database-url` override — never a hardcoded,
remote, or otherwise externally-supplied connection string.

Two layers, both required: a static source check (import allowlist + no
hardcoded URL-scheme literal, so a future edit can't quietly add a
network call or an embedded connection string) and a behavioral check of
`database_url()` itself (so the resolution logic, not just its absence of
suspicious literals, is verified).
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Only what these scripts legitimately need: stdlib for CLI/data-shaping,
# psycopg for the local Postgres connection, faker for synthetic data.
# Nothing here can open a network connection to anything other than the
# database resolved via `{DOMAIN}_DATABASE_URL` (checked separately below).
_ALLOWED_TOP_LEVEL_IMPORTS = {
    "__future__",
    "argparse",
    "os",
    "random",
    "dataclasses",
    "datetime",
    "pathlib",
    "psycopg",
    "faker",
}

# Any of these appearing as a literal in the source would mean a
# connection target (or other network endpoint) baked into the file
# itself, rather than resolved from the domain's env var at run time.
_URL_SCHEME_PATTERN = re.compile(
    r"(https?|ftp|s3|gs|postgres(?:ql)?|mysql|mongodb)://", re.IGNORECASE
)

_DOMAINS = ["healthcare", "fintech"]


def _seed_path(domain: str) -> Path:
    return REPO_ROOT / "domains" / domain / "seed.py"


def _load_seed_module(domain: str) -> ModuleType:
    path = _seed_path(domain)
    module_name = f"_seed_{domain}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    # Registered in sys.modules before exec: the seed scripts use
    # `@dataclass`, whose annotation resolution looks the module up via
    # `sys.modules[cls.__module__]` and fails on an unregistered module.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _imported_top_level_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("domain", _DOMAINS)
def test_seed_script_only_imports_the_allowed_local_toolchain(domain):
    source = _seed_path(domain).read_text()
    tree = ast.parse(source)

    imports = _imported_top_level_names(tree)

    disallowed = imports - _ALLOWED_TOP_LEVEL_IMPORTS
    assert not disallowed, (
        f"domains/{domain}/seed.py imports {disallowed}, outside the allowed "
        f"local generator/DB toolchain {_ALLOWED_TOP_LEVEL_IMPORTS} — a network "
        f"or external-data-source dependency would let real/remote data in"
    )


@pytest.mark.parametrize("domain", _DOMAINS)
def test_seed_script_has_no_hardcoded_url_or_connection_string(domain):
    source = _seed_path(domain).read_text()

    match = _URL_SCHEME_PATTERN.search(source)
    assert match is None, (
        f"domains/{domain}/seed.py contains a hardcoded URL-scheme literal "
        f"{match.group(0) if match else ''!r} — the database target must only "
        f"ever come from {domain.upper()}_DATABASE_URL or --database-url"
    )


@pytest.mark.parametrize("domain", _DOMAINS)
def test_database_url_override_takes_precedence_over_env(domain, monkeypatch):
    module = _load_seed_module(domain)
    monkeypatch.setenv(f"{domain.upper()}_DATABASE_URL", "postgresql://env-value/db")

    assert module.database_url("postgresql://cli-override/db") == "postgresql://cli-override/db"


@pytest.mark.parametrize("domain", _DOMAINS)
def test_database_url_falls_back_to_the_domain_scoped_env_var(domain, monkeypatch):
    module = _load_seed_module(domain)
    env_var = f"{domain.upper()}_DATABASE_URL"
    monkeypatch.setenv(env_var, "postgresql://localhost:5432/synthetic")

    assert module.database_url(None) == "postgresql://localhost:5432/synthetic"


@pytest.mark.parametrize("domain", _DOMAINS)
def test_database_url_raises_rather_than_silently_default_when_unset(domain, monkeypatch):
    """Fail closed (Constitution Principle II applied here too): no
    override and no env var must never fall back to some other default
    connection string — it must error instead of guessing a target."""
    module = _load_seed_module(domain)
    monkeypatch.delenv(f"{domain.upper()}_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError):
        module.database_url(None)


@pytest.mark.parametrize("domain", _DOMAINS)
def test_database_url_ignores_unscoped_or_other_domains_env_vars(domain, monkeypatch):
    """The resolution must be scoped to exactly this domain's own
    `{DOMAIN}_DATABASE_URL` — never a generic `DATABASE_URL` or another
    domain's variable, which would make it possible for an unrelated,
    externally-supplied connection string to be picked up by accident."""
    module = _load_seed_module(domain)
    monkeypatch.delenv(f"{domain.upper()}_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unscoped-generic/db")
    other_domain = next(d for d in _DOMAINS if d != domain)
    monkeypatch.setenv(f"{other_domain.upper()}_DATABASE_URL", "postgresql://other-domain/db")

    with pytest.raises(RuntimeError):
        module.database_url(None)
