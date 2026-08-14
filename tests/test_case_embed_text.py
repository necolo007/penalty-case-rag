"""案例嵌入文本：违规行为 + 案件总结。"""

from engine.embedding.case_text import build_case_embed_text


def test_build_case_embed_text_both_fields():
    text = build_case_embed_text(
        violation_behavior="承诺保本保息",
        case_summary="某公司销售误导并被罚款",
    )
    assert text.startswith("违规行为：承诺保本保息")
    assert "案件总结：某公司销售误导并被罚款" in text
    assert "raw" not in text.lower()


def test_build_case_embed_text_vb_only():
    text = build_case_embed_text(violation_behavior="给予合同外利益", case_summary="")
    assert text == "违规行为：给予合同外利益"


def test_build_case_embed_text_empty_fallback():
    assert build_case_embed_text() == "保险监管处罚案例"
