"""BDD step defs for spec.md Scenario 11 (T057a).

An active policy artifact that has become unreadable (corrupted YAML,
per this scenario) must fail the whole query closed with
`ENFORCEMENT_ERROR` — never behave like an implicit pass, even though no
column/table-level policy was actually violated.

This test corrupts the just-published policy version's file directly on
disk — this suite runs against the real, shared `policies/<domain>/`
directory, not a temp copy (see conftest.py) — and restores its original
content via `request.addfinalizer`, which pytest guarantees runs during
teardown even if an assertion fails, so a failed run never leaves the
repo's real policy file corrupted for subsequent runs.
"""

from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when
from src.config.domains import get_domain

scenarios("features/scenario11_enforcement_error.feature")


@given(parsers.parse('the classification pipeline runs for domain "{domain}"'))
def run_classification_pipeline(api_client, domain):
    enumerate_resp = api_client.post(f"/domains/{domain}/schema/enumerate")
    assert enumerate_resp.status_code == 200, enumerate_resp.text
    classify_resp = api_client.post(f"/domains/{domain}/classify")
    assert classify_resp.status_code == 202, classify_resp.text


@given(
    parsers.parse('the policy for domain "{domain}" is published'),
    target_fixture="published_version",
)
def publish_policy(api_client, domain):
    publish_resp = api_client.post(
        f"/domains/{domain}/policy/publish", headers={"X-Steward-Role": "admin"}
    )
    assert publish_resp.status_code == 201, publish_resp.text
    return publish_resp.json()["version"]


@given(parsers.parse('the active policy file for domain "{domain}" becomes corrupted'))
def corrupt_active_policy_file(request, domain, published_version):
    domain_config = get_domain(domain)
    policy_path = domain_config.policy_dir / str(published_version) / "policy.yaml"
    original_content = policy_path.read_text()
    request.addfinalizer(lambda: policy_path.write_text(original_content))

    policy_path.write_text("not: [valid, policy, {shape")


@when(
    parsers.parse('an analyst submits the SQL query "{sql}" to domain "{domain}"'),
    target_fixture="query_response",
)
def analyst_submits_sql(api_client, sql, domain):
    return api_client.post(
        f"/domains/{domain}/query",
        json={"sql": sql},
        headers={"X-Steward-Role": "analyst"},
    )


@then(parsers.parse("the query is rejected before execution with status {status:d}"))
def assert_rejected(query_response, status):
    assert query_response.status_code == status, query_response.text


@then(parsers.parse('the rejection reason code is "{reason_code}" with message "{reason_message}"'))
def assert_reason_code_and_message(query_response, reason_code, reason_message):
    body = query_response.json()
    assert body["reason_code"] == reason_code, body
    assert body["reason_message"] == reason_message, body
