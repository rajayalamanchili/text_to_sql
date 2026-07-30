import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from src.services.audit.audit_log import (
    ActorRole,
    AuditLogEntry,
    AuditLogWriter,
    Decision,
    PostgresAuditLogSink,
    ReasonCode,
    render_reason_message,
)


def test_create_renders_reason_message_from_template():
    entry = AuditLogEntry.create(
        domain="fintech",
        query_id=uuid.uuid4(),
        actor_role=ActorRole.ANALYST,
        decision=Decision.BLOCK,
        reason_code=ReasonCode.COLUMN_BLOCKED,
        reason_params={"column": "member_ssn"},
        policy_version_used=3,
    )

    assert entry.reason_message == "column blocked by policy: member_ssn"


def test_scenario6_no_active_policy_message_matches_spec():
    assert render_reason_message(ReasonCode.NO_ACTIVE_POLICY) == "schema not yet classified"


def test_create_accepts_a_prerendered_reason_message_directly():
    """T052: an enforcement decision (T048's `EnforcementResult`) already
    renders its own `reason_message` via `render_reason_message` at the
    point the decision is made — `create()` must accept that message
    as-is rather than forcing every caller to re-derive `reason_params`
    just to re-render the same template a second time."""
    entry = AuditLogEntry.create(
        domain="fintech",
        query_id=uuid.uuid4(),
        actor_role=ActorRole.ANALYST,
        decision=Decision.BLOCK,
        reason_code=ReasonCode.COLUMN_BLOCKED,
        reason_message="column blocked by policy: member_ssn",
        policy_version_used=3,
    )

    assert entry.reason_message == "column blocked by policy: member_ssn"


def test_create_rejects_both_reason_params_and_reason_message():
    with pytest.raises(ValueError, match="not both"):
        AuditLogEntry.create(
            domain="fintech",
            query_id=uuid.uuid4(),
            actor_role=ActorRole.ANALYST,
            decision=Decision.BLOCK,
            reason_code=ReasonCode.COLUMN_BLOCKED,
            reason_params={"column": "member_ssn"},
            reason_message="column blocked by policy: member_ssn",
        )


def test_create_with_allow_decision_and_no_reason_code():
    entry = AuditLogEntry.create(
        domain="fintech",
        query_id=uuid.uuid4(),
        actor_role=ActorRole.ANALYST,
        decision=Decision.ALLOW,
        policy_version_used=3,
    )

    assert entry.reason_code is None
    assert entry.reason_message is None


def test_scenario7_role_gate_message_matches_spec():
    message = render_reason_message(ReasonCode.ROLE_GATE_MISMATCH, role="admin")

    assert message == "column requires role: admin"


def test_create_without_reason_code_leaves_message_null():
    entry = AuditLogEntry.create(
        domain="healthcare",
        query_id=uuid.uuid4(),
        actor_role=ActorRole.ADMIN,
        decision=Decision.ALLOW,
    )

    assert entry.reason_code is None
    assert entry.reason_message is None


def test_reason_code_and_message_must_be_paired():
    with pytest.raises(ValidationError):
        AuditLogEntry(
            id=uuid.uuid4(),
            timestamp="2026-07-28T00:00:00Z",
            domain="healthcare",
            query_id=uuid.uuid4(),
            actor_role=ActorRole.ANALYST,
            decision=Decision.BLOCK,
            reason_code=ReasonCode.COLUMN_BLOCKED,
            reason_message=None,
        )


class _FakeSink:
    def __init__(self):
        self.saved = []

    async def save(self, entry):
        self.saved.append(entry)


def test_writer_persists_to_sink_when_configured():
    sink = _FakeSink()
    writer = AuditLogWriter(sink=sink)
    entry = AuditLogEntry.create(
        domain="healthcare",
        query_id=uuid.uuid4(),
        actor_role=ActorRole.ADMIN,
        decision=Decision.ALLOW,
    )

    asyncio.run(writer.write(entry))

    assert sink.saved == [entry]


def test_writer_without_sink_does_not_raise():
    writer = AuditLogWriter()
    entry = AuditLogEntry.create(
        domain="healthcare",
        query_id=uuid.uuid4(),
        actor_role=ActorRole.ADMIN,
        decision=Decision.ALLOW,
    )

    asyncio.run(writer.write(entry))


def _fake_conn():
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def test_postgres_sink_applies_migration_ddl_on_construction():
    conn, cursor = _fake_conn()

    PostgresAuditLogSink(conn)

    ddl_calls = [c for c in cursor.execute.call_args_list if "CREATE TABLE" in str(c.args[0])]
    assert len(ddl_calls) == 1
    assert "audit_log" in str(ddl_calls[0].args[0])
    conn.commit.assert_called()


def test_postgres_sink_inserts_entry_and_commits():
    conn, cursor = _fake_conn()
    sink = PostgresAuditLogSink(conn)
    cursor.execute.reset_mock()
    conn.commit.reset_mock()
    entry = AuditLogEntry.create(
        domain="healthcare",
        query_id=uuid.uuid4(),
        actor_role=ActorRole.ANALYST,
        decision=Decision.CLASSIFY_AUTO_APPROVED,
    )

    asyncio.run(sink.save(entry))

    (query, params), _ = cursor.execute.call_args
    assert "INSERT INTO audit_log" in query
    assert params["id"] == entry.id
    assert params["decision"] == "classify_auto_approved"
    assert params["reason_code"] is None
    conn.commit.assert_called_once()


def _audit_row(**overrides):
    row = {
        "id": uuid.uuid4(),
        "timestamp": datetime.now(UTC),
        "domain": "fintech",
        "query_id": uuid.uuid4(),
        "actor_role": "analyst",
        "decision": "block",
        "reason_code": "COLUMN_BLOCKED",
        "reason_message": "column blocked by policy: member_ssn",
        "policy_version_used": 1,
        "raw_query_hash": "abc123",
    }
    row.update(overrides)
    return tuple(row.values())


def test_list_entries_passes_filters_and_maps_rows(monkeypatch):
    conn, cursor = _fake_conn()
    rows = [_audit_row()]
    cursor.fetchall.return_value = rows
    sink = PostgresAuditLogSink(conn)
    cursor.execute.reset_mock()

    from_ts = datetime.now(UTC)
    to_ts = datetime.now(UTC)
    entries = sink.list_entries(from_ts=from_ts, to_ts=to_ts, decision=Decision.BLOCK)

    (query, params), _ = cursor.execute.call_args
    assert "SELECT" in query
    assert "FROM audit_log" in query
    assert params["from_ts"] == from_ts
    assert params["to_ts"] == to_ts
    assert params["decision"] == "block"
    assert len(entries) == 1
    assert entries[0].decision == Decision.BLOCK
    assert entries[0].reason_code == ReasonCode.COLUMN_BLOCKED
    assert entries[0].domain == "fintech"


def test_list_entries_with_no_filters_passes_nulls():
    conn, cursor = _fake_conn()
    cursor.fetchall.return_value = []
    sink = PostgresAuditLogSink(conn)
    cursor.execute.reset_mock()

    entries = sink.list_entries()

    (_, params), _ = cursor.execute.call_args
    assert params == {"from_ts": None, "to_ts": None, "decision": None}
    assert entries == []
