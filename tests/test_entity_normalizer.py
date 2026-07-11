from engine.classification.entity_normalizer import normalize_entity, split_parties


def test_branch_company():
    e = normalize_entity("华泰人寿保险股份有限公司山东分公司")
    assert e.entity_type == "保险分支机构"


def test_head_company():
    e = normalize_entity("华泰人寿保险股份有限公司")
    assert e.entity_type == "保险公司"


def test_agency():
    e = normalize_entity("某某保险代理有限公司")
    assert e.entity_type == "保险代理中介"


def test_person():
    e = normalize_entity("张三")
    assert e.entity_type == "责任人员"


def test_split_parties():
    parts = split_parties("华泰人寿山东分公司、张三；李四")
    assert parts == ["华泰人寿山东分公司", "张三", "李四"]
