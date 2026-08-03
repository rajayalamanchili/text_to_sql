"""BDD step defs for spec.md Scenario 4 (T041).

`claims.member_ssn` is blocked once the fintech policy is published
(pii_direct, near-100% unique, same auto-approval path as Scenario 1's
`patient_ssn`). A query that references it must be rejected before
execution regardless of what the SQL claims about itself — the injected
SQL comment below mimics a prompt-injected/incorrect LLM self-report
(spec.md Scenario 4) and must have zero effect on the enforcement
decision, since the enforcement node's only permitted inputs are the
parsed SQL AST, the active policy artifact, and the Caller object
(Constitution Principle I).

Expected to FAIL until T043-T052 (policy store, publish/query endpoints,
enforcement node) exist (TDD — see tasks.md).
"""

from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/scenario4_block_override.feature")


@given(
    parsers.parse(
        'a fintech schema containing a column "{table_column}" (string, near-100% unique values)'
    )
)
def verify_seed_has_near_unique_column(fintech_db, table_column):
    table, column = table_column.split(".")
    with fintech_db.cursor() as cur:
        cur.execute(f"SELECT count(*), count(DISTINCT {column}) FROM {table}")  # noqa: S608
        total, distinct = cur.fetchone()
    assert total > 0, f"{table} has no seeded rows"
    assert distinct / total >= 0.99, (
        f"{table}.{column} is not near-unique in seed data ({distinct}/{total})"
    )


@given(parsers.parse('the classification pipeline runs for domain "{domain}"'))
def run_classification_pipeline(api_client, domain):
    enumerate_resp = api_client.post(f"/domains/{domain}/schema/enumerate")
    assert enumerate_resp.status_code == 200, enumerate_resp.text
    classify_resp = api_client.post(f"/domains/{domain}/classify")
    assert classify_resp.status_code == 202, classify_resp.text


@given(
    parsers.parse('an approved policy blocking the "{table_column}" column in domain "{domain}"')
)
def publish_policy_and_assert_blocked(api_client, table_column, domain):
    table, column = table_column.split(".")
    publish_resp = api_client.post(
        f"/domains/{domain}/policy/publish", headers={"X-Steward-Role": "admin"}
    )
    assert publish_resp.status_code == 201, publish_resp.text

    policy_resp = api_client.get(f"/domains/{domain}/policy")
    assert policy_resp.status_code == 200, policy_resp.text
    policy = policy_resp.json()
    table_entry = next(t for t in policy["tables"] if t["table_name"] == table)
    assert table_entry["columns"][column]["action"] == "block", table_entry["columns"][column]


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


@then(parsers.parse('the rejection is recorded in the audit log for domain "{domain}"'))
def assert_audit_log_records_block(api_client, domain):
    resp = api_client.get("/audit-log", params={"domain": domain, "decision": "block"})
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert any(item["reason_code"] == "COLUMN_BLOCKED" for item in items), items
