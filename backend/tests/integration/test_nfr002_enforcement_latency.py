"""NFR-002 timing test: policy enforcement checks add no more than 200ms
of latency, measured as p95 over a single-query, no-concurrent-load
benchmark run (spec.md NFR-002).

Unlike NFR-001's classifier timing (T068), nothing here is stubbed for
speed — NFR-002 is explicitly scoped to *deterministic* checks only, no
LLM calls are permitted in the enforcement path (Constitution Principle
I), so `enforce()` itself never does anything non-deterministic or
network-bound. The `PolicyStore` is backed by real files under `tmp_path`
(same fixture pattern as `tests/unit/test_enforcer.py`) rather than
faked, so the benchmark includes real disk reads of the policy YAML on
every call, matching production (`PolicyStore` has no cache).

The benchmarked query exercises the full ALLOW path — column resolution,
policy lookup, and row-policy predicate injection — rather than the
cheapest possible early-exit, since that's the representative "did this
query clear enforcement" case NFR-002 is meant to bound.
"""

from __future__ import annotations

import statistics
import time

from src.api.deps import Caller
from src.config.domains import DomainConfig
from src.models.column_classification import Classification
from src.models.policy_artifact import PolicyAction, PolicyColumn, PolicyTable
from src.services.audit.audit_log import ActorRole, Decision
from src.services.enforcement.enforcer import enforce
from src.services.enumeration.schema_enumerator import (
    ColumnSchema,
    DomainSchemaSnapshot,
    TableSchema,
)
from src.services.policy.policy_store import PolicyStore

NUM_ITERATIONS = 200
P95_BUDGET_SECONDS = 0.2  # NFR-002

QUERY = "SELECT claim_id, claim_amount FROM claims WHERE claim_amount > 100"


def _schema() -> DomainSchemaSnapshot:
    return DomainSchemaSnapshot(
        domain="fintech",
        tables=[
            TableSchema(
                table_name="claims",
                columns=[
                    ColumnSchema(column_name=name, data_type="text", cardinality_ratio=0.5)
                    for name in (
                        "claim_id",
                        "claim_amount",
                        "member_ssn",
                        "diagnosis_code",
                        "tenant_id",
                    )
                ],
            )
        ],
    )


def _policy_store(tmp_path) -> PolicyStore:
    policy_dir = tmp_path / "policies" / "fintech"
    policy_dir.mkdir(parents=True)
    domain_config = DomainConfig(
        name="fintech",
        domain_dir=tmp_path / "domains" / "fintech",
        policy_dir=policy_dir,
        schema_sql_path=tmp_path / "schema.sql",
        seed_script_path=tmp_path / "seed.py",
        database_url=None,
    )
    store = PolicyStore(domain_config)
    store.publish(
        [
            PolicyTable(
                table_name="claims",
                row_policy_template="tenant_id = :current_tenant",
                columns={
                    "claim_id": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    ),
                    "claim_amount": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    ),
                    "member_ssn": PolicyColumn(
                        action=PolicyAction.BLOCK, classification=Classification.PII_DIRECT
                    ),
                    "diagnosis_code": PolicyColumn(
                        action=PolicyAction.ROLE_GATE,
                        roles=["admin"],
                        classification=Classification.SENSITIVE_CATEGORY,
                    ),
                },
            )
        ],
        approved_by="admin",
    )
    return store


def test_enforcement_check_p95_latency_under_200ms(tmp_path):
    policy_store = _policy_store(tmp_path)
    schema = _schema()
    caller = Caller(role=ActorRole.ANALYST, tenant_id="tenant-001")

    durations: list[float] = []
    for _ in range(NUM_ITERATIONS):
        start = time.perf_counter()
        result = enforce(QUERY, schema, policy_store, caller)
        durations.append(time.perf_counter() - start)
        assert result.decision == Decision.ALLOW  # sanity: benchmarking the real ALLOW path

    p95 = statistics.quantiles(durations, n=100, method="inclusive")[94]
    assert p95 < P95_BUDGET_SECONDS, (
        f"p95 enforcement latency {p95 * 1000:.2f}ms over {NUM_ITERATIONS} single-query "
        f"runs exceeds NFR-002's {P95_BUDGET_SECONDS * 1000:.0f}ms budget"
    )
