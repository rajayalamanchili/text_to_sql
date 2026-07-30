import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

from src.models.column_classification import (
    Classification,
    ClassificationSource,
    ClassificationStatus,
    ColumnClassification,
)
from src.services.audit.audit_log import ActorRole, Decision
from src.services.classification.persistence import PostgresClassificationStore


def _fake_conn():
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def _record(**overrides):
    defaults = dict(
        id=uuid4(),
        domain="healthcare",
        table_name="patients",
        column_name="patient_ssn",
        data_type="text",
        cardinality_ratio=0.99,
        classification=Classification.PII_DIRECT,
        heuristic_score=0.95,
        llm_score=None,
        confidence=0.95,
        source=ClassificationSource.HEURISTIC,
        status=ClassificationStatus.AUTO_APPROVED,
        reviewed_by=None,
        reviewed_at=None,
        llm_rationale=None,
    )
    defaults.update(overrides)
    return ColumnClassification(**defaults)


def test_construction_applies_migration_ddl():
    conn, cursor = _fake_conn()

    PostgresClassificationStore(conn)

    ddl_calls = [c for c in cursor.execute.call_args_list if "CREATE TABLE" in str(c.args[0])]
    assert len(ddl_calls) == 1
    assert "column_classifications" in str(ddl_calls[0].args[0])
    conn.commit.assert_called()


def test_save_upserts_with_expected_params_and_commits():
    conn, cursor = _fake_conn()
    store = PostgresClassificationStore(conn)
    cursor.execute.reset_mock()
    conn.commit.reset_mock()
    record = _record()

    asyncio.run(store.save(record))

    (query, params), _ = cursor.execute.call_args
    assert "INSERT INTO column_classifications" in query
    assert "ON CONFLICT (domain, table_name, column_name)" in query
    assert params["id"] == record.id
    assert params["classification"] == "pii_direct"
    assert params["status"] == "auto_approved"
    conn.commit.assert_called_once()


def test_upsert_clears_prior_review_state_on_conflict():
    conn, cursor = _fake_conn()
    store = PostgresClassificationStore(conn)
    cursor.execute.reset_mock()

    asyncio.run(store.save(_record()))

    (query, _params), _ = cursor.execute.call_args
    assert "reviewed_by = NULL" in query
    assert "reviewed_at = NULL" in query


class _FakeAuditWriter:
    def __init__(self):
        self.written = []

    async def write(self, entry):
        self.written.append(entry)


def test_save_writes_audit_entry_with_shared_run_id_and_caller_role():
    conn, _cursor = _fake_conn()
    audit_writer = _FakeAuditWriter()
    store = PostgresClassificationStore(conn, audit_writer=audit_writer, actor_role=ActorRole.ADMIN)

    asyncio.run(store.save(_record(status=ClassificationStatus.AUTO_APPROVED)))
    asyncio.run(store.save(_record(status=ClassificationStatus.PENDING_REVIEW)))

    assert len(audit_writer.written) == 2
    first, second = audit_writer.written
    assert first.decision == Decision.CLASSIFY_AUTO_APPROVED
    assert second.decision == Decision.CLASSIFY_PENDING_REVIEW
    assert first.query_id == second.query_id == store.run_id
    assert first.actor_role == ActorRole.ADMIN
    assert first.reason_code is None
    assert first.policy_version_used is None


def test_save_without_audit_writer_does_not_raise():
    conn, _cursor = _fake_conn()
    store = PostgresClassificationStore(conn)

    asyncio.run(store.save(_record()))  # no audit_writer configured — should be a no-op


def test_approve_transitions_status_and_writes_audit_entry_with_actor_role():
    conn, _cursor = _fake_conn()
    audit_writer = _FakeAuditWriter()
    store = PostgresClassificationStore(conn, audit_writer=audit_writer, actor_role=ActorRole.ADMIN)
    record = _record(status=ClassificationStatus.PENDING_REVIEW)

    updated = asyncio.run(store.approve(record, reviewed_by=ActorRole.ADMIN.value))

    assert updated.status == ClassificationStatus.APPROVED
    assert updated.reviewed_by == "admin"
    assert updated.reviewed_at is not None
    assert len(audit_writer.written) == 1
    entry = audit_writer.written[0]
    assert entry.decision == Decision.CLASSIFY_APPROVED
    assert entry.actor_role == ActorRole.ADMIN
    assert entry.query_id == updated.id


def test_reject_transitions_status_and_writes_audit_entry_with_actor_role():
    conn, _cursor = _fake_conn()
    audit_writer = _FakeAuditWriter()
    store = PostgresClassificationStore(conn, audit_writer=audit_writer, actor_role=ActorRole.ADMIN)
    record = _record(status=ClassificationStatus.PENDING_REVIEW)

    updated = asyncio.run(store.reject(record, reviewed_by=ActorRole.ADMIN.value))

    assert updated.status == ClassificationStatus.REJECTED
    assert updated.reviewed_by == "admin"
    assert updated.reviewed_at is not None
    assert len(audit_writer.written) == 1
    entry = audit_writer.written[0]
    assert entry.decision == Decision.CLASSIFY_REJECTED
    assert entry.actor_role == ActorRole.ADMIN
    assert entry.query_id == updated.id


def test_reclassify_overwrites_classification_and_writes_audit_entry():
    conn, _cursor = _fake_conn()
    audit_writer = _FakeAuditWriter()
    store = PostgresClassificationStore(conn, audit_writer=audit_writer, actor_role=ActorRole.ADMIN)
    record = _record(
        status=ClassificationStatus.PENDING_REVIEW,
        classification=Classification.UNCLASSIFIED,
        source=ClassificationSource.HEURISTIC,
    )

    updated = asyncio.run(
        store.reclassify(
            record, classification=Classification.PII_DIRECT, reviewed_by=ActorRole.ADMIN.value
        )
    )

    assert updated.classification == Classification.PII_DIRECT
    assert updated.source == ClassificationSource.HUMAN
    assert updated.status == ClassificationStatus.APPROVED
    assert updated.reviewed_by == "admin"
    assert updated.reviewed_at is not None
    assert len(audit_writer.written) == 1
    entry = audit_writer.written[0]
    assert entry.decision == Decision.CLASSIFY_APPROVED
    assert entry.actor_role == ActorRole.ADMIN
    assert entry.query_id == updated.id


def test_list_records_converts_rows_back_to_column_classification():
    conn, cursor = _fake_conn()
    store = PostgresClassificationStore(conn)
    record_id = uuid4()
    cursor.fetchall.return_value = [
        (
            record_id,
            "healthcare",
            "patients",
            "patient_ssn",
            "text",
            0.99,
            "pii_direct",
            0.95,
            None,
            0.95,
            "heuristic",
            "auto_approved",
            None,
            None,
            None,
        )
    ]

    records = store.list_records("healthcare")

    assert len(records) == 1
    record = records[0]
    assert record.id == record_id
    assert record.classification == Classification.PII_DIRECT
    assert record.status == ClassificationStatus.AUTO_APPROVED
    assert record.source == ClassificationSource.HEURISTIC
