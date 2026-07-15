"""eval_metrics 兼容官方嵌套 gold_answer。"""

from scripts.eval_metrics import compute_retrieval_metrics


def test_nested_gold_answer():
    submission = [{
        "question_id": "QT001",
        "retrieved_cases": [
            {"case_id": "C280", "rank": 1},
            {"case_id": "C001", "rank": 2},
        ],
    }]
    gold = [{
        "question_id": "QT001",
        "gold_answer": {
            "expected_risk_types": ["销售误导"],
            "relevant_cases": [{"case_id": "C280", "relevance": "strong"}],
        },
    }]
    metrics = compute_retrieval_metrics(submission, gold, k_values=[5])
    assert metrics["evaluated"] == 1
    assert metrics["top1_hit"] == 1.0
    assert metrics["mrr"] == 1.0
