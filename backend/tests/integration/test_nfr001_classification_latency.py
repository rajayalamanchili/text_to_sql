"""NFR-001 timing test: a 50-table schema classifies end-to-end (heuristic
+ LLM-assisted passes) in under 5 minutes.

Scope note: this exercises the classification *pipeline* only — an
in-memory fake DB connection (same pattern as
`tests/unit/test_classification_graph.py`) and a near-instant stub LLM
client, never a real Postgres instance or the real Anthropic API. Real
LLM call latency is provider/network-dependent and non-deterministic, so
it can't be asserted against in a repeatable CI test; this test instead
proves the engine's own per-column bookkeeping (enumeration fan-out,
heuristic scoring, confidence combination, persistence) has no
algorithmic blowup that would eat the 5-minute budget before a single
real LLM call is even made. The bound asserted below (30s) is
deliberately far tighter than the 300s NFR itself, so a regression here
is caught long before it could threaten the real budget — real end-to-end
timing against a live provider is a manual/spot-check concern (see
quickstart.md), not something this suite can own deterministically.

Columns are named so most of them (record_id, notes, created_at, status,
amount) miss every heuristic name-pattern and fall through to the LLM
pass — only ssn/email/diagnosis_code skip it — matching how a real
schema mostly consists of un-flagged operational columns, not PII
lookalikes, so this exercises the (currently sequential) LLM fan-out at
realistic scale.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

from src.graph.classification_graph import run_classification
from src.models.column_classification import Classification
from src.services.classification.llm_classifier import LLMClassificationResponse

NUM_TABLES = 50
# record_id, ssn, email, diagnosis_code, notes, created_at, status, amount
COLUMNS_PER_TABLE = 8
ENGINE_OVERHEAD_BUDGET_SECONDS = 30  # << NFR-001's 300s; see module docstring
ROW_COUNT = 100


def _column_defs() -> list[tuple[str, str]]:
    return [
        ("record_id", "integer"),
        ("ssn", "text"),
        ("email", "text"),
        ("diagnosis_code", "text"),
        ("notes", "text"),
        ("created_at", "timestamp"),
        ("status", "text"),
        ("amount", "numeric"),
    ]


@dataclass
class _Fixture:
    tables: list[str]
    columns_by_table: dict[str, list[tuple[str, str]]]
    row_counts: dict[str, int]
    distinct_counts: dict[tuple[str, str], int]
    sample_values: dict[tuple[str, str], list[str]] = field(default_factory=dict)


def _build_fixture(num_tables: int) -> _Fixture:
    tables = [f"table_{i:03d}" for i in range(num_tables)]
    columns_by_table = {table: _column_defs() for table in tables}
    row_counts = {table: ROW_COUNT for table in tables}
    distinct_counts: dict[tuple[str, str], int] = {}
    sample_values: dict[tuple[str, str], list[str]] = {}
    for table in tables:
        for column_name, _data_type in _column_defs():
            distinct_counts[(table, column_name)] = ROW_COUNT
            sample_values[(table, column_name)] = ["sample-a", "sample-b", "sample-c"]
    return _Fixture(tables, columns_by_table, row_counts, distinct_counts, sample_values)


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
            column_name, table_name = re.findall(r"Identifier\('([^']+)'\)", text)
            self._result = [(f.distinct_counts[(table_name, column_name)],)]
        elif "count(*)" in text:
            (table_name,) = re.findall(r"Identifier\('([^']+)'\)", text)
            self._result = [(f.row_counts[table_name],)]
        elif "LIMIT" in text:
            column_name, table_name = re.findall(r"Identifier\('([^']+)'\)", text)
            self._result = [(v,) for v in f.sample_values[(table_name, column_name)]]
        else:
            raise AssertionError(f"unexpected query: {text}")

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0]


class _FakeConnection:
    def __init__(self, fixture: _Fixture):
        self._fixture = fixture

    def cursor(self):
        return _FakeCursor(self._fixture)


class _InstantStubLLMClient:
    """Returns immediately — see module docstring for why real LLM
    latency is out of scope for this test."""

    def __init__(self):
        self.call_count = 0

    async def classify_column(self, profile):
        self.call_count += 1
        return LLMClassificationResponse(
            classification=Classification.SENSITIVE_CATEGORY,
            confidence=0.6,
            rationale="stub",
        )


class _StubStore:
    def __init__(self):
        self.saved = []

    async def save(self, record):
        self.saved.append(record)


def test_fifty_table_schema_classifies_within_engine_overhead_budget():
    fixture = _build_fixture(NUM_TABLES)
    conn = _FakeConnection(fixture)
    llm_client = _InstantStubLLMClient()
    store = _StubStore()

    start = time.perf_counter()
    records = asyncio.run(
        run_classification(domain="healthcare", conn=conn, llm_client=llm_client, store=store)
    )
    elapsed = time.perf_counter() - start

    assert len(records) == NUM_TABLES * COLUMNS_PER_TABLE
    # Most columns (record_id, notes, created_at, status, amount) miss every
    # heuristic name pattern and fall through to the LLM pass.
    assert llm_client.call_count == NUM_TABLES * 5
    assert elapsed < ENGINE_OVERHEAD_BUDGET_SECONDS, (
        f"classification pipeline took {elapsed:.2f}s for a {NUM_TABLES}-table schema, "
        f"exceeding the {ENGINE_OVERHEAD_BUDGET_SECONDS}s engine-overhead budget "
        f"(NFR-001's full budget is 300s including real LLM network latency)"
    )
