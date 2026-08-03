"""BDD step defs for spec.md Scenario 2 (T016).

An ambiguous column (`transactions.notes`: free text, low cardinality of
distinct patterns — research.md §1's dictionary won't confidently match
it, but it isn't high-entropy narrative either) must land below the 0.85
auto-approval threshold and sit in `pending_review` with no active policy
until an admin acts on it (FR-005, FR-013).

Expected to FAIL until T018-T027a/T032 exist (TDD — see tasks.md).
"""

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/scenario2_review_queue.feature")


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
        'the column "{table_column}" receives a classification with confidence < {threshold:g}'
    )
)
def assert_classified_below(api_client, classify_result, table_column, threshold):
    table, column = table_column.split(".")
    resp = api_client.get(
        "/domains/fintech/classifications", params={"table": table, "column": column}
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1, f"expected exactly one record for {table_column}, got {items}"
    assert items[0]["confidence"] < threshold, items[0]


@then(
    parsers.parse(
        'the column "{table_column}" is added to the human-review queue for domain "{domain}"'
    )
)
def assert_in_review_queue(api_client, table_column, domain):
    resp = api_client.get(f"/domains/{domain}/review-queue")
    assert resp.status_code == 200, resp.text
    pending = {f"{item['table_name']}.{item['column_name']}" for item in resp.json()["items"]}
    assert table_column in pending, f"{table_column} missing from review queue: {pending}"


@then(parsers.parse('a reviewer sees "{table_column}" in the review UI with status "{status}"'))
def assert_review_queue_status(api_client, table_column, status):
    table, column = table_column.split(".")
    resp = api_client.get("/domains/fintech/review-queue")
    assert resp.status_code == 200, resp.text
    record = next(
        item
        for item in resp.json()["items"]
        if item["table_name"] == table and item["column_name"] == column
    )
    assert record["status"] == status, record


@then(
    parsers.parse(
        'the policy status for "{table_column}" is "{pending_status}", not "{allowed_status}", '
        "until an admin approves it"
    )
)
def assert_no_active_policy_yet(api_client, table_column, pending_status, allowed_status):
    table, column = table_column.split(".")
    resp = api_client.get(
        "/domains/fintech/classifications", params={"table": table, "column": column}
    )
    assert resp.status_code == 200, resp.text
    record = resp.json()["items"][0]
    assert record["status"] == pending_status, record
    assert record["status"] != allowed_status, record
