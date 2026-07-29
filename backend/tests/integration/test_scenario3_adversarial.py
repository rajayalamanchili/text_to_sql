"""BDD step defs for spec.md Scenario 3 (T017).

`patients.patient_notes` is free-text clinical narrative whose column name
matches no heuristic dictionary term (research.md §1) — the adversarial
free-text default (research.md §2) must cap it at confidence <= 0.6 and
default it to `sensitive_category`, NEVER silently auto-classify it
`business`. This is the fail-closed guarantee at the heuristic layer
itself (Constitution Principle II), independent of whatever the LLM pass
later proposes.

Expected to FAIL until T018-T027a exist (TDD — see tasks.md).
"""

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/scenario3_adversarial.feature")


@given(
    parsers.parse(
        'a healthcare schema containing a column "{table_column}" '
        "that contains free-text clinical narrative"
    )
)
def verify_seed_has_free_text_narrative(healthcare_db, table_column):
    table, column = table_column.split(".")
    with healthcare_db.cursor() as cur:
        cur.execute(f"SELECT count(*), count(DISTINCT {column}) FROM {table}")  # noqa: S608
        total, distinct = cur.fetchone()
    assert total > 0, f"{table} has no seeded rows"
    # High-entropy narrative, unlike Scenario 2's low-cardinality memo field.
    assert distinct / total > 0.9, (
        f"{table}.{column} does not look like free-text narrative in seed data ({distinct}/{total})"
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


def _lookup_classification(api_client, domain, table, column):
    resp = api_client.get(
        f"/domains/{domain}/classifications", params={"table": table, "column": column}
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1, f"expected exactly one record for {table}.{column}, got {items}"
    return items[0]


@then(
    parsers.parse(
        'the column "{table_column}" is NOT auto-classified "{classification}" with high confidence'
    )
)
def assert_not_auto_classified(api_client, classify_result, table_column, classification):
    table, column = table_column.split(".")
    record = _lookup_classification(api_client, "healthcare", table, column)
    is_unsafe_auto_approval = (
        record["classification"] == classification and record["status"] == "auto_approved"
    )
    assert not is_unsafe_auto_approval, record


@then(
    parsers.parse(
        '"{table_column}" is either classified "{classification}" or routed to human review'
    )
)
def assert_sensitive_or_pending_review(api_client, table_column, classification):
    table, column = table_column.split(".")
    record = _lookup_classification(api_client, "healthcare", table, column)
    is_sensitive_or_pending = (
        record["classification"] == classification or record["status"] == "pending_review"
    )
    assert is_sensitive_or_pending, record
