"""OCR 逐字重复归一与抽取回归。"""

from pipeline.extraction.extractor import ExtractorEngine
from pipeline.parser.base import ParseResult
from pipeline.parser.ocr_normalize import normalize_ocr_text

SAMPLE_DOUBLED_OCR = """《北京银保监局行政处罚信息公开表》-(京银保监罚决字〔2023〕15号)
北京银保监局行政处罚信息公开表
(人保财险北京市宣武支公司,刘文新)
行行政政处处罚罚决决定定书书文文号号 京银保监罚决字〔2023〕15号
个人姓名 刘文新
被被处处罚罚当当 中国人民财产保险股份有限公司北京
名称
事事人人 单 市宣武支公司
位
主要负责人 刘文新
1.未如实记录业务及管理费;
主主要要违违法法违违规规事事实实(案案由由)
2.给予投保人合同约定以外的利益。
《中华人民共和国保险法》第一百六
行行政政处处罚罚依依据据 十一条、第一百七十条、第一百七十
一条。
责令人保财险北京市宣武支公司改正,
行行政政处处罚罚决决定定 给予罚款合计65万元;
给予刘文新警告并罚款16万元。
作作出出处处罚罚决决定定的的机机关关名名称称
北京银保监局
作作出出处处罚罚决决定定的的日日期期 2023年5月24日
"""


def test_collapse_doubled_cjk_labels():
    out = normalize_ocr_text(SAMPLE_DOUBLED_OCR)
    assert "行政处罚决定书文号" in out
    assert "行行政政" not in out
    assert "主要违法违规事实(案由)" in out
    assert "行政处罚依据" in out
    assert "作出处罚决定的机关名称" in out
    assert "被处罚当事人" in out
    assert "中国人民财产保险股份有限公司北京市宣武支公司" in out


def test_normalize_is_idempotent_on_clean_text():
    clean = """行政处罚决定书
鲁金罚决字〔2026〕16号
当事人：华泰人寿保险股份有限公司山东分公司
主要违法违规事实：给予投保人保险合同约定以外的其他利益
"""
    once = normalize_ocr_text(clean)
    twice = normalize_ocr_text(once)
    assert once == twice
    assert "华泰人寿保险股份有限公司山东分公司" in once


def test_extract_from_doubled_ocr_publicity_table():
    engine = ExtractorEngine(llm_client=None, use_llm_refine=False)
    cases = engine.extract(
        ParseResult(success=True, markdown=SAMPLE_DOUBLED_OCR, confidence=0.6),
        file_id="F_OCR_DUP",
        source_file="京银保监罚决字2023_15.pdf",
    )
    assert len(cases) == 1
    case = cases[0]
    assert case.penalty_doc_no == "京银保监罚决字〔2023〕15号"
    assert "中国人民财产保险股份有限公司北京市宣武支公司" in case.party_name
    assert "未如实记录" in (case.violation_behavior or "") or "合同约定以外" in (
        case.violation_behavior or ""
    )
    assert "65" in (case.penalty_content or "") or "65" in (case.fine_amount or "")
    assert "北京银保监局" in (case.regulator or "")
    assert case.fine_amount and "65" in case.fine_amount
