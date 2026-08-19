"""标签映射单测。"""

from engine.classification.competition_label_map import (
    cn_tags_to_competition_ids,
    format_cn_tag_guide_for_prompt,
    format_submission_risk_type,
    load_cn_tag_catalog,
    normalize_cn_tags,
    predict_cn_tags_by_keywords,
    refine_cn_tags,
    resolve_final_cn_tags,
)


def test_cn_tags_map_to_r_codes():
    assert cn_tags_to_competition_ids(["合同外利益", "赠送利益"]) == ["R002"]
    assert "R001" in cn_tags_to_competition_ids(["销售误导", "承诺收益"])
    assert cn_tags_to_competition_ids(["虚列费用套取资金"]) == ["R005"]


def test_near_synonym_aliases():
    assert "隐瞒重要信息" in normalize_cn_tags(["隐藏重要信息"])
    assert "虚假宣传" in normalize_cn_tags(["夸大宣传"])
    assert "诱导投保" in normalize_cn_tags(["引诱投保"])
    assert "销售误导" in normalize_cn_tags(["误导"])
    tags = normalize_cn_tags(["夸大服务"])
    assert "夸大收益" in tags or "虚假宣传" in tags


def test_unknown_label_needs_review():
    from engine.classification.competition_label_map import normalize_cn_tags_detailed

    detailed = normalize_cn_tags_detailed(["完全不存在的标签XYZ"])
    assert detailed[0]["status"] == "needs_review"
    assert detailed[0]["normalized_label"] is None
    assert detailed[0]["raw_label"] == "完全不存在的标签XYZ"


def test_compliance_tags_not_forced_to_r006():
    """费率条款 / 客户信息不实 ≠ 编制虚假财务资料(R006)。"""
    assert cn_tags_to_competition_ids(["未按规定使用费率条款"]) == []
    assert cn_tags_to_competition_ids(["客户信息不真实"]) == []
    mixed = cn_tags_to_competition_ids(
        ["未按规定使用费率条款", "客户信息不真实", "虚列费用套取资金"]
    )
    assert mixed == ["R005"]
    assert "R006" not in mixed


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


def test_refine_does_not_stack_deceive_on_false_ads_alone():
    tags = refine_cn_tags(["虚假宣传", "虚列费用套取资金"], "宣传材料夸大保险责任，并虚列中介费用")
    assert "虚假宣传" in tags
    assert "欺骗投保人" not in tags


def test_refine_adds_absolute_and_parent_deceive():
    text = "产说会上宣称偿付能力充足率行业第一，此宣传与事实不符。"
    tags = refine_cn_tags(["产品说明会违规"], text)
    assert "绝对化表述" in tags
    assert "欺骗投保人" in tags


def test_refine_adds_fictive_yield():
    text = "电话销售时存在虚构、夸大分红水平的行为"
    tags = refine_cn_tags(["电销违规", "销售误导"], text)
    assert "虚构收益率" in tags
    assert "欺骗投保人" in tags


def test_refine_deceive_from_non_disclosure_duty():
    text = "诱导 投保人不履行保险法规定的如实告知义 务负有责任"
    tags = refine_cn_tags(["合同外利益", "回扣返佣", "诱导投保"], text)
    assert "欺骗投保人" in tags
    assert "合同外利益" in tags


def test_refine_drops_ungrounded_fictive_yield():
    text = "宣传材料将保险收益与银行存款比较，并承诺保本保息。"
    tags = refine_cn_tags(["虚假宣传", "承诺收益", "虚构收益率"], text)
    assert "虚构收益率" not in tags
    assert "承诺收益" in tags


def test_refine_telemarketing_drops_false_ads():
    text = "电话销售过程中对产品作虚假宣传"
    tags = refine_cn_tags(["虚假宣传", "电销违规"], text)
    assert "虚假宣传" not in tags
    assert "销售误导" in tags
    assert "电销违规" in tags


def test_refine_adds_induce_from_fake_stop_sale():
    text = "以即将停售为由宣传实际并未停售的产品，并夸大保险责任。"
    tags = refine_cn_tags(["欺骗投保人", "销售误导", "电销违规"], text)
    assert "诱导投保" in tags


def test_refine_person_unlicensed_is_agent_management():
    text = "委托无资格证书、执业证书人员从事保险销售，并向其发放佣金。"
    tags = refine_cn_tags(["委托无资质机构销售", "虚列费用套取资金"], text)
    assert "代理人管理不到位" in tags
    assert "委托无资质机构销售" not in tags


def test_refine_drops_ungrounded_weaken_risk():
    text = "产说会宣传分红不确定，未说明高中低档演示。"
    tags = refine_cn_tags(["销售误导", "弱化风险提示"], text)
    assert "弱化风险提示" not in tags


def test_refine_keeps_proxy_signature_as_fake_client_info():
    text = "银保渠道部分上门回访的书面回访函由银保客户经理代投保人签名。"
    tags = refine_cn_tags(["虚列费用套取资金"], text)
    assert "客户信息不真实" in tags


def test_refine_drops_ungrounded_fake_client_info():
    text = "农业保险自查报告显示问题档案占比偏高，与实际不一致。"
    tags = refine_cn_tags(["客户信息不真实"], text)
    assert "客户信息不真实" not in tags
