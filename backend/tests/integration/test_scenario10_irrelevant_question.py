"""BDD step defs for spec.md Scenario 10 (T054).

A question that maps to none of the domain's known table/column names
must never execute SQL, never reveal which tables/columns exist, and
must be surfaced as a `200` with `reason_code: QUESTION_NOT_MAPPED`
(contracts/api.md's non-rejection, HTTP-200 case) — distinct from every
other enforcement outcome's `403`.

This is NOT expected to fail: `POST /query` (T051) renders exactly this
contract. Since T056, the query graph also writes its own `AuditLogEntry`
for this outcome (`Decision.QUESTION_NOT_MAPPED`, satisfying FR-010's
audit-completeness rule) — not asserted on here, since `GET /audit-log`
(T057) doesn't exist yet to query it back through the API; see
`test_query_graph.py`'s unit-level coverage for that part.
"""

from __future__ import annotations

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/scenario10_irrelevant_question.feature")

# Real table/column names in the healthcare schema (domains/healthcare/schema.sql)
# that must never appear in an unmapped-question response.
_HEALTHCARE_SCHEMA_IDENTIFIERS = [
    "patients",
    "patient_ssn",
    "patient_notes",
    "diagnosis_code",
    "encounters",
    "conditions",
    "condition_code",
]


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
    parsers.parse('an analyst asks the question "{question}" of domain "{domain}"'),
    target_fixture="query_response",
)
def analyst_asks_question(api_client, question, domain):
    return api_client.post(
        f"/domains/{domain}/query",
        json={"question": question},
        headers={"X-Steward-Role": "analyst"},
    )


@then(parsers.parse('the question is not executed as SQL against domain "{domain}"'))
def assert_no_sql_executed(query_response, domain):
    del domain  # part of the sentence; verified via the response shape below
    assert query_response.status_code == 200, query_response.text
    assert "rows" not in query_response.json(), query_response.text


@then(
    parsers.parse(
        'the response indicates reason code "{reason_code}" with message "{reason_message}"'
    )
)
def assert_reason_code_and_message(query_response, reason_code, reason_message):
    body = query_response.json()
    assert body["reason_code"] == reason_code, body
    assert body["reason_message"] == reason_message, body


@then(parsers.parse('the response does not reveal any table or column name from domain "{domain}"'))
def assert_no_schema_leak(query_response, domain):
    del domain
    response_text = query_response.text
    for identifier in _HEALTHCARE_SCHEMA_IDENTIFIERS:
        assert identifier not in response_text, (
            f"{identifier!r} leaked into unmapped-question response: {response_text}"
        )
