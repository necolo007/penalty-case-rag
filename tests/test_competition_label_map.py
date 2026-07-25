"""标签映射单测。"""

from engine.classification.competition_label_map import (
    cn_tags_to_competition_ids,
    format_cn_tag_guide_for_prompt,
    format_submission_risk_type,
    load_cn_tag_catalog,
    normalize_cn_tags,
    predict_cn_tags_by_keywords,
    resolve_final_cn_tags,
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


def test_normalize_aliases_from_competition_doc():
    assert normalize_cn_tags(["给予保险合同约定以外利益"]) == ["合同外利益"]
    assert "夸大收益" in normalize_cn_tags(["销售误导/夸大收益"])
    assert "销售误导" in normalize_cn_tags(["销售误导/夸大收益"])


def test_resolve_final_prefers_cn_over_r_codes():
    tags = resolve_final_cn_tags(
        query_text="投保可获加油卡补贴",
        keyword_tags=["合同外利益"],
        competition_ids=["R001", "R002"],
    )
    assert tags[0] == "合同外利益"
    assert "R001" not in tags


def test_format_submission_never_emits_r_codes():
    text = format_submission_risk_type(competition_ids=["R001", "R002"])
    assert "R001" not in text
    assert "；" in text or text in {"销售误导", "合同外利益"}


def test_catalog_loads_enriched_fields():
    catalog = load_cn_tag_catalog()
    assert len(catalog) >= 27
    by_tag = {r["risk_tag"]: r for r in catalog}
    assert by_tag["夸大收益"].get("typical_behavior")
    assert by_tag["夸大收益"].get("exclusion_boundary")
    assert "承诺收益" in by_tag["夸大收益"]["exclusion_boundary"]


def test_exclusion_boundary_prefers_promise_over_exaggerate():
    # 「保证/承诺」触发排除边界：夸大收益 → 归入承诺收益
    tags = predict_cn_tags_by_keywords("本产品保证收益，买了肯定不亏，稳赚")
    assert "承诺收益" in tags or "保证收益" in tags


def test_tag_guide_includes_disambiguation():
    guide = format_cn_tag_guide_for_prompt()
    assert "夸大收益" in guide
    assert "承诺收益" in guide or "排除" in guide or "归入" in guide
