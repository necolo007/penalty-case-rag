import json

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

SAMPLE_BEI_PENALTY_UNIT = """中国银保监会广东监管局行政处罚决定书(北京联合保险经纪有限公司广东分公司)

粤银保监罚决字〔2019〕2号

被处罚单位名称:北京联合保险经纪有限公司广东分公司
地          址:广州市越秀区环市东路450号
主 要 负 责 人:梅兰香
经查,你公司存在财务数据不真实的行为。
"""

SAMPLE_NAME_LABEL = """行政处罚决定书
新保监罚〔2018〕23号
      名称:昌吉市庞大一众汽车销售服务有限公司
      营业地址:新疆昌吉市乌伊西路
      法定代表人:张久文
      经查,你公司存在给予投保人保险合同约定外利益的违法行为。
"""

SAMPLE_DUAL_PARTY = """浙保监罚[2007]2号
当事人:顾斌,男,汉族,1963年11月18日出生。
当事人:安邦财产保险股份有限公司台州中心支公司(以下简称安邦产险台州中支),住所的台州市鑫泰广场。
经查,安邦产险台州中支存在以下违法事实。
"""

SAMPLE_SHOU_PENALTY_REN_MINGCHENG = """中国保监会宁夏监管局行政处罚决定书
受处罚人名称:中国太平洋财产保险股份有限公司石嘴山中心支公司
地址:宁夏石嘴山市大武口区贺兰山北路152号
经查,你公司存在未严格执行报备的商业车险费率行为。
"""


def make_engine() -> ExtractorEngine:
    # 无 LLM 时无论 llm_first/regex_first 都走正则，保证离线单测稳定
    return ExtractorEngine(
        llm_client=None, use_llm_refine=False, extraction_mode="llm_first",
    )


class _FakeLLM:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def complete(self, prompt, **kwargs):
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


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


def test_bei_penalty_unit_label():
    """「被处罚单位名称」标签（非「受处罚」）应正确抽取。"""
    engine = make_engine()
    cases = engine.extract(
        ParseResult(success=True, markdown=SAMPLE_BEI_PENALTY_UNIT, confidence=0.9),
        file_id="F3", source_file="x.pdf",
    )
    assert cases
    assert cases[0].party_name == "北京联合保险经纪有限公司广东分公司"


def test_standalone_name_label():
    """决定书抬头「名称:XXX」应能抽取。"""
    engine = make_engine()
    cases = engine.extract(
        ParseResult(success=True, markdown=SAMPLE_NAME_LABEL, confidence=0.9),
        file_id="F4", source_file="x.pdf",
    )
    assert cases
    assert "庞大一众汽车销售服务有限公司" in cases[0].party_name


def test_prefer_institution_over_person():
    """一案两罚时优先机构当事人，而非责任人姓名。"""
    engine = make_engine()
    cases = engine.extract(
        ParseResult(success=True, markdown=SAMPLE_DUAL_PARTY, confidence=0.9),
        file_id="F5", source_file="x.pdf",
    )
    assert cases
    assert "安邦财产保险股份有限公司台州中心支公司" in cases[0].party_name
    assert "顾斌" not in cases[0].party_name


def test_shou_penalty_ren_mingcheng_not_prefix_capture():
    """「受处罚人名称:」不应被短标签「受处罚人」截成「名称:XXX」。"""
    engine = make_engine()
    cases = engine.extract(
        ParseResult(success=True, markdown=SAMPLE_SHOU_PENALTY_REN_MINGCHENG, confidence=0.9),
        file_id="F6", source_file="x.pdf",
    )
    assert cases
    assert cases[0].party_name == "中国太平洋财产保险股份有限公司石嘴山中心支公司"


def test_docno_prefix_not_split_into_empty_segment():
    """标题「重庆保监局渝保监罚…」与正文「渝保监罚…」应视为同一文号，不误拆。"""
    text = """重庆保监局渝保监罚〔2013〕46号(中国人寿重庆分公司)
中国保监会重庆监管局行政处罚决定书

渝保监罚〔2013〕46号

当事人:中国人寿保险股份有限公司重庆市分公司
住  所:重庆市渝中区民族路23号
主要负责人:周多光

经查实,中国人寿保险股份有限公司重庆市分公司存在欺骗投保人的行为。
"""
    engine = make_engine()
    cases = engine.extract(
        ParseResult(success=True, markdown=text, confidence=0.9),
        file_id="F7", source_file="x.pdf",
    )
    assert len(cases) == 1
    assert cases[0].party_name == "中国人寿保险股份有限公司重庆市分公司"


def test_llm_first_extraction_uses_prompt_fields():
    """llm_first：长文走提示词主抽，不再依赖正则命中主字段。"""
    fake = _FakeLLM({
        "party_name": "华泰人寿保险股份有限公司山东分公司",
        "institution_type": "寿险公司",
        "is_insurance_related": True,
        "penalty_doc_no": "鲁金罚决字〔2026〕16号",
        "violation_behavior": "给予投保人保险合同约定以外的其他利益",
        "penalty_content": "罚款人民币11.5万元",
        "regulator": "国家金融监督管理总局山东监管局",
        "case_summary": "华泰人寿山东分公司因合同外利益被罚11.5万元",
    })
    engine = ExtractorEngine(
        llm_client=fake, use_llm_refine=False, extraction_mode="llm_first",
    )
    cases = engine.extract(
        ParseResult(success=True, markdown=SAMPLE_DECISION_TEXT, confidence=0.9),
        file_id="F_LLM", source_file="x.pdf",
    )
    assert len(cases) == 1
    case = cases[0]
    assert case.extraction_method == "llm"
    assert fake.calls == 1
    assert case.party_name == "华泰人寿保险股份有限公司山东分公司"
    assert case.institution_type == InstitutionType.LIFE_INSURANCE
    assert case.is_insurance_related is True
    assert "合同外利益" in case.case_summary or "11.5" in case.case_summary
    assert case.fine_amount  # 由 penalty_content 轻量补齐
    assert case.publish_date == "2026-03-03"


