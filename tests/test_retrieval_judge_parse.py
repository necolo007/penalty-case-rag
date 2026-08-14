"""Judge 输出解析单测（无 LLM）。"""

from scripts.eval_retrieval_judge import _normalize_judgements, _parse_judge


def test_parse_judge_json():
    raw = '{"judgements":[{"case_id":"C1","score":2,"same_risk_type":true,"reason":"ok"}],"best_case_id":"C1"}'
    data = _parse_judge(raw)
    assert data["best_case_id"] == "C1"
    out = _normalize_judgements(data, ["C1", "C2"])
    assert out[0]["score"] == 2
    assert out[1]["score"] == 0


def test_parse_judge_clamps_score():
    data = {"judgements": [{"case_id": "C1", "score": 9}]}
    out = _normalize_judgements(data, ["C1"])
    assert out[0]["score"] == 2
