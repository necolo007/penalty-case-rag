from pathlib import Path

from engine.classification.insurance_filter import InsuranceFilter

DICT_DIR = Path(__file__).resolve().parents[1] / "data" / "dictionaries"


def make_filter() -> InsuranceFilter:
    # 不存在的目录 → 使用内置默认词表
    return InsuranceFilter(dict_dir="nonexistent")


def make_synced_filter() -> InsuranceFilter:
    return InsuranceFilter(dict_dir=DICT_DIR)


def test_insurance_company_detected():
    f = make_filter()
    s = f.score(
        "华泰人寿保险股份有限公司山东分公司",
        "给予投保人保险合同约定以外的其他利益",
        "《保险法》第一百一十六条",
    )
    assert s.is_insurance
    assert s.final >= 0.5
    assert any("机构关键词" in r for r in s.reasons)


def test_bank_excluded():
    f = make_filter()
    s = f.score(
        "某某农村商业银行股份有限公司",
        "违规发放贷款",
        "《商业银行法》",
    )
    assert not s.is_insurance
    assert s.exclude == 1.0


def test_candidate_loose_threshold():
    f = make_filter()
    # 仅业务词命中：不足以精筛通过，但应进入候选集
    candidate, reasons = f.is_candidate("张三", "退保后向投保人返还保费并赠送礼品", "")
    assert candidate
    is_ins = f.score("张三", "退保后向投保人返还保费并赠送礼品", "").is_insurance
    assert not is_ins


def test_brand_entity_from_synced_dict():
    f = make_synced_filter()
    s = f.score("中国平安人寿保险股份有限公司", "销售误导客户", "《保险法》")
    assert s.is_insurance
    assert any("中国平安" in r or "人寿保险" in r for r in s.reasons)


def test_new_business_terms_hesitation_period():
    f = make_synced_filter()
    candidate, reasons = f.is_candidate("李四", "未告知犹豫期及退保损失", "")
    assert candidate
    assert any("犹豫期" in r for r in reasons)
