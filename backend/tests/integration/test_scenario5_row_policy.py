"""BDD step defs for spec.md Scenario 5 (T058).

A table's `row_policy_template` must be injected into every executed
query deterministically — AND-merged at the AST level with whatever
`WHERE` clause the submitted SQL already contains, never overwriting or
stripping it (spec.md Clarifications, Session 2026-07-23) — and the
query must never be able to return rows outside the caller's tenant, even
though the SQL submitted below never mentions tenant scoping itself. If
`X-Steward-Tenant` is absent or malformed for a table whose policy
requires it, the query must be rejected fail-closed with
`reason_code: ENFORCEMENT_ERROR` (spec.md Clarifications, Session
2026-07-27), not treated as an implicit pass.

`claims.tenant_id`/`claims.claim_id`/`claims.claim_status` are forced to
an approved `business` classification (rather than relying on whatever
the heuristic/LLM pipeline happens to produce for them) so this scenario
exercises row-policy enforcement specifically, independent of
classification-confidence nondeterminism — the same approach
`test_scenario8_admin_approval.py` uses for the review-queue/approve
path. `row_policy_template` is a manual, post-publish override applied
directly to the published YAML (tasks.md T061), mirroring
`test_scenario11_enforcement_error.py`'s direct-file-edit pattern; the
original file content is restored via `request.addfinalizer` so a failed
run never leaves the repo's real policy file altered for subsequent runs.

Expected to FAIL until T059-T061 (row-predicate injector, its wiring into
the enforcement node, and the fintech `tenant_id` row-policy) exist
(TDD — see tasks.md).
"""

from __future__ import annotations

import yaml
from pytest_bdd import given, parsers, scenarios, then, when
from src.config.domains import get_domain

scenarios("features/scenario5_row_policy.feature")


@given(parsers.parse('the classification pipeline runs for domain "{domain}"'))
def run_classification_pipeline(api_client, domain):
    enumerate_resp = api_client.post(f"/domains/{domain}/schema/enumerate")
    assert enumerate_resp.status_code == 200, enumerate_resp.text
    classify_resp = api_client.post(f"/domains/{domain}/classify")
    assert classify_resp.status_code == 202, classify_resp.text


@given(parsers.parse('the column "{table_column}" is approved as "business" in domain "{domain}"'))
def ensure_column_approved_business(api_client, table_column, domain):
    table, column = table_column.split(".")
    resp = api_client.get(
        f"/domains/{domain}/classifications", params={"table": table, "column": column}
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items, f"no classification record found for {table_column}"
    record = items[0]

    if record["status"] == "pending_review":
        reclassify_resp = api_client.post(
            f"/domains/{domain}/review-queue/{record['id']}/reclassify",
            json={"classification": "business"},
            headers={"X-Steward-Role": "admin"},
        )
        assert reclassify_resp.status_code == 200, reclassify_resp.text
        record = reclassify_resp.json()

    assert record["classification"] == "business", (
        f"{table_column} is already {record['status']!r} as "
        f"{record['classification']!r}; Scenario 5 needs it publish-allowed "
        "as 'business' to isolate row-policy enforcement from column-block "
        "enforcement"
    )


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


@given(parsers.parse('the "{table}" table has a row policy "{predicate}" in domain "{domain}"'))
def add_row_policy_template(request, domain, table, predicate, published_version):
    domain_config = get_domain(domain)
    policy_path = domain_config.policy_dir / str(published_version) / "policy.yaml"
    original_content = policy_path.read_text()
    request.addfinalizer(lambda: policy_path.write_text(original_content))

    raw = yaml.safe_load(original_content)
    table_entry = next(t for t in raw["tables"] if t["table_name"] == table)
    table_entry["row_policy_template"] = predicate
    policy_path.write_text(yaml.safe_dump(raw, sort_keys=False))


@given(
    parsers.parse(
        'domain "{domain}" has "{status}" claims for tenant "{tenant_id}" '
        "and at least one other tenant"
    ),
    target_fixture="total_matching_claims",
)
def verify_multi_tenant_claims(fintech_db, domain, status, tenant_id):
    del domain  # sentence context only; fintech_db is already domain-specific
    with fintech_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM claims WHERE claim_status = %s", (status,))
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM claims WHERE claim_status = %s AND tenant_id = %s",
            (status, tenant_id),
        )
        tenant_count = cur.fetchone()[0]
        cur.execute(
            "SELECT count(DISTINCT tenant_id) FROM claims WHERE claim_status = %s", (status,)
        )
        distinct_tenants = cur.fetchone()[0]
    assert tenant_count > 0, f"tenant {tenant_id!r} has no {status!r} claims in seed data"
    assert distinct_tenants > 1, (
        f"only one tenant has {status!r} claims in seed data; Scenario 5 needs "
        "cross-tenant data to prove row-policy scoping actually narrows results"
    )
    return total


@when(
    parsers.parse(
        'a caller with tenant "{tenant_id}" submits the SQL query "{sql}" to domain "{domain}"'
    ),
    target_fixture="query_response",
)
def caller_with_tenant_submits_sql(api_client, tenant_id, sql, domain):
    return api_client.post(
        f"/domains/{domain}/query",
        json={"sql": sql},
        headers={"X-Steward-Role": "analyst", "X-Steward-Tenant": tenant_id},
    )


@when(
    parsers.parse(
        'a caller with no tenant header submits the SQL query "{sql}" to domain "{domain}"'
    ),
    target_fixture="query_response",
)
def caller_without_tenant_submits_sql(api_client, sql, domain):
    return api_client.post(
        f"/domains/{domain}/query",
        json={"sql": sql},
        headers={"X-Steward-Role": "analyst"},
    )


@then(parsers.parse("the query succeeds with status {status:d}"))
def assert_success(query_response, status):
    assert query_response.status_code == status, query_response.text


@then(
    parsers.parse('every returned row belongs to tenant "{tenant_id}" with claim_status "{status}"')
)
def assert_rows_scoped_to_tenant(query_response, tenant_id, status):
    rows = query_response.json()["rows"]
    assert rows, "expected at least one row (tenant_id, claim_id, claim_status)"
    for row in rows:
        assert row[0] == tenant_id, row
        assert row[2] == status, row


@then("fewer rows are returned than the total number of matching claims across all tenants")
def assert_fewer_rows_than_total(query_response, total_matching_claims):
    rows = query_response.json()["rows"]
    assert len(rows) < total_matching_claims, (len(rows), total_matching_claims)


@then(parsers.parse("the query is rejected before execution with status {status:d}"))
def assert_rejected(query_response, status):
    assert query_response.status_code == status, query_response.text


@then(parsers.parse('the rejection reason code is "{reason_code}" with message "{reason_message}"'))
def assert_reason_code_and_message(query_response, reason_code, reason_message):
    body = query_response.json()
    assert body["reason_code"] == reason_code, body
    assert body["reason_message"] == reason_message, body
