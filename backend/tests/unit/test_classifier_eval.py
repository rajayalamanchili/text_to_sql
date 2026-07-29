from eval.classifier_eval import (
    GROUND_TRUTH_DIR,
    GroundTruthRow,
    _print_report,
    load_ground_truth,
    score,
)
from src.models.column_classification import Classification


def _row(table: str, column: str, expected: Classification) -> GroundTruthRow:
    return GroundTruthRow(table_name=table, column_name=column, expected_classification=expected)


def test_score_counts_true_positive():
    ground_truth = [_row("patients", "patient_ssn", Classification.PII_DIRECT)]
    predictions = {("patients", "patient_ssn"): Classification.PII_DIRECT}

    metrics, missing = score(ground_truth, predictions)

    assert missing == []
    pii_direct = metrics[Classification.PII_DIRECT]
    assert pii_direct.true_positives == 1
    assert pii_direct.false_positives == 0
    assert pii_direct.false_negatives == 0
    assert pii_direct.precision == 1.0
    assert pii_direct.recall == 1.0


def test_score_counts_false_negative_and_false_positive():
    # Ground truth says pii_direct, classifier predicted business instead.
    ground_truth = [_row("patients", "first_name", Classification.PII_DIRECT)]
    predictions = {("patients", "first_name"): Classification.BUSINESS}

    metrics, _missing = score(ground_truth, predictions)

    assert metrics[Classification.PII_DIRECT].false_negatives == 1
    assert metrics[Classification.PII_DIRECT].true_positives == 0
    assert metrics[Classification.BUSINESS].false_positives == 1


def test_score_reports_missing_columns_without_crashing():
    ground_truth = [_row("patients", "does_not_exist", Classification.BUSINESS)]

    metrics, missing = score(ground_truth, predictions={})

    assert missing == ["patients.does_not_exist"]
    assert all(m.true_positives == 0 for m in metrics.values())


def test_precision_and_recall_are_none_with_zero_denominator():
    metrics, _missing = score(ground_truth=[], predictions={})

    pii_direct = metrics[Classification.PII_DIRECT]
    assert pii_direct.precision is None
    assert pii_direct.recall is None


def test_precision_recall_math_with_mixed_outcomes():
    # 2 correct pii_direct, 1 false positive (predicted pii_direct, was
    # actually business), 1 false negative (predicted business, was
    # actually pii_direct) -> precision = 2/3, recall = 2/3.
    ground_truth = [
        _row("t", "a", Classification.PII_DIRECT),
        _row("t", "b", Classification.PII_DIRECT),
        _row("t", "c", Classification.BUSINESS),
        _row("t", "d", Classification.PII_DIRECT),
    ]
    predictions = {
        ("t", "a"): Classification.PII_DIRECT,
        ("t", "b"): Classification.PII_DIRECT,
        ("t", "c"): Classification.PII_DIRECT,
        ("t", "d"): Classification.BUSINESS,
    }

    metrics, _missing = score(ground_truth, predictions)

    pii_direct = metrics[Classification.PII_DIRECT]
    assert pii_direct.true_positives == 2
    assert pii_direct.false_positives == 1
    assert pii_direct.false_negatives == 1
    assert pii_direct.precision == 2 / 3
    assert pii_direct.recall == 2 / 3


def test_print_report_gate_passes_at_or_above_target(capsys):
    # 9 correct pii_direct out of 10 -> precision=recall=0.9, both >= 0.85.
    ground_truth = [_row("t", f"col{i}", Classification.PII_DIRECT) for i in range(10)]
    predictions = {
        ("t", f"col{i}"): Classification.PII_DIRECT if i < 9 else Classification.BUSINESS
        for i in range(10)
    }
    metrics, _missing = score(ground_truth, predictions)

    passed = _print_report("healthcare", metrics)

    assert passed is True
    assert "PASS" in capsys.readouterr().out


def test_print_report_gate_fails_below_target(capsys):
    # 1 correct out of 4 -> recall=0.25, well below 0.85.
    ground_truth = [_row("t", f"col{i}", Classification.PII_DIRECT) for i in range(4)]
    predictions = {
        ("t", f"col{i}"): (Classification.PII_DIRECT if i == 0 else Classification.BUSINESS)
        for i in range(4)
    }
    metrics, _missing = score(ground_truth, predictions)

    passed = _print_report("healthcare", metrics)

    assert passed is False
    assert "FAIL" in capsys.readouterr().out


def test_print_report_gate_fails_when_no_pii_direct_examples_present(capsys):
    # Zero-denominator precision/recall (None) must not be treated as a pass.
    ground_truth = [_row("t", "a", Classification.BUSINESS)]
    predictions = {("t", "a"): Classification.BUSINESS}
    metrics, _missing = score(ground_truth, predictions)

    passed = _print_report("healthcare", metrics)

    assert passed is False


def test_real_ground_truth_files_load_and_have_pii_direct_examples():
    for domain in ("healthcare", "fintech"):
        rows = load_ground_truth(GROUND_TRUTH_DIR / f"{domain}.csv")
        assert 20 <= len(rows) <= 32
        pii_direct_rows = [
            r for r in rows if r.expected_classification == Classification.PII_DIRECT
        ]
        assert len(pii_direct_rows) >= 2, f"{domain} needs pii_direct examples for the eval gate"
