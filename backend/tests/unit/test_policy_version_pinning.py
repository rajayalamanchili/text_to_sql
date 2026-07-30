"""Unit test for T044a (FR-007's policy-version-pinning guarantee).

Per spec.md's Clarifications (2026-07-27): "the active policy version is
resolved once, at the start of a query's enforcement evaluation, and used
for every check in that evaluation; a concurrent publish has no effect on
the in-flight query." `enforce()` (T048) only calls
`PolicyStore.active_version()`/`get_version()` once, via
`_load_active_policy`, and never re-queries the store afterward — this
test proves that structural guarantee by simulating a publish landing in
the exact window between the enforcer resolving the version and finishing
its evaluation.
"""

from __future__ import annotations

from src.config.domains import DomainConfig
from src.models.column_classification import Classification
from src.models.policy_artifact import PolicyAction, PolicyColumn, PolicyTable
from src.services.audit.audit_log import Decision
from src.services.enforcement.enforcer import enforce
from src.services.enumeration.schema_enumerator import (
    ColumnSchema,
    DomainSchemaSnapshot,
    TableSchema,
)
from src.services.policy.policy_store import PolicyStore


def _schema(**tables: list[str]) -> DomainSchemaSnapshot:
    return DomainSchemaSnapshot(
        domain="fintech",
        tables=[
            TableSchema(
                table_name=table_name,
                columns=[
                    ColumnSchema(column_name=column_name, data_type="text", cardinality_ratio=0.5)
                    for column_name in column_names
                ],
            )
            for table_name, column_names in tables.items()
        ],
    )


class _PublishDuringEnforcementPolicyStore(PolicyStore):
    """Simulates an admin publishing a new policy version in the window
    between the enforcer resolving the active version and finishing its
    evaluation. `get_version` is the last store call `enforce()` makes
    before pinning its local `artifact` variable for the rest of the
    evaluation, so triggering the republish there reproduces the race
    exactly where FR-007 says it must have no effect."""

    def __init__(self, domain_config: DomainConfig, *, republish_tables: list[PolicyTable]) -> None:
        super().__init__(domain_config)
        self._republish_tables = republish_tables
        self.republished = False

    def get_version(self, version: int):
        artifact = super().get_version(version)
        if not self.republished:
            self.republished = True
            super().publish(self._republish_tables, approved_by="admin")
        return artifact


def test_concurrent_publish_does_not_affect_in_flight_query(tmp_path):
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

    setup_store = PolicyStore(domain_config)
    setup_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "claim_amount": PolicyColumn(
                        action=PolicyAction.ALLOW, classification=Classification.BUSINESS
                    )
                },
            )
        ],
        approved_by="admin",
    )

    # What an admin publishes *during* the in-flight query's evaluation:
    # the same column, now blocked.
    republish_tables = [
        PolicyTable(
            table_name="claims",
            columns={
                "claim_amount": PolicyColumn(
                    action=PolicyAction.BLOCK, classification=Classification.BUSINESS
                )
            },
        )
    ]
    racing_store = _PublishDuringEnforcementPolicyStore(
        domain_config, republish_tables=republish_tables
    )
    schema = _schema(claims=["claim_amount"])

    result = enforce("SELECT claim_amount FROM claims", schema, racing_store)

    assert racing_store.republished is True
    # A newer version now exists in the store...
    assert racing_store.active_version() == 2
    # ...but the in-flight query's decision was pinned to version 1's
    # policy (ALLOW), never seeing the concurrent republish to BLOCK.
    assert result.policy_version_used == 1
    assert result.decision == Decision.ALLOW
