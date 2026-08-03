"""Value-pattern masking utility (FR-003, research.md §3).

Turns a column's raw sample values into a safe, generalized summary — a
length-bucket distribution and regex-generalized pattern classes — that
the LLM-assisted classification pass (T022) sends to the LLM instead of
any raw value. A digit-string sample like `"123-45-6789"` becomes the
pattern `\\d{3}-\\d{2}-\\d{4}`; no literal digit or letter from any sample
ever appears in the output (Constitution Principle I).

This module never opens a database connection itself — callers (T022)
are responsible for fetching `sample_values` and must not persist, log,
or otherwise forward them anywhere except into this function.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel

from src.services.enumeration.schema_enumerator import ColumnSchema

DEFAULT_MAX_PATTERNS = 5

_DIGIT_CLASS = "D"
_ALPHA_CLASS = "A"
_OTHER_CLASS = "X"
_STRUCTURAL_CHARS = set("-/_.:@,() ")


class MaskedColumnProfile(BaseModel):
    """The complete, safe payload for one column's LLM-assisted pass
    (research.md §3) — column name, type, and cardinality ratio are
    already non-sensitive schema metadata; length/pattern fields are
    derived from raw values but contain no literal value fragment."""

    model_config = {"frozen": True}

    column_name: str
    data_type: str
    cardinality_ratio: float
    min_length: int
    max_length: int
    avg_length: float
    pattern_classes: list[str]


def mask_column_profile(
    column: ColumnSchema,
    sample_values: Sequence[object],
    *,
    max_patterns: int = DEFAULT_MAX_PATTERNS,
) -> MaskedColumnProfile:
    """Summarize `sample_values` (raw, in-memory only for the duration of
    this call) into a `MaskedColumnProfile` safe to send to an LLM."""
    lengths = [len(str(value)) for value in sample_values if value is not None]
    if lengths:
        min_length, max_length = min(lengths), max(lengths)
        avg_length = sum(lengths) / len(lengths)
    else:
        min_length = max_length = 0
        avg_length = 0.0

    pattern_counts = Counter(
        _generalize_value(str(value)) for value in sample_values if value is not None
    )
    top_patterns = [pattern for pattern, _count in pattern_counts.most_common(max_patterns)]

    return MaskedColumnProfile(
        column_name=column.column_name,
        data_type=column.data_type,
        cardinality_ratio=column.cardinality_ratio,
        min_length=min_length,
        max_length=max_length,
        avg_length=avg_length,
        pattern_classes=top_patterns,
    )


def _generalize_value(value: str) -> str:
    """Collapse `value` into a regex-like pattern describing character
    classes and run-lengths only — never a literal digit or letter
    (research.md §3)."""
    if not value:
        return ""
    runs: list[tuple[str, int]] = []
    for char in value:
        char_class = _char_class(char)
        if runs and runs[-1][0] == char_class:
            runs[-1] = (char_class, runs[-1][1] + 1)
        else:
            runs.append((char_class, 1))
    return "".join(_render_run(char_class, length) for char_class, length in runs)


def _char_class(char: str) -> str:
    if char in _STRUCTURAL_CHARS:
        return char
    if char.isdigit():
        return _DIGIT_CLASS
    if char.isalpha():
        return _ALPHA_CLASS
    return _OTHER_CLASS


def _render_run(char_class: str, length: int) -> str:
    if char_class == _DIGIT_CLASS:
        token = r"\d"
    elif char_class == _ALPHA_CLASS:
        token = "[A-Za-z]"
    elif char_class == _OTHER_CLASS:
        token = "."
    else:
        return char_class * length  # structural separator/whitespace, preserved literally
    return f"{token}{{{length}}}" if length > 1 else token