def test_llm_failure_falls_back_to_regex():
    class _BrokenLLM:
        def complete(self, *args, **kwargs):
            raise RuntimeError("boom")

    engine = ExtractorEngine(
        llm_client=_BrokenLLM(), use_llm_refine=False, extraction_mode="llm_first",
    )
    cases = engine.extract(
        ParseResult(success=True, markdown=SAMPLE_DECISION_TEXT, confidence=0.9),
        file_id="F_FB", source_file="x.pdf",
    )
    assert len(cases) == 1
    assert cases[0].extraction_method == "regex"
    assert "华泰人寿" in cases[0].party_name


def test_llm_short_fields_backfilled_from_regex():
    """文号/机关：正则可用时覆盖错误或空的 LLM 短字段；长字段仍用 LLM。"""
    fake = _FakeLLM({
        "party_name": "华泰人寿保险股份有限公司山东分公司",
        "institution_type": "寿险公司",
        "is_insurance_related": True,
        "penalty_doc_no": None,
        "violation_behavior": "给予投保人保险合同约定以外的其他利益（LLM专属表述）",
        "penalty_content": "罚款人民币11.5万元",
        "regulator": "国家金融监督管理总局",  # 裸机关名，应由正则换成带地区
        "case_summary": "摘要",
    })
    engine = ExtractorEngine(
        llm_client=fake, use_llm_refine=False, extraction_mode="llm_first",
    )
    cases = engine.extract(
        ParseResult(success=True, markdown=SAMPLE_DECISION_TEXT, confidence=0.9),
        file_id="F_HY", source_file="x.pdf",
    )
    assert len(cases) == 1
    case = cases[0]
    assert case.extraction_method == "hybrid"
    assert case.penalty_doc_no == "鲁金罚决字〔2026〕16号"
    assert "山东监管局" in case.regulator
    assert case.regulator != "国家金融监督管理总局"
    assert "LLM专属表述" in case.violation_behavior
    assert case.penalty_content == "罚款人民币11.5万元"


def test_llm_party_only_filled_when_empty():
    """当事人仅在 LLM 空时回填，不覆盖 LLM 已给出的主体。"""
    fake = _FakeLLM({
        "party_name": "华泰人寿保险股份有限公司山东分公司",
        "institution_type": "寿险公司",
        "is_insurance_related": True,
        "penalty_doc_no": "鲁金罚决字〔2026〕16号",
        "violation_behavior": "给予投保人保险合同约定以外的其他利益",
        "penalty_content": "罚款人民币11.5万元",
        "regulator": "国家金融监督管理总局山东监管局",
        "case_summary": "摘要",
    })
    engine = ExtractorEngine(
        llm_client=fake, use_llm_refine=False, extraction_mode="llm_first",
    )
    case = engine.extract(
        ParseResult(success=True, markdown=SAMPLE_DECISION_TEXT, confidence=0.9),
        file_id="F_P", source_file="x.pdf",
    )[0]
    assert case.party_name == "华泰人寿保险股份有限公司山东分公司"
    # 文号/机关与正则一致时可不标 hybrid；若正则改写了同义写法也可能 hybrid
    assert "给予投保人" in case.violation_behavior


def test_institution_type_health_insurance_branch_is_life():
    """健康险+分公司：业态优先，应判寿险公司而非保险分支机构。"""
    from pipeline.extraction.schema import ExtractedCase

    engine = ExtractorEngine(llm_client=None, use_llm_refine=False)
    case = ExtractedCase(
        file_id="F",
        source_file="x.pdf",
        party_name="昆仑健康保险股份有限公司广东分公司",
        violation_behavior="虚列费用、电销业务销售误导",
    )
    engine._infer_institution_type(case)
    assert case.institution_type == InstitutionType.LIFE_INSURANCE


def test_institution_type_life_branch_still_life():
    from pipeline.extraction.schema import ExtractedCase

    engine = ExtractorEngine(llm_client=None, use_llm_refine=False)
    case = ExtractedCase(
        file_id="F",
        source_file="x.pdf",
        party_name="华泰人寿保险股份有限公司山东分公司",
    )
    engine._infer_institution_type(case)
    assert case.institution_type == InstitutionType.LIFE_INSURANCE


def test_institution_type_generic_branch_fallback():
    """无业态关键词、仅有分公司时才落保险分支机构。"""
    from pipeline.extraction.schema import ExtractedCase

    engine = ExtractorEngine(llm_client=None, use_llm_refine=False)
    case = ExtractedCase(
        file_id="F",
        source_file="x.pdf",
        party_name="某某保险股份有限公司广东分公司",
    )
    engine._infer_institution_type(case)
    assert case.institution_type == InstitutionType.INSURANCE_BRANCH
