import asyncio
import uuid

import pytest
from pydantic import ValidationError
from src.services.audit.audit_log import (
    ActorRole,
    AuditLogEntry,
    AuditLogWriter,
    Decision,
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
