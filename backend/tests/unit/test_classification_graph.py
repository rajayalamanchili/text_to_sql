import asyncio
import re
from dataclasses import dataclass, field

from src.graph.classification_graph import run_classification
from src.models.column_classification import Classification, ClassificationStatus
from src.services.classification.llm_classifier import LLMClassificationResponse


def _identifiers(query) -> list[str]:
    return re.findall(r"Identifier\('([^']+)'\)", str(query))


@dataclass
class _Fixture:
    tables: list[str]
    columns_by_table: dict[str, list[tuple[str, str]]]
    row_counts: dict[str, int]
    distinct_counts: dict[tuple[str, str], int]
    sample_values: dict[tuple[str, str], list[str]] = field(default_factory=dict)


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
        elif "LIMIT" in text:
            column_name, table_name = _identifiers(text)
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


class _StubLLMClient:
    def __init__(self, response: LLMClassificationResponse):
        self._response = response
        self.call_count = 0

    async def classify_column(self, profile):
        self.call_count += 1
        return self._response


class _StubStore:
    def __init__(self):
        self.saved = []

    async def save(self, record):
        self.saved.append(record)


def test_high_confidence_column_skips_llm_entirely():
    fixture = _Fixture(
        tables=["patients"],
        columns_by_table={"patients": [("patient_ssn", "text")]},
        row_counts={"patients": 10},
        distinct_counts={("patients", "patient_ssn"): 10},
    )
    conn = _FakeConnection(fixture)
    llm_client = _StubLLMClient(
        LLMClassificationResponse(
            classification=Classification.BUSINESS, confidence=0.99, rationale="should not run"
        )
    )
    store = _StubStore()

    records = asyncio.run(
        run_classification(domain="healthcare", conn=conn, llm_client=llm_client, store=store)
    )

    assert llm_client.call_count == 0
    assert len(records) == 1
    record = records[0]
    assert record.classification == Classification.PII_DIRECT
    assert record.status == ClassificationStatus.AUTO_APPROVED
    assert record.llm_score is None
    assert store.saved == records


def test_low_confidence_column_routes_through_llm_and_persists_combined_result():
    fixture = _Fixture(
        tables=["patients"],
        columns_by_table={
            "patients": [("patient_ssn", "text"), ("notes", "text")],
        },
        row_counts={"patients": 10},
        distinct_counts={("patients", "patient_ssn"): 10, ("patients", "notes"): 2},
        sample_values={("patients", "notes"): ["short note", "short note", "another one"]},
    )
    conn = _FakeConnection(fixture)
    llm_client = _StubLLMClient(
        LLMClassificationResponse(
            classification=Classification.SENSITIVE_CATEGORY,
            confidence=0.9,
            rationale="looks categorical",
        )
    )
    store = _StubStore()

    records = asyncio.run(
        run_classification(domain="healthcare", conn=conn, llm_client=llm_client, store=store)
    )

    assert llm_client.call_count == 1  # only the low-confidence column triggered it
    by_column = {r.column_name: r for r in records}

    ssn_record = by_column["patient_ssn"]
    assert ssn_record.classification == Classification.PII_DIRECT
    assert ssn_record.llm_score is None

    notes_record = by_column["notes"]
    assert notes_record.classification == Classification.SENSITIVE_CATEGORY
    assert notes_record.confidence == 0.9
    assert notes_record.llm_score == 0.9
    assert notes_record.status == ClassificationStatus.AUTO_APPROVED
    assert store.saved == records


def test_still_below_threshold_after_llm_lands_in_pending_review():
    fixture = _Fixture(
        tables=["transactions"],
        columns_by_table={"transactions": [("notes", "text")]},
        row_counts={"transactions": 10},
        distinct_counts={("transactions", "notes"): 1},
        sample_values={("transactions", "notes"): ["memo", "memo"]},
    )
    conn = _FakeConnection(fixture)
    llm_client = _StubLLMClient(
        LLMClassificationResponse(
            classification=Classification.SENSITIVE_CATEGORY, confidence=0.6, rationale="unsure"
        )
    )
    store = _StubStore()

    records = asyncio.run(
        run_classification(domain="fintech", conn=conn, llm_client=llm_client, store=store)
    )

    assert len(records) == 1
    record = records[0]
    assert record.status == ClassificationStatus.PENDING_REVIEW
    assert record.classification != Classification.BUSINESS
