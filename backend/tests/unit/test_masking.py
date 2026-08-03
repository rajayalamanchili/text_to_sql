from src.services.classification.masking import mask_column_profile
from src.services.enumeration.schema_enumerator import ColumnSchema


def _column(name: str = "member_ssn", data_type: str = "text") -> ColumnSchema:
    return ColumnSchema(column_name=name, data_type=data_type, cardinality_ratio=0.99)


def test_ssn_like_values_generalize_to_digit_dash_pattern():
    profile = mask_column_profile(_column(), ["123-45-6789", "987-65-4321"])

    assert profile.pattern_classes == [r"\d{3}-\d{2}-\d{4}"]
    assert profile.min_length == 11
    assert profile.max_length == 11
    assert profile.avg_length == 11


def test_no_raw_value_fragment_ever_appears_in_output():
    raw_values = ["123-45-6789", "hunter2secret", "alice@example.com"]

    profile = mask_column_profile(_column("password_hint", "text"), raw_values)

    dumped = profile.model_dump_json()
    for raw in raw_values:
        assert raw not in dumped
    # No individual digit sequence longer than the generalized \d{n} token
    # syntax itself should appear either.
    assert "123" not in dumped
    assert "456789" not in dumped
    assert "hunter2secret" not in dumped


def test_empty_sample_values_do_not_error():
    profile = mask_column_profile(_column(), [])

    assert profile.min_length == 0
    assert profile.max_length == 0
    assert profile.avg_length == 0.0
    assert profile.pattern_classes == []


def test_max_patterns_caps_returned_pattern_count():
    values = [f"item-{i}" for i in range(20)]  # many distinct lengths -> many patterns

    profile = mask_column_profile(_column("sku", "text"), values, max_patterns=3)

    assert len(profile.pattern_classes) <= 3


def test_non_string_sample_values_are_coerced_safely():
    profile = mask_column_profile(_column("amount", "numeric"), [123, 4567, None])

    assert profile.min_length == 3
    assert profile.max_length == 4
    assert profile.pattern_classes == [r"\d{3}", r"\d{4}"] or set(profile.pattern_classes) == {
        r"\d{3}",
        r"\d{4}",
    }


def test_schema_metadata_carried_through_from_column():
    profile = mask_column_profile(_column("member_ssn", "text"), ["123-45-6789"])

    assert profile.column_name == "member_ssn"
    assert profile.data_type == "text"
    assert profile.cardinality_ratio == 0.99
