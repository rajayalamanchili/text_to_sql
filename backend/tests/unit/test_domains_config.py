import pytest
from src.config.domains import UnknownDomainError, get_domain, list_domains


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
    return domains_root, policies_root


def test_list_domains_discovers_directory_pairs(configured_domains):
    domains_root, policies_root = configured_domains

    domains = list_domains()

    assert [domain.name for domain in domains] == ["fintech", "healthcare"]
    healthcare = next(d for d in domains if d.name == "healthcare")
    assert healthcare.domain_dir == domains_root / "healthcare"
    assert healthcare.policy_dir == policies_root / "healthcare"
    assert healthcare.schema_sql_path == domains_root / "healthcare" / "schema.sql"
    assert healthcare.seed_script_path == domains_root / "healthcare" / "seed.py"


def test_database_url_resolved_from_env_per_domain(configured_domains):
    healthcare = get_domain("healthcare")
    fintech = get_domain("fintech")

    assert healthcare.database_url == "postgresql://healthcare-db/synthetic"
    assert fintech.database_url is None


def test_unknown_domain_raises(configured_domains):
    with pytest.raises(UnknownDomainError) as exc_info:
        get_domain("insurance")

    assert exc_info.value.name == "insurance"
    assert set(exc_info.value.configured) == {"healthcare", "fintech"}


def test_new_domain_directory_requires_no_code_change(configured_domains):
    domains_root, policies_root = configured_domains
    (domains_root / "retail").mkdir()
    (policies_root / "retail").mkdir()

    retail = get_domain("retail")

    assert retail.name == "retail"
