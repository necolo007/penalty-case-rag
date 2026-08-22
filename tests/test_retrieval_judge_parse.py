"""Judge 输出解析单测（无 LLM）。"""

from scripts.eval_retrieval_judge import _normalize_judgements, _parse_judge, _to_binary_score


def test_to_binary_score():
    assert _to_binary_score(1) == 1
    assert _to_binary_score(0) == 0
    assert _to_binary_score(2) == 1  # 兼容旧 0/1/2
    assert _to_binary_score(9) == 1


def test_parse_judge_json():
    raw = '{"judgements":[{"case_id":"C1","score":1,"reason":"ok"}],"best_case_id":"C1"}'
    data = _parse_judge(raw)
    assert data["best_case_id"] == "C1"
    out = _normalize_judgements(data, ["C1", "C2"])
    assert out[0]["score"] == 1
    assert out[1]["score"] == 0


def test_parse_judge_legacy_score2_maps_to_relevant():
    data = {"judgements": [{"case_id": "C1", "score": 2}]}
    out = _normalize_judgements(data, ["C1"])
    assert out[0]["score"] == 1
