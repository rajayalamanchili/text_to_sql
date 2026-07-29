"""Anthropic-backed `LLMClassifierClient` adapter (FR-003, tech-stack.md:
"LLM provider: Anthropic Claude (primary)").

The first concrete implementation of the `LLMClassifierClient` protocol
defined in `llm_classifier.py` — everything before this task was the
provider-agnostic interface plus `NullLLMClient`, a safe placeholder that
never actually calls a model. This module sends the masked column
profile (`render_prompt`, research.md §3) to Claude via structured
outputs and parses the response back into `LLMClassificationResponse` —
never a raw column value, only what `render_prompt` already includes.

`build_default_llm_client()` is the selection point future callers
(e.g. the `/classify` endpoint) should use: it returns this adapter when
an Anthropic credential is configured, and falls back to `NullLLMClient`
otherwise, so the classification pipeline keeps working (conservatively —
never a fabricated auto-approval) in environments with no API key.
"""

from __future__ import annotations

import os

import anthropic

from src.services.classification.llm_classifier import (
    LLMClassificationResponse,
    LLMClassifierClient,
    NullLLMClient,
    render_prompt,
)
from src.services.classification.masking import MaskedColumnProfile

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_MAX_TOKENS = 1024

_SYSTEM_PROMPT = (
    "You are a data governance classifier for a database column-sensitivity "
    "pipeline. You are given only masked, aggregated metadata about a "
    "column — its name, data type, cardinality ratio, a value-length "
    "distribution, and regex-generalized value patterns — never a raw "
    "value. Classify the column's sensitivity as exactly one of: "
    "pii_direct, pii_indirect, sensitive_category, business, unclassified. "
    "Favor a more sensitive category and a lower confidence when uncertain "
    "— this pipeline treats low confidence as a safe, conservative signal "
    "that routes the column to human review, not a failure."
)


class AnthropicLLMClient:
    """Calls the Anthropic Messages API to classify one column from its
    masked profile. Implements `LLMClassifierClient` (llm_classifier.py)."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic | None = None,
        *,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self._client = client or anthropic.AsyncAnthropic()
        self._model = model

    async def classify_column(self, profile: MaskedColumnProfile) -> LLMClassificationResponse:
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=DEFAULT_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            output_config={"effort": "low"},  # narrow, single-turn classification
            messages=[{"role": "user", "content": render_prompt(profile)}],
            output_format=LLMClassificationResponse,
        )
        return response.parsed_output


def build_default_llm_client() -> LLMClassifierClient:
    """Select the LLM client for the classification pipeline: the real
    Anthropic adapter when a credential is configured, `NullLLMClient`
    otherwise. Checked via `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`
    rather than instantiating the client, since construction alone
    doesn't fail on a missing key — only the first real call would."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return AnthropicLLMClient()
    return NullLLMClient()
