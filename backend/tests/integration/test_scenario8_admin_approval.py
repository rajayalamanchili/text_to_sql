"""BDD step defs for spec.md Scenario 8 (T031).

Only an admin-role caller may approve a pending_review classification;
an analyst-role attempt must be rejected with the record left unchanged,
and a successful admin approval must be recorded in the audit log with
the approving admin's identity (FR-013, data-model.md State Transitions).

Expected to FAIL until T032-T036 (review-queue + approve endpoints) and
T057 (GET /audit-log) exist (TDD — see tasks.md).
"""

from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/scenario8_admin_approval.feature")


@given(
    parsers.parse(
        'a fintech schema containing a column "{table_column}" '
        "(free text, low cardinality of distinct patterns)"
    )
)
def verify_seed_has_low_cardinality_column(fintech_db, table_column):
    table, column = table_column.split(".")
    with fintech_db.cursor() as cur:
        cur.execute(f"SELECT count(*), count(DISTINCT {column}) FROM {table}")  # noqa: S608
        total, distinct = cur.fetchone()
    assert total > 0, f"{table} has no seeded rows"
    assert distinct / total < 0.1, (
        f"{table}.{column} is not low-cardinality in seed data ({distinct}/{total})"
    )


@given(parsers.parse('the classification pipeline runs for domain "{domain}"'))
def run_classification_pipeline(api_client, domain):
    enumerate_resp = api_client.post(f"/domains/{domain}/schema/enumerate")
    assert enumerate_resp.status_code == 200, enumerate_resp.text
    classify_resp = api_client.post(f"/domains/{domain}/classify")
    assert classify_resp.status_code == 202, classify_resp.text


@given(
    parsers.parse('the column "{table_column}" is in the review queue for domain "{domain}"'),
    target_fixture="column_id",
)
def assert_in_review_queue_and_capture_id(api_client, table_column, domain):
    table, column = table_column.split(".")
    resp = api_client.get(f"/domains/{domain}/review-queue")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    record = next(
        item for item in items if item["table_name"] == table and item["column_name"] == column
    )
    assert record["status"] == "pending_review", record
    return record["id"]


@when(
    parsers.parse('an analyst attempts to approve "{table_column}" in domain "{domain}"'),
    target_fixture="analyst_approve_response",
)
def analyst_attempts_approve(api_client, column_id, table_column, domain):
    del table_column  # part of the sentence, resolved via column_id from the prior step
    return api_client.post(
        f"/domains/{domain}/review-queue/{column_id}/approve",
        headers={"X-Steward-Role": "analyst"},
    )


@then(parsers.parse("the approval is rejected with status {status:d}"))
def assert_rejected(analyst_approve_response, status):
    assert analyst_approve_response.status_code == status, analyst_approve_response.text


@then(parsers.parse('the column "{table_column}" remains "{status}" in domain "{domain}"'))
def assert_column_remains_status(api_client, table_column, status, domain):
    table, column = table_column.split(".")
    resp = api_client.get(
        f"/domains/{domain}/classifications", params={"table": table, "column": column}
    )
    assert resp.status_code == 200, resp.text
    record = resp.json()["items"][0]
    assert record["status"] == status, record


@when(
    parsers.parse('an admin approves "{table_column}" in domain "{domain}"'),
    target_fixture="admin_approve_response",
)
def admin_approves(api_client, column_id, table_column, domain):
    del table_column  # part of the sentence, resolved via column_id from the review-queue step
    return api_client.post(
        f"/domains/{domain}/review-queue/{column_id}/approve",
        headers={"X-Steward-Role": "admin"},
    )


@then("the approval succeeds")
def assert_approval_succeeds(admin_approve_response):
    assert admin_approve_response.status_code == 200, admin_approve_response.text


@then(parsers.parse('the column "{table_column}" is "{status}" in domain "{domain}"'))
def assert_column_is_status(api_client, table_column, status, domain):
    table, column = table_column.split(".")
    resp = api_client.get(
        f"/domains/{domain}/classifications", params={"table": table, "column": column}
    )
    assert resp.status_code == 200, resp.text
    record = resp.json()["items"][0]
    assert record["status"] == status, record
    assert record["reviewed_by"] is not None, record
    assert record["reviewed_at"] is not None, record


@then(
    parsers.parse(
        "the audit log records the admin's identity for the approval in domain \"{domain}\""
    )
)
def assert_audit_log_records_admin(api_client, domain):
    resp = api_client.get(
        "/audit-log", params={"domain": domain, "decision": "classify_approved"}
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert any(item["actor_role"] == "admin" for item in items), items
