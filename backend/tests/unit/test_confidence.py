from src.models.column_classification import Classification, ClassificationSource
from src.services.classification.confidence import combine_confidence
from src.services.classification.heuristic_classifier import HeuristicResult
from src.services.classification.llm_classifier import LLMResult


def _heuristic(classification, score):
    return HeuristicResult(classification=classification, score=score, signal="test")


def _llm(classification, score):
    return LLMResult(classification=classification, score=score, rationale="test")


def test_llm_skipped_returns_heuristic_unchanged():
    heuristic = _heuristic(Classification.PII_DIRECT, 0.95)

    result = combine_confidence(heuristic, None)

    assert result.classification == Classification.PII_DIRECT
    assert result.confidence == 0.95
    assert result.source == ClassificationSource.HEURISTIC


def test_agreement_takes_max_confidence():
    heuristic = _heuristic(Classification.SENSITIVE_CATEGORY, 0.5)
    llm = _llm(Classification.SENSITIVE_CATEGORY, 0.8)

    result = combine_confidence(heuristic, llm)

    assert result.classification == Classification.SENSITIVE_CATEGORY
    assert result.confidence == 0.8
    assert result.source == ClassificationSource.LLM


def test_disagreement_more_sensitive_category_wins_with_min_confidence():
    heuristic = _heuristic(Classification.BUSINESS, 0.9)
    llm = _llm(Classification.PII_DIRECT, 0.3)

    result = combine_confidence(heuristic, llm)

    assert result.classification == Classification.PII_DIRECT
    assert result.confidence == 0.3
    assert result.source == ClassificationSource.LLM


def test_disagreement_heuristic_more_sensitive_wins_and_is_attributed_to_heuristic():
    heuristic = _heuristic(Classification.SENSITIVE_CATEGORY, 0.4)
    llm = _llm(Classification.BUSINESS, 0.9)

    result = combine_confidence(heuristic, llm)

    assert result.classification == Classification.SENSITIVE_CATEGORY
    assert result.confidence == 0.4
    assert result.source == ClassificationSource.HEURISTIC


def test_unclassified_llm_proposal_never_wins_over_real_heuristic_category():
    heuristic = _heuristic(Classification.PII_INDIRECT, 0.4)
    llm = _llm(Classification.UNCLASSIFIED, 0.9)

    result = combine_confidence(heuristic, llm)

    assert result.classification == Classification.PII_INDIRECT
    assert result.confidence == 0.4


def test_unclassified_heuristic_proposal_never_wins_over_real_llm_category():
    heuristic = _heuristic(Classification.UNCLASSIFIED, 0.9)
    llm = _llm(Classification.SENSITIVE_CATEGORY, 0.3)

    result = combine_confidence(heuristic, llm)

    assert result.classification == Classification.SENSITIVE_CATEGORY
    assert result.confidence == 0.3


def test_risk_order_full_ranking():
    order = [
        Classification.BUSINESS,
        Classification.PII_INDIRECT,
        Classification.SENSITIVE_CATEGORY,
        Classification.PII_DIRECT,
    ]
    for i in range(len(order) - 1):
        lower = _heuristic(order[i], 0.95)
        higher = _llm(order[i + 1], 0.05)

        result = combine_confidence(lower, higher)

        assert result.classification == order[i + 1], f"{order[i + 1]} should outrank {order[i]}"
