"""BDD step defs for spec.md Scenario 6 (T042).

A table that was never enumerated/classified for a domain is absent from
that domain's active policy artifact by definition. FR-009 requires this
to default closed — rejected with `reason_code: NO_ACTIVE_POLICY`
(message: "schema not yet classified") — even though the domain otherwise
has an active, published policy for its known tables (CHK020: default-
closed applies at table/column granularity, not only when a domain has
never been classified at all).

Expected to FAIL until T043-T052 (policy store, publish/query endpoints,
enforcement node) exist (TDD — see tasks.md).
"""

from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/scenario6_default_closed.feature")


@given(parsers.parse('the classification pipeline runs for domain "{domain}"'))
def run_classification_pipeline(api_client, domain):
    enumerate_resp = api_client.post(f"/domains/{domain}/schema/enumerate")
    assert enumerate_resp.status_code == 200, enumerate_resp.text
    classify_resp = api_client.post(f"/domains/{domain}/classify")
    assert classify_resp.status_code == 202, classify_resp.text


@given(parsers.parse('the policy for domain "{domain}" is published'))
def publish_policy(api_client, domain):
    publish_resp = api_client.post(
        f"/domains/{domain}/policy/publish", headers={"X-Steward-Role": "admin"}
    )
    assert publish_resp.status_code == 201, publish_resp.text


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


@then(parsers.parse('no rows from domain "{domain}" are returned in the response'))
def assert_no_rows_returned(query_response, domain):
    del domain  # part of the sentence; the rejection body itself carries no data
    body = query_response.json()
    assert "rows" not in body, body
