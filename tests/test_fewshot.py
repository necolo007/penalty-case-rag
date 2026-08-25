"""动态 few-shot 示例库：检索、去冗余、长尾配额与 Prompt 注入。"""

import json

import pytest

from engine.classification.fewshot import (
    FewShotBank,
    FewShotExample,
    char_ngrams,
    format_fewshot_block,
    normalize_for_match,
)
from engine.classification.risk_tagger import build_cn_tag_user_prompt


def _ex(example_id, text, tags, *, typicality=1.0, note="", case_id=None):
    return FewShotExample(
        example_id=example_id,
        violation_behavior=text,
        risk_tags=tuple(tags),
        case_id=case_id if case_id is not None else example_id,
        typicality=typicality,
        note=note,
    )


@pytest.fixture
def bank():
    return FewShotBank([
        _ex(
            "C001",
            "2015年开展电话销售业务中，销售人员以即将停售为由宣传实际并未停售的产品，"
            "并夸大产品收益，涉及保单25笔，实收保费26.01万元。",
            ["欺骗投保人", "夸大收益", "电销违规", "诱导投保"],
        ),
        _ex(
            "C002",
            "电销人员在销售过程中夸大保险责任、以即将停售为由宣传实际并未停售的产品，"
            "欺骗投保人，涉及保单8笔，实收保费7.26万元。",
            ["欺骗投保人", "夸大收益", "电销违规", "诱导投保"],
        ),
        _ex(
            "C003",
            "2017年3月开展车险营销活动，向投保客户赠送国通储油卡，"
            "承保家用车商业车险合计4605笔，赠送油卡金额合计6460550元。",
            ["合同外利益", "赠送利益"],
        ),
        _ex(
            "C004",
            "2013年9月至2014年8月，个险部在产品说明会上仅按中档红利演示预期收益，"
            "并将金账户收益同余额宝、银行利息比较，承诺保证10年6%的收益。",
            ["产品说明会违规", "不当比较", "承诺收益", "保证收益"],
        ),
        _ex(
            "C005",
            "回访过程中诱导投保人对回访问题作肯定回答，未确认犹豫期与退保损失等关键事项。",
            ["回访违规"],
            note="原文未出现「回访违规」字样，依据具体事实判定",
        ),
    ], name="test-bank")


def test_normalize_for_match_folds_numbers():
    assert normalize_for_match("涉及保单25笔，保费26.01万元") == "涉及保单#笔保费#万元"


def test_char_ngrams_skips_boilerplate_grams():
    grams = char_ngrams("你公司存在欺骗投保人的违法行为")
    assert "存在" not in grams
    assert "欺骗" in grams


def test_search_ranks_similar_example_first(bank):
    hits = bank.search("电话销售中以停售为由宣传并夸大收益，欺骗投保人", top_n=2)
    assert hits
    assert hits[0].example.example_id in {"C001", "C002"}
    assert "电销违规" in hits[0].example.risk_tags


def test_search_excludes_self_case(bank):
    text = bank.examples[0].violation_behavior
    hits = bank.search(text, top_n=3, exclude_case_ids=["C001"])
    assert all(h.example.case_id != "C001" for h in hits)


def test_search_drops_near_identical_self_match(bank):
    """待判事实与示例几乎同文时该示例被剔除，避免离线指标虚高。"""
    text = bank.examples[2].violation_behavior
    hits = bank.search(text, top_n=3, max_self_similarity=0.9)
    assert all(h.example.case_id != "C003" for h in hits)


def test_mmr_avoids_returning_two_near_duplicates(bank):
    """C001/C002 内容高度重复：低 lambda 时不应同时入选。"""
    hits = bank.search(
        "电话销售中以停售为由宣传并夸大收益，欺骗投保人", top_n=2, mmr_lambda=0.2
    )
    ids = {h.example.example_id for h in hits}
    assert not {"C001", "C002"} <= ids


def test_tag_quota_backfills_tail_label(bank):
    """长尾标签命中关键词但未被相似检索覆盖时，配额补位注入示例。"""
    hits = bank.search(
        "营销活动向投保客户赠送加油卡", top_n=2, tag_hints=["赠送利益", "回访违规"]
    )
    quota = [h for h in hits if h.reason == "tag_quota"]
    assert any("回访违规" in h.example.risk_tags for h in quota)


def test_search_returns_empty_for_blank_query(bank):
    assert bank.search("   ", top_n=3) == []


def test_stats_reports_tag_coverage(bank):
    stats = bank.stats()
    assert stats["examples"] == 5
    assert stats["per_tag"]["回访违规"] == 1
    assert "培训材料违规" in stats["tags_missing"]
    assert stats["dense_channel"] is False


