"""BDD step defs for spec.md Scenario 1 (T015).

Obvious PII column (`patients.patient_ssn`) must be auto-classified
`pii_direct` with confidence >= 0.9, never routed to human review, and
end up `block`-actioned once published — proving the heuristic pass alone
(near-100% unique string + an `ssn` name-pattern match, research.md §1)
clears the 0.85 auto-approval bar without any LLM call.

Expected to FAIL until T018-T027a/T044-T046 exist (TDD — see tasks.md).
"""

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/scenario1_pii_direct.feature")


@given(
    parsers.parse(
        'a healthcare schema containing a column "{table_column}" (string, near-100% unique values)'
    )
)
def verify_seed_has_near_unique_column(healthcare_db, table_column):
    table, column = table_column.split(".")
    with healthcare_db.cursor() as cur:
        cur.execute(f"SELECT count(*), count(DISTINCT {column}) FROM {table}")  # noqa: S608
        total, distinct = cur.fetchone()
    assert total > 0, f"{table} has no seeded rows"
    assert distinct / total >= 0.99, (
        f"{table}.{column} is not near-unique in seed data ({distinct}/{total})"
    )


@when(
    parsers.parse('the classification pipeline runs for domain "{domain}"'),
    target_fixture="classify_result",
)
def run_classification_pipeline(api_client, domain):
    enumerate_resp = api_client.post(f"/domains/{domain}/schema/enumerate")
    assert enumerate_resp.status_code == 200, enumerate_resp.text
    classify_resp = api_client.post(f"/domains/{domain}/classify")
    assert classify_resp.status_code == 202, classify_resp.text
    return classify_resp.json()


@then(
    parsers.parse(
        'the column "{table_column}" is classified "{classification}" '
        "with confidence >= {threshold:g}"
    )
)
def assert_classified_at_or_above(
    api_client, classify_result, table_column, classification, threshold
):
    table, column = table_column.split(".")
    resp = api_client.get(
        "/domains/healthcare/classifications", params={"table": table, "column": column}
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1, f"expected exactly one record for {table_column}, got {items}"
    record = items[0]
    assert record["classification"] == classification, record
    assert record["confidence"] >= threshold, record


@then(parsers.parse('no human review is triggered for "{table_column}" in domain "{domain}"'))
def assert_not_in_review_queue(api_client, table_column, domain):
    resp = api_client.get(f"/domains/{domain}/review-queue")
    assert resp.status_code == 200, resp.text
    pending = {f"{item['table_name']}.{item['column_name']}" for item in resp.json()["items"]}
    assert table_column not in pending, f"{table_column} unexpectedly pending review: {pending}"


@then(
    parsers.parse('the published policy for domain "{domain}" sets "{action}" for "{table_column}"')
)
def assert_published_policy_action(api_client, domain, action, table_column):
    table, column = table_column.split(".")
    publish_resp = api_client.post(
        f"/domains/{domain}/policy/publish", headers={"X-Steward-Role": "admin"}
    )
    assert publish_resp.status_code == 201, publish_resp.text

    policy_resp = api_client.get(f"/domains/{domain}/policy")
    assert policy_resp.status_code == 200, policy_resp.text
    policy = policy_resp.json()
    table_entry = next(t for t in policy["tables"] if t["table_name"] == table)
    assert table_entry["columns"][column]["action"] == action, table_entry["columns"][column]
