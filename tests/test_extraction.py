from pipeline.extraction.extractor import ExtractorEngine
from pipeline.extraction.schema import InstitutionType
from pipeline.parser.base import ParseResult

SAMPLE_DECISION_TEXT = """行政处罚决定书
鲁金罚决字〔2026〕16号
当事人：华泰人寿保险股份有限公司山东分公司
主要违法违规事实：给予投保人保险合同约定以外的其他利益
行政处罚内容：罚款人民币11.5万元
作出处罚决定的机关名称：国家金融监督管理总局山东监管局
依据《中华人民共和国保险法》第一百六十一条规定
2026年3月3日
"""


def make_engine() -> ExtractorEngine:
    return ExtractorEngine(llm_client=None, use_llm_refine=False)


def test_regex_extraction_from_decision_doc():
    engine = make_engine()
    parse_result = ParseResult(success=True, markdown=SAMPLE_DECISION_TEXT, confidence=0.9)
    cases = engine.extract(parse_result, file_id="F000001", source_file="test.pdf")

    assert len(cases) == 1
    case = cases[0]
    assert case.penalty_doc_no == "鲁金罚决字〔2026〕16号"
    assert "华泰人寿保险股份有限公司山东分公司" in case.party_name
    assert "给予投保人保险合同约定以外的其他利益" in case.violation_behavior
    assert case.fine_amount
    assert "山东监管局" in case.regulator
    assert case.publish_date == "2026-03-03"
    assert case.institution_type == InstitutionType.LIFE_INSURANCE
    assert case.overall_confidence >= 0.75


def test_table_record_extraction():
    engine = make_engine()
    records = [{
        "party_name": "某财产保险股份有限公司北京分公司",
        "penalty_doc_no": "京金罚决字〔2026〕8号",
        "violation_behavior": "编制虚假财务资料",
        "penalty_content": "罚款30万元",
        "regulator": "国家金融监督管理总局北京监管局",
        "publish_date": "2026年1月15日",
    }]
    parse_result = ParseResult(success=True, markdown="", confidence=0.9,
                               metadata={"records": records})
    cases = engine.extract(parse_result, file_id="F000002", source_file="table.pdf")

    assert len(cases) == 1
    case = cases[0]
    assert case.extraction_method == "table"
    assert case.publish_date == "2026-01-15"
    assert case.institution_type == InstitutionType.PROPERTY_INSURANCE


def test_empty_text_returns_no_cases():
    engine = make_engine()
    parse_result = ParseResult(success=True, markdown="   ", confidence=0.0)
    assert engine.extract(parse_result, file_id="F1", source_file="x.pdf") == []
