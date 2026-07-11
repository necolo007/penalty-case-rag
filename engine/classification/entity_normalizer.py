"""主体关联与标准化：原始当事人名称 → 标准机构类型（任务2交付物 subject_relations）。"""

import re
from dataclasses import dataclass


@dataclass
class NormalizedEntity:
    raw_name: str
    normalized_name: str
    entity_type: str          # 保险公司/保险分支机构/保险代理中介/责任人员/第三方主体
    confidence: float


_BRANCH_PATTERN = re.compile(r"(分公司|支公司|中心支公司|营业部|营销服务部)")
_AGENCY_PATTERN = re.compile(r"(保险代理|保险经纪|保险公估|保险销售)")
_COMPANY_PATTERN = re.compile(r"保险(股份)?有限公司|相互保险社|再保险")
_PERSON_PATTERN = re.compile(r"^[\u4e00-\u9fff]{2,4}$")  # 纯 2-4 字中文名视为自然人


def normalize_entity(raw_name: str) -> NormalizedEntity:
    name = (raw_name or "").strip()
    normalized = re.sub(r"[\s（(].*?[）)]?$", "", name) or name

    if _AGENCY_PATTERN.search(name):
        etype, conf = "保险代理中介", 0.9
    elif _BRANCH_PATTERN.search(name) and _COMPANY_PATTERN.search(name):
        etype, conf = "保险分支机构", 0.9
    elif _COMPANY_PATTERN.search(name):
        etype, conf = "保险公司", 0.9
    elif _PERSON_PATTERN.match(name):
        etype, conf = "责任人员", 0.7
    else:
        etype, conf = "第三方主体", 0.5

    return NormalizedEntity(
        raw_name=name, normalized_name=normalized, entity_type=etype, confidence=conf,
    )


def split_parties(raw_party_field: str) -> list[str]:
    """多主体共格拆分：按顿号/分号/换行拆开"""
    parts = re.split(r"[、;；\n]+", raw_party_field or "")
    return [p.strip() for p in parts if p.strip()]
