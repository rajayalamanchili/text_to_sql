from src.models.column_classification import Classification
from src.services.classification.heuristic_classifier import (
    MAX_HEURISTIC_CONFIDENCE,
    classify_heuristically,
)
from src.services.enumeration.schema_enumerator import ColumnSchema


def _column(name: str, data_type: str = "text", cardinality_ratio: float = 0.5) -> ColumnSchema:
    return ColumnSchema(column_name=name, data_type=data_type, cardinality_ratio=cardinality_ratio)


def test_scenario1_patient_ssn_is_pii_direct_high_confidence():
    result = classify_heuristically(_column("patient_ssn", "text", cardinality_ratio=0.99))

    assert result.classification == Classification.PII_DIRECT
    assert result.score >= 0.9
    assert result.score <= MAX_HEURISTIC_CONFIDENCE


def test_scenario3_patient_notes_free_text_never_business():
    # Free-text narrative is also near-unique, like an SSN column — the
    # name pattern (not cardinality alone) is what must disambiguate them.
    result = classify_heuristically(_column("patient_notes", "text", cardinality_ratio=0.95))

    assert result.classification != Classification.BUSINESS
    assert result.classification == Classification.SENSITIVE_CATEGORY
    assert result.score <= 0.6


def test_scenario2_low_cardinality_unmatched_text_stays_below_auto_approval():
    result = classify_heuristically(_column("notes", "text", cardinality_ratio=0.05))

    assert result.classification != Classification.BUSINESS
    assert result.score < 0.85


def test_email_column_is_pii_indirect():
    result = classify_heuristically(_column("email_address", "text", cardinality_ratio=0.9))

    assert result.classification == Classification.PII_INDIRECT


def test_diagnosis_code_is_sensitive_category():
    result = classify_heuristically(_column("diagnosis_code", "text", cardinality_ratio=0.2))

    assert result.classification == Classification.SENSITIVE_CATEGORY


def test_numeric_column_with_no_name_signal_defaults_business_below_auto_approval():
    result = classify_heuristically(_column("row_sequence", "integer", cardinality_ratio=1.0))

    assert result.classification == Classification.BUSINESS
    assert result.score < 0.85


def test_score_never_exceeds_global_cap():
    result = classify_heuristically(_column("ssn", "text", cardinality_ratio=1.0))

    assert result.score <= MAX_HEURISTIC_CONFIDENCE
