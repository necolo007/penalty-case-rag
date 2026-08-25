from engine.classification.tag_mapper import (
    map_internal_to_competition,
    to_submission_risk_types,
)


def test_internal_to_competition_mapping():
    assert map_internal_to_competition("R002-01-01") == "R002"
    assert map_internal_to_competition("R001") == "R001"
    assert map_internal_to_competition("X999") == ""


def test_submission_risk_types_joined_with_chinese_semicolon():
    result = to_submission_risk_types(["R002-01-01", "R001-01", "R002"])
    assert result == "欺骗投保人/销售误导；给予保险合同约定以外利益"


def test_retrieval_metrics_recall_mrr_ndcg():
    import sys
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from eval_metrics import compute_retrieval_metrics, mrr, recall_at_k

    gold = [
        {
            "question_id": "Q1",
            "relevant_cases": [
                {"case_id": "C1", "relevance": "strong"},
                {"case_id": "C2", "relevance": "medium"},
            ],
        },
    ]
    submission = [
        {
            "question_id": "Q1",
            "retrieved_cases": [
                {"case_id": "C9", "rank": 1},
                {"case_id": "C1", "rank": 2},
                {"case_id": "C2", "rank": 3},
            ],
        },
    ]
    out = compute_retrieval_metrics(submission, gold, k_values=[3, 5])
    assert out["evaluated"] == 1
    assert out["mrr"] == 0.5
    assert out["top1_hit"] == 0.0
    assert out["recall@3"] == 1.0
    assert "precision@3" not in out
    assert recall_at_k(["C1", "C2", "C3"], {"C1", "C2"}, 3) == 1.0
    assert mrr(["C1"], {"C1"}) == 1.0
def test_judge_retrieval_metrics_from_binary_scores():
    import sys
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from eval_metrics import compute_judge_retrieval_metrics

    per_query = [
        {
            "question_id": "Q1",
            "judgements": [
                {"case_id": "C1", "score": 0},
                {"case_id": "C2", "score": 1},
                {"case_id": "C3", "score": 1},
            ],
        },
    ]
    out = compute_judge_retrieval_metrics(per_query, k_values=[3])
    assert out["top1_hit"] == 0.0
    assert out["mrr"] == 0.5
    assert out["recall@3"] == 1.0
    assert "precision@3" not in out
