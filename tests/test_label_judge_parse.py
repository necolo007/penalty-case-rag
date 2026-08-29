"""Label Judge 输出解析与指标单测（无 LLM）。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from eval_metrics import compute_label_judge_metrics
from eval_label_judge import (
    _normalize_tag_judgements,
    _parse_label_judge,
    _to_binary_score,
)


def test_to_binary_score():
    assert _to_binary_score(1) == 1
    assert _to_binary_score(0) == 0
    assert _to_binary_score(2) == 1


def test_parse_label_judge_json():
    raw = (
        '{"pred_judgements":[{"tag":"电销违规","score":1}],'
        '"gold_coverage":[{"tag":"电销违规","score":1}],"case_note":"ok"}'
    )
    data = _parse_label_judge(raw)
    pred = _normalize_tag_judgements(data, ["电销违规", "销售误导"], "pred_judgements")
    assert pred[0]["score"] == 1
    assert pred[1]["score"] == 0


def test_compute_label_judge_metrics():
    per_case = [
        {
            "case_id": "C1",
            "judge_pred_precision": 1.0,
            "judge_gold_recall": 0.5,
            "judge_f1": 0.6667,
            "judge_full_accept": False,
        },
        {
            "case_id": "C2",
            "judge_pred_precision": 1.0,
            "judge_gold_recall": 1.0,
            "judge_f1": 1.0,
            "judge_full_accept": True,
        },
    ]
    out = compute_label_judge_metrics(per_case)
    assert out["evaluated"] == 2
    assert out["judge_pred_precision"] == 1.0
    assert out["judge_gold_recall"] == 0.75
    assert out["judge_full_accept_rate"] == 0.5
