import re

from engine.review.risk_locator import is_non_risk_boilerplate
from engine.review.risk_rules import match_risk_rules
from engine.review.segmenter import segment_text


def test_high_risk_pattern_gift_card():
    hits = match_risk_rules("投保本产品即可获得加油卡补贴")
    assert hits
    assert any(h.risk_type_id == "R002" and h.severity == "high" for h in hits)


def test_medium_upgraded_in_strict_scene():
    sentence = "本产品年化收益率最高可达6%"
    normal = match_risk_rules(sentence)
    strict = match_risk_rules(sentence, scene="营销宣传材料/销售话术审核")
    assert any(h.severity == "medium" for h in normal)
    assert any(h.severity == "high" for h in strict)


def test_no_hit_for_clean_sentence():
    assert match_risk_rules("本产品提供重大疾病保障，详见条款说明") == []


def test_skip_legal_citation_boilerplate():
    cite = "上述行为违反了《中华人民共和国保险法》(2015年修正)第八十六条的规定。"
    assert is_non_risk_boilerplate(cite)
    assert is_non_risk_boilerplate("依据《保险法》第一百七十条的规定，决定如下：")
    assert not is_non_risk_boilerplate(
        "存在虚列费用的问题，套取的资金实际用于支付手续费和业务推动。"
    )


def _span_flat(text: str, start: int, end: int) -> str:
    return re.sub(r"[\r\n]+", "", text[start:end]).strip()


def test_segmenter_positions():
    text = "第一句。第二句！\n\n第二段的句子。"
    sentences = segment_text(text)
    assert len(sentences) == 3
    for s in sentences:
        assert _span_flat(text, s.start, s.end) == s.text
    assert sentences[0].paragraph_idx == 0
    assert sentences[2].paragraph_idx == 1


def test_segmenter_skips_blank_lines():
    sentences = segment_text("\n\n只有一句话。\n\n")
    assert len(sentences) == 1


def test_segmenter_joins_soft_line_breaks():
    """同一句因排版跨行时，应拼成完整风险句而非半截。"""
    text = (
        "经查,永诚财险蚌埠中支存在虚列费用的问题,套取的资金实际\n"
        "用于支付手续费和业务推动。上述行为违反了《中华人民\n"
        "共和国保险法》(2015年修正)第八十六条的规定。"
    )
    sentences = segment_text(text)
    assert len(sentences) == 2
    assert "套取的资金实际用于支付手续费" in sentences[0].text
    assert "\n" not in sentences[0].text
    assert sentences[1].text.startswith("上述行为违反了《中华人民共和国保险法》")
    assert "第八十六条的规定。" in sentences[1].text
    for s in sentences:
        assert _span_flat(text, s.start, s.end) == s.text


def test_segmenter_keeps_list_items_apart():
    text = "主要违法事实：\n1. 虚列费用套取资金\n2. 给予合同约定以外的利益"
    sentences = segment_text(text)
    texts = [s.text for s in sentences]
    assert any("主要违法事实" in t for t in texts)
    assert any(t.startswith("1.") for t in texts)
    assert any(t.startswith("2.") for t in texts)
