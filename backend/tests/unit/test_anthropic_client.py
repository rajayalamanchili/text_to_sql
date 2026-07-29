import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.models.column_classification import Classification
from src.services.classification.anthropic_client import (
    AnthropicLLMClient,
    build_default_llm_client,
)
from src.services.classification.llm_classifier import (
    LLMClassificationResponse,
    NullLLMClient,
)
from src.services.classification.masking import mask_column_profile
from src.services.enumeration.schema_enumerator import ColumnSchema


def _profile():
    column = ColumnSchema(column_name="notes", data_type="text", cardinality_ratio=0.05)
    return mask_column_profile(column, ["short note", "another one"])


def _fake_sdk_client(parsed_output: LLMClassificationResponse) -> MagicMock:
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.parsed_output = parsed_output
    fake_client.messages.parse = AsyncMock(return_value=fake_response)
    return fake_client


def test_classify_column_returns_parsed_output():
    expected = LLMClassificationResponse(
        classification=Classification.SENSITIVE_CATEGORY,
        confidence=0.8,
        rationale="looks categorical",
    )
    sdk_client = _fake_sdk_client(expected)
    adapter = AnthropicLLMClient(client=sdk_client)

    result = asyncio.run(adapter.classify_column(_profile()))

    assert result == expected


def test_classify_column_sends_only_masked_profile_never_raw_values():
    raw_values = ["hunter2secret", "another-value-here"]
    profile = mask_column_profile(
        ColumnSchema(column_name="notes", data_type="text", cardinality_ratio=0.05), raw_values
    )
    sdk_client = _fake_sdk_client(
        LLMClassificationResponse(
            classification=Classification.SENSITIVE_CATEGORY, confidence=0.7, rationale="r"
        )
    )
    adapter = AnthropicLLMClient(client=sdk_client)

    asyncio.run(adapter.classify_column(profile))

    _args, kwargs = sdk_client.messages.parse.call_args
    sent_content = kwargs["messages"][0]["content"]
    for raw in raw_values:
        assert raw not in sent_content


def test_classify_column_uses_default_model_and_output_format():
    sdk_client = _fake_sdk_client(
        LLMClassificationResponse(
            classification=Classification.BUSINESS, confidence=0.9, rationale="r"
        )
    )
    adapter = AnthropicLLMClient(client=sdk_client)

    asyncio.run(adapter.classify_column(_profile()))

    _args, kwargs = sdk_client.messages.parse.call_args
    assert kwargs["model"] == "claude-opus-4-8"
    assert kwargs["output_format"] is LLMClassificationResponse


def test_classify_column_respects_custom_model():
    sdk_client = _fake_sdk_client(
        LLMClassificationResponse(
            classification=Classification.BUSINESS, confidence=0.9, rationale="r"
        )
    )
    adapter = AnthropicLLMClient(client=sdk_client, model="claude-haiku-4-5")

    asyncio.run(adapter.classify_column(_profile()))

    _args, kwargs = sdk_client.messages.parse.call_args
    assert kwargs["model"] == "claude-haiku-4-5"


def test_build_default_llm_client_falls_back_to_null_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    client = build_default_llm_client()

    assert isinstance(client, NullLLMClient)


def test_build_default_llm_client_uses_anthropic_when_api_key_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    client = build_default_llm_client()

    assert isinstance(client, AnthropicLLMClient)


def test_build_default_llm_client_uses_anthropic_when_auth_token_present(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-value")

    client = build_default_llm_client()

    assert isinstance(client, AnthropicLLMClient)
