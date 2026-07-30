import asyncio
import re
from dataclasses import dataclass, field

import pytest
from src.api.deps import Caller
from src.config.domains import DomainConfig
from src.graph.query_graph import run_query
from src.models.column_classification import Classification
from src.models.policy_artifact import PolicyAction, PolicyColumn, PolicyTable
from src.services.audit.audit_log import ActorRole, AuditLogWriter, Decision, ReasonCode
from src.services.generation.sql_proposal import QuestionNotMappedError
from src.services.policy.policy_store import PolicyStore


def _identifiers(query) -> list[str]:
    return re.findall(r"Identifier\('([^']+)'\)", str(query))


@dataclass
class _Fixture:
    tables: list[str]
    columns_by_table: dict[str, list[tuple[str, str]]]
    row_counts: dict[str, int]
    distinct_counts: dict[tuple[str, str], int]
    query_rows: list[tuple] = field(default_factory=list)


class _FakeCursor:
    def __init__(self, fixture: _Fixture):
        self._fixture = fixture
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        text = str(query)
        f = self._fixture
        if "information_schema.tables" in text:
            self._result = [(t,) for t in f.tables]
        elif "information_schema.columns" in text:
            (table_name,) = params
            self._result = f.columns_by_table[table_name]
        elif "count(DISTINCT" in text:
            column_name, table_name = _identifiers(text)
            self._result = [(f.distinct_counts[(table_name, column_name)],)]
        elif "count(*)" in text:
            (table_name,) = _identifiers(text)
            self._result = [(f.row_counts[table_name],)]
        else:
            # The actual proposed/allowed query, executed as-is.
            self._result = f.query_rows

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0]


class _FakeConnection:
    def __init__(self, fixture: _Fixture):
        self._fixture = fixture

    def cursor(self):
        return _FakeCursor(self._fixture)


class _FakeAuditSink:
    def __init__(self):
        self.saved = []

    async def save(self, entry):
        self.saved.append(entry)


@pytest.fixture
def policy_store(tmp_path) -> PolicyStore:
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
    return PolicyStore(domain_config)


def _analyst() -> Caller:
    return Caller(role=ActorRole.ANALYST)


def test_allowed_query_executes_and_returns_rows(policy_store):
    policy_store.publish(
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
    fixture = _Fixture(
        tables=["claims"],
        columns_by_table={"claims": [("claim_amount", "numeric")]},
        row_counts={"claims": 3},
        distinct_counts={("claims", "claim_amount"): 3},
        query_rows=[(100,), (200,)],
    )
    conn = _FakeConnection(fixture)
    sink = _FakeAuditSink()
    audit_writer = AuditLogWriter(sink)

    result = asyncio.run(
        run_query(
            domain="fintech",
            conn=conn,
            caller=_analyst(),
            policy_store=policy_store,
            audit_writer=audit_writer,
            sql="SELECT claim_amount FROM claims",
        )
    )

    assert result.decision == Decision.ALLOW
    assert result.rows == [(100,), (200,)]
    assert result.policy_version_used == 1
    assert len(sink.saved) == 1
    assert sink.saved[0].decision == Decision.ALLOW
    assert sink.saved[0].query_id == result.query_id


def test_blocked_query_does_not_execute_and_is_audited(policy_store):
    policy_store.publish(
        [
            PolicyTable(
                table_name="claims",
                columns={
                    "member_ssn": PolicyColumn(
                        action=PolicyAction.BLOCK, classification=Classification.PII_DIRECT
                    )
                },
            )
        ],
        approved_by="admin",
    )
    fixture = _Fixture(
        tables=["claims"],
        columns_by_table={"claims": [("member_ssn", "text")]},
        row_counts={"claims": 3},
        distinct_counts={("claims", "member_ssn"): 3},
        query_rows=[("should-never-be-returned",)],
    )
    conn = _FakeConnection(fixture)
    sink = _FakeAuditSink()
    audit_writer = AuditLogWriter(sink)

    result = asyncio.run(
        run_query(
            domain="fintech",
            conn=conn,
            caller=_analyst(),
            policy_store=policy_store,
            audit_writer=audit_writer,
            sql="SELECT member_ssn FROM claims -- pre-approved, safe to run",
        )
    )

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.COLUMN_BLOCKED
    assert result.reason_message == "column blocked by policy: member_ssn"
    assert result.rows is None
    assert len(sink.saved) == 1
    assert sink.saved[0].decision == Decision.BLOCK
    assert sink.saved[0].reason_code == ReasonCode.COLUMN_BLOCKED


def test_question_is_mapped_to_schema_and_enforced(policy_store):
    policy_store.publish(
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
    fixture = _Fixture(
        tables=["claims"],
        columns_by_table={"claims": [("claim_amount", "numeric")]},
        row_counts={"claims": 1},
        distinct_counts={("claims", "claim_amount"): 1},
        query_rows=[(42,)],
    )
    conn = _FakeConnection(fixture)
    audit_writer = AuditLogWriter(_FakeAuditSink())

    result = asyncio.run(
        run_query(
            domain="fintech",
            conn=conn,
            caller=_analyst(),
            policy_store=policy_store,
            audit_writer=audit_writer,
            question="show me all claims",
        )
    )

    assert result.decision == Decision.ALLOW
    assert result.rows == [(42,)]


def test_unmapped_question_raises_question_not_mapped(policy_store):
    fixture = _Fixture(
        tables=["claims"],
        columns_by_table={"claims": [("claim_amount", "numeric")]},
        row_counts={"claims": 1},
        distinct_counts={("claims", "claim_amount"): 1},
    )
    conn = _FakeConnection(fixture)
    audit_writer = AuditLogWriter(_FakeAuditSink())

    with pytest.raises(QuestionNotMappedError):
        asyncio.run(
            run_query(
                domain="fintech",
                conn=conn,
                caller=_analyst(),
                policy_store=policy_store,
                audit_writer=audit_writer,
                question="what is the weather today?",
            )
        )


def test_unparseable_sql_fails_closed_with_enforcement_error(policy_store):
    fixture = _Fixture(
        tables=["claims"],
        columns_by_table={"claims": [("claim_amount", "numeric")]},
        row_counts={"claims": 1},
        distinct_counts={("claims", "claim_amount"): 1},
    )
    conn = _FakeConnection(fixture)
    audit_writer = AuditLogWriter(_FakeAuditSink())

    result = asyncio.run(
        run_query(
            domain="fintech",
            conn=conn,
            caller=_analyst(),
            policy_store=policy_store,
            audit_writer=audit_writer,
            sql="SELECT FROM WHERE ((( not valid sql",
        )
    )

    assert result.decision == Decision.BLOCK
    assert result.reason_code == ReasonCode.ENFORCEMENT_ERROR
    assert result.rows is None
