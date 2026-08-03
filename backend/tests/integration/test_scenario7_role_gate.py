"""BDD step defs for spec.md Scenario 7 (T062).

A `role_gate` column must be rejected with `reason_code:
ROLE_GATE_MISMATCH` for a caller whose role isn't in the column's
`roles` list — `on_role_mismatch: reject`, the default (FR-008) — and
must succeed for a caller whose role is listed.

`patients.diagnosis_code` is role-gated by editing the freshly published
YAML directly, mirroring `test_scenario5_row_policy.py`'s approach for
`row_policy_template`: `role_gate` (like `row_policy_template`) is never
auto-derived from a column's classification at publish time
(`src/api/policy.py`) — it's only ever a manual, post-publish override
(tasks.md T064). The original file content is restored via
`request.addfinalizer` so a failed run never leaves the repo's real
policy file altered for subsequent runs.

Expected to FAIL until T063 (the `role_gate` enforcement branch) exists
(TDD — see tasks.md); until then, a `role_gate` column defaults closed
under `NO_ACTIVE_POLICY`, not `ROLE_GATE_MISMATCH` (`enforcer.py`).
"""

from __future__ import annotations

import yaml
from pytest_bdd import given, parsers, scenarios, then, when
from src.config.domains import get_domain

scenarios("features/scenario7_role_gate.feature")


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


@given(parsers.parse('the "{table_column}" column is role-gated to "{role}" in domain "{domain}"'))
def add_role_gate(request, domain, table_column, role, published_version):
    table, column = table_column.split(".")
    domain_config = get_domain(domain)
    policy_path = domain_config.policy_dir / str(published_version) / "policy.yaml"
    original_content = policy_path.read_text()
    request.addfinalizer(lambda: policy_path.write_text(original_content))

    raw = yaml.safe_load(original_content)
    table_entry = next((t for t in raw["tables"] if t["table_name"] == table), None)
    if table_entry is None:
        table_entry = {"table_name": table, "columns": {}, "row_policy_template": None}
        raw["tables"].append(table_entry)

    table_entry["columns"][column] = {
        "action": "role_gate",
        "roles": [role],
        "on_role_mismatch": "reject",
        "classification": "sensitive_category",
    }
    policy_path.write_text(yaml.safe_dump(raw, sort_keys=False))


@when(
    parsers.parse('a caller with role "{role}" submits the SQL query "{sql}" to domain "{domain}"'),
    target_fixture="query_response",
)
def caller_with_role_submits_sql(api_client, role, sql, domain):
    return api_client.post(
        f"/domains/{domain}/query",
        json={"sql": sql},
        headers={"X-Steward-Role": role},
    )


@then(parsers.parse("the query is rejected before execution with status {status:d}"))
def assert_rejected(query_response, status):
    assert query_response.status_code == status, query_response.text


@then(parsers.parse('the rejection reason code is "{reason_code}" with message "{reason_message}"'))
def assert_reason_code_and_message(query_response, reason_code, reason_message):
    body = query_response.json()
    assert body["reason_code"] == reason_code, body
    assert body["reason_message"] == reason_message, body


@then(parsers.parse("the query succeeds with status {status:d}"))
def assert_success(query_response, status):
    assert query_response.status_code == status, query_response.text
