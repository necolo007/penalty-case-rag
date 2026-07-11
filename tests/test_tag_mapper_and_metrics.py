from engine.classification.tag_mapper import (
    map_internal_to_competition,
    to_submission_risk_types,
)
from scripts.eval_metrics import compute_retrieval_metrics


def test_internal_to_competition_mapping():
    assert map_internal_to_competition("R002-01-01") == "R002"
    assert map_internal_to_competition("R001") == "R001"
    assert map_internal_to_competition("X999") == ""


def test_submission_risk_types_joined_with_chinese_semicolon():
    result = to_submission_risk_types(["R002-01-01", "R001-01", "R002"])
    assert result == "欺骗投保人/销售误导；给予保险合同约定以外利益"


def test_retrieval_metrics_perfect_hit():
    submission = [{
        "question_id": "QT001",
        "retrieved_cases": [{"case_id": "C001", "rank": 1}, {"case_id": "C002", "rank": 2}],
    }]
    gold = [{
        "question_id": "QT001",
        "relevant_cases": [{"case_id": "C001", "relevance": "strong"}],
    }]
    m = compute_retrieval_metrics(submission, gold, k_values=[5])
    assert m["evaluated"] == 1
    assert m["recall@5"] == 1.0
    assert m["mrr"] == 1.0
    assert m["top1_hit"] == 1.0
    assert m["ndcg@5"] == 1.0


def test_retrieval_metrics_miss():
    submission = [{"question_id": "QT001",
                   "retrieved_cases": [{"case_id": "C999", "rank": 1}]}]
    gold = [{"question_id": "QT001",
             "relevant_cases": [{"case_id": "C001", "relevance": "strong"}]}]
    m = compute_retrieval_metrics(submission, gold, k_values=[5])
    assert m["recall@5"] == 0.0
    assert m["mrr"] == 0.0


def test_retrieval_metrics_second_rank():
    submission = [{
        "question_id": "QT001",
        "retrieved_cases": [{"case_id": "C999", "rank": 1}, {"case_id": "C001", "rank": 2}],
    }]
    gold = [{"question_id": "QT001",
             "relevant_cases": [{"case_id": "C001", "relevance": "strong"}]}]
    m = compute_retrieval_metrics(submission, gold, k_values=[5])
    assert m["mrr"] == 0.5
    assert m["top1_hit"] == 0.0
    assert m["recall@5"] == 1.0
