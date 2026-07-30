"""BDD step defs for spec.md Scenario 9 (T053).

A non-`SELECT` statement (DML) must be rejected unconditionally, before
any column/table policy check, regardless of what the active policy
would otherwise allow — and this applies identically to a single-
statement DML query and to a stacked multi-statement input (the latter
logged with `MULTIPLE_STATEMENTS_REJECTED` instead of `DML_REJECTED`),
per FR-014's amendment covering the stacked-statement case.

T055 (the DML/multi-statement guard in `enforcer.py`) now exists, so this
is no longer TDD-blocked — verified with a mocked-Postgres smoke test
against the real `/query` endpoint (both cases return the exact reason
codes/messages below) before updating this note.
"""

from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/scenario9_dml_rejected.feature")


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


@then(
    parsers.parse(
        'the rejection reason code is "{reason_code}" with message "{reason_message}"'
    )
)
def assert_reason_code_and_message(query_response, reason_code, reason_message):
    body = query_response.json()
    assert body["reason_code"] == reason_code, body
    assert body["reason_message"] == reason_message, body
