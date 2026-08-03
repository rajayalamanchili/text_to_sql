"""Security test (FR-003, Constitution Principle I): no raw sample value
ever survives into the text actually sent to the LLM.

`test_masking.py` and `test_llm_classifier.py` each spot-check one hop of
this chain (`mask_column_profile` output, or `render_prompt`'s output,
individually). This file drives the full round trip —
`mask_column_profile` -> `render_prompt` — end to end, against a battery
of adversarial raw values (secrets, PII look-alikes, unicode, very long
strings, control characters), and checks not just exact-string
containment but every length->=4 alphanumeric substring of each raw
value, so a partial leak (e.g. a masking bug that only strips some
characters) fails the test too.
"""

from __future__ import annotations

import re

import pytest
from src.services.classification.llm_classifier import render_prompt
from src.services.classification.masking import mask_column_profile
from src.services.enumeration.schema_enumerator import ColumnSchema

_ALNUM_RUN = re.compile(r"\w{4,}", re.UNICODE)

_SCENARIOS = [
    pytest.param("text", ["123-45-6789", "987-65-4321"], id="ssn_like_digits"),
    pytest.param("text", ["alice@example.com", "bob.smith@corp.co"], id="email_addresses"),
    pytest.param("text", ["hunter2secret", "correcthorsebatterystaple"], id="secrets"),
    pytest.param(
        "text",
        ["Patient reports chest pain radiating to left arm since Tuesday."],
        id="free_text_clinical_note",
    ),
    pytest.param("text", ["4111111111111111", "5500005555555559"], id="credit_card_like"),
    pytest.param("text", ["José García", "北京市朝阳区"], id="unicode_names"),
    pytest.param("text", ["x" * 2000 + "topsecrettail"], id="very_long_string"),
    pytest.param(
        "text",
        ["line1\nline2secret", 'quote"embedded', "semi;colonvalue"],
        id="control_and_special_chars",
    ),
    pytest.param("bigint", [123456789012, 987654321098], id="numeric_values"),
    pytest.param("text", [None, "topsecretvalue123"], id="none_mixed_with_value"),
]


def _alnum_runs(value: str) -> list[str]:
    return _ALNUM_RUN.findall(value)


@pytest.mark.parametrize("data_type, raw_values", _SCENARIOS)
def test_no_raw_value_or_fragment_reaches_the_llm_prompt(data_type, raw_values):
    column = ColumnSchema(column_name="sensitive_col", data_type=data_type, cardinality_ratio=0.9)

    profile = mask_column_profile(column, raw_values)
    prompt = render_prompt(profile)
    dumped = profile.model_dump_json()

    for raw in raw_values:
        if raw is None:
            continue
        raw_str = str(raw)

        assert raw_str not in dumped, f"raw value {raw_str!r} leaked into masked profile"
        assert raw_str not in prompt, f"raw value {raw_str!r} leaked into LLM prompt"

        for fragment in _alnum_runs(raw_str):
            assert fragment not in dumped, (
                f"fragment {fragment!r} of raw value {raw_str!r} leaked into masked profile"
            )
            assert fragment not in prompt, (
                f"fragment {fragment!r} of raw value {raw_str!r} leaked into LLM prompt"
            )


def test_prompt_still_carries_non_sensitive_schema_metadata():
    """Guards against a masking bug that over-corrects by stripping
    legitimate, non-sensitive schema metadata (column name/type) along
    with the raw values — the prompt must still be useful to the LLM."""
    column = ColumnSchema(column_name="member_ssn", data_type="text", cardinality_ratio=0.99)

    profile = mask_column_profile(column, ["123-45-6789"])
    prompt = render_prompt(profile)

    assert "member_ssn" in prompt
    assert "text" in prompt
    assert profile.pattern_classes == [r"\d{3}-\d{2}-\d{4}"]
    assert str(profile.pattern_classes) in prompt
