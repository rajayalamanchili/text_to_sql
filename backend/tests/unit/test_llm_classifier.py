import asyncio

from src.models.column_classification import Classification
from src.services.classification.heuristic_classifier import classify_heuristically
from src.services.classification.llm_classifier import (
    MAX_LLM_CONFIDENCE,
    LLMClassificationResponse,
    NullLLMClient,
    classify_with_llm,
    render_prompt,
)
from src.services.classification.masking import mask_column_profile
from src.services.enumeration.schema_enumerator import ColumnSchema


def _profile():
    column = ColumnSchema(column_name="notes", data_type="text", cardinality_ratio=0.05)
    return mask_column_profile(column, ["hunter2secret", "another-value-here"])


class _StubClient:
    def __init__(self, response: LLMClassificationResponse):
        self._response = response
        self.received_profile = None

    async def classify_column(self, profile):
        self.received_profile = profile
        return self._response


def test_classify_with_llm_returns_clamped_result():
    stub = _StubClient(
        LLMClassificationResponse(
            classification=Classification.SENSITIVE_CATEGORY,
            confidence=0.8,
            rationale="looks like free text",
        )
    )

    result = asyncio.run(classify_with_llm(_profile(), stub))

    assert result.classification == Classification.SENSITIVE_CATEGORY
    assert result.score == 0.8
    assert result.rationale == "looks like free text"


def test_classify_with_llm_clamps_confidence_above_max():
    stub = _StubClient(
        LLMClassificationResponse(
            classification=Classification.PII_DIRECT, confidence=1.0, rationale="certain"
        )
    )

    result = asyncio.run(classify_with_llm(_profile(), stub))

    assert result.score <= MAX_LLM_CONFIDENCE


def test_classify_with_llm_clamps_confidence_below_zero():
    stub = _StubClient(
        LLMClassificationResponse(
            classification=Classification.BUSINESS, confidence=-0.5, rationale="bug"
        )
    )

    result = asyncio.run(classify_with_llm(_profile(), stub))

    assert result.score == 0.0


def test_classify_with_llm_only_sends_masked_profile_never_raw_values():
    raw_values = ["hunter2secret", "another-value-here"]
    profile = mask_column_profile(
        ColumnSchema(column_name="notes", data_type="text", cardinality_ratio=0.05), raw_values
    )
    stub = _StubClient(
        LLMClassificationResponse(
            classification=Classification.SENSITIVE_CATEGORY, confidence=0.7, rationale="r"
        )
    )

    asyncio.run(classify_with_llm(profile, stub))

    dumped = stub.received_profile.model_dump_json()
    for raw in raw_values:
        assert raw not in dumped


def test_null_llm_client_never_raises_confidence_above_heuristic():
    from src.services.classification.confidence import combine_confidence

    column = ColumnSchema(column_name="notes", data_type="text", cardinality_ratio=0.05)
    heuristic = classify_heuristically(column)  # sensitive_category, low confidence
    profile = mask_column_profile(column, ["short note", "another one"])

    llm_result = asyncio.run(classify_with_llm(profile, NullLLMClient()))
    combined = combine_confidence(heuristic, llm_result)

    assert combined.classification == heuristic.classification
    assert combined.confidence == heuristic.score


def test_null_llm_client_response_is_transparent_about_not_running():
    profile = mask_column_profile(
        ColumnSchema(column_name="notes", data_type="text", cardinality_ratio=0.05), []
    )

    result = asyncio.run(classify_with_llm(profile, NullLLMClient()))

    assert "not configured" in result.rationale.lower()


def test_render_prompt_never_contains_raw_value_fragment():
    raw_values = ["123-45-6789", "topsecretvalue"]
    profile = mask_column_profile(
        ColumnSchema(column_name="member_ssn", data_type="text", cardinality_ratio=0.99),
        raw_values,
    )

    prompt = render_prompt(profile)

    for raw in raw_values:
        assert raw not in prompt
    assert "member_ssn" in prompt
