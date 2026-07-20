from engine.classification.tag_mapper import (
    map_internal_to_competition,
    to_submission_risk_types,
)


def test_internal_to_competition_mapping():
    assert map_internal_to_competition("R002-01-01") == "R002"
    assert map_internal_to_competition("R001") == "R001"
    assert map_internal_to_competition("X999") == ""


def test_submission_risk_types_joined_with_chinese_semicolon():
    result = to_submission_risk_types(["R002-01-01", "R001-01", "R002"])
    assert result == "欺骗投保人/销售误导；给予保险合同约定以外利益"