def test_format_block_includes_tags_and_note(bank):
    hits = bank.search("回访中诱导投保人对回访问题作肯定回答", top_n=1)
    block = format_fewshot_block(hits)
    assert "正确标签：回访违规" in block
    assert "判定要点：" in block


def test_format_block_respects_max_chars(bank):
    hits = bank.search("电话销售夸大收益", top_n=4)
    block = format_fewshot_block(hits, max_chars=120, max_behavior_chars=40)
    assert block.count("[例") == 1


def test_format_block_empty_for_no_hits():
    assert format_fewshot_block([]) == ""


def test_from_jsonl_skips_invalid_rows(tmp_path):
    path = tmp_path / "bank.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"case_id": "A1", "violation_behavior": "赠送油卡",
                        "risk_tags": ["赠送利益"]}, ensure_ascii=False),
            json.dumps({"case_id": "A2", "violation_behavior": "", "risk_tags": ["赠送利益"]}),
            json.dumps({"case_id": "A3", "violation_behavior": "无标签", "risk_tags": []}),
            json.dumps({"case_id": "A1", "violation_behavior": "重复 id",
                        "risk_tags": ["赠送利益"]}, ensure_ascii=False),
        ]),
        encoding="utf-8",
    )
    loaded = FewShotBank.from_jsonl(path)
    assert [e.example_id for e in loaded.examples] == ["A1"]


def test_from_jsonl_rejects_empty_bank(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError):
        FewShotBank.from_jsonl(path)


def test_user_prompt_injects_examples_and_discipline(bank):
    prompt = build_cn_tag_user_prompt(
        "电话销售中以停售为由宣传并夸大收益", fewshot=True, fewshot_bank=bank
    )
    assert "相似判例参考" in prompt
    assert "示例使用纪律" in prompt
    assert "[例1]" in prompt


def test_bare_system_prompt_has_no_tag_rules():
    from engine.classification.risk_tagger import build_cn_tag_system_prompt

    bare = build_cn_tag_system_prompt(prompt_style="bare")
    full = build_cn_tag_system_prompt(prompt_style="full")
    assert "可选标签" in bare
    assert "标签规则" not in bare
    assert "虚列费用套取资金" in bare
    assert "标签规则" in full
    assert len(full) > len(bare)

    prompt = build_cn_tag_user_prompt(
        "电话销售中以停售为由宣传并夸大收益", fewshot=False, fewshot_bank=bank
    )
    assert "相似判例参考" not in prompt
    assert "违法违规行为" in prompt
    assert "标签消歧" not in prompt
    assert "可选风险标签" not in prompt


def test_fixed_fewshot_always_injects_same_examples(bank):
    from engine.classification.fewshot import retrieve_fixed_fewshot_hits

    hits = retrieve_fixed_fewshot_hits(bank=bank, fixed_ids="C003,C005")
    assert [h.example.example_id for h in hits] == ["C003", "C005"]
    assert all(h.reason == "fixed" for h in hits)

    p1 = build_cn_tag_user_prompt(
        "任意无关文本AAA",
        fewshot=True,
        fewshot_bank=bank,
        fewshot_mode="fixed",
        fewshot_fixed_ids="C003,C005",
    )
    p2 = build_cn_tag_user_prompt(
        "另一段无关文本BBB赠送油卡",
        fewshot=True,
        fewshot_bank=bank,
        fewshot_mode="fixed",
        fewshot_fixed_ids="C003,C005",
    )
    assert "相似判例参考" in p1
    assert "赠送国通储油卡" in p1 and "回访过程中诱导" in p1
    # 固定模式下两案注入内容一致（待判正文除外）
    assert p1.split("违法违规行为：")[0] == p2.split("违法违规行为：")[0]


def test_fewshot_gate_skips_when_hints_only_outside_bank(monkeypatch):
    """库外长尾初判 → 不注入 few-shot，走纯静态消歧。"""
    from engine.classification import fewshot as fs

    # 银行只覆盖「虚列费用套取资金」
    thin = FewShotBank([
        _ex("C100", "通过宣传费科目虚列费用用于补贴车险市场费用共计77万元。", ["虚列费用套取资金"]),
    ], name="thin")

    monkeypatch.setattr(fs, "fewshot_gate_allows", fs.fewshot_gate_allows)
    # 避债避税不在库内；关键词应能命中
    prompt = build_cn_tag_user_prompt(
        "这个保险产品能避债避税，合理合法，换个地方存钱。",
        fewshot=True,
        fewshot_bank=thin,
    )
    assert "相似判例参考" not in prompt


def test_fewshot_gate_allows_when_hint_covered(bank):
    prompt = build_cn_tag_user_prompt(
        "向购买车险的客户赠送加油卡和洗车券",
        fewshot=True,
        fewshot_bank=bank,
    )
    # 合同外利益/赠送利益在 bank 中有示例
    assert "相似判例参考" in prompt
