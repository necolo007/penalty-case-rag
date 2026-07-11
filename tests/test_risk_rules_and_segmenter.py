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


def test_segmenter_positions():
    text = "第一句。第二句！\n第二段的句子。"
    sentences = segment_text(text)
    assert len(sentences) == 3
    for s in sentences:
        assert text[s.start:s.end].strip() == s.text
    assert sentences[0].paragraph_idx == 0
    assert sentences[2].paragraph_idx == 1


def test_segmenter_skips_blank_lines():
    sentences = segment_text("\n\n只有一句话。\n\n")
    assert len(sentences) == 1
