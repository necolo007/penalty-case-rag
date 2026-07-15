"""标签映射单测。"""

from engine.classification.competition_label_map import (
    cn_tags_to_competition_ids,
    format_submission_risk_type,
    predict_cn_tags_by_keywords,
)


def test_cn_tags_map_to_r_codes():
    assert cn_tags_to_competition_ids(["合同外利益", "赠送利益"]) == ["R002"]
    assert "R001" in cn_tags_to_competition_ids(["销售误导", "承诺收益"])


def test_submission_risk_type_uses_cn_semicolon():
    text = format_submission_risk_type(cn_tags=["合同外利益", "销售误导"])
    assert text == "合同外利益；销售误导"


def test_keyword_predict_gift_card():
    tags = predict_cn_tags_by_keywords("购买本产品即可领取价值1000元体检卡")
    assert "合同外利益" in tags or "赠送利益" in tags
