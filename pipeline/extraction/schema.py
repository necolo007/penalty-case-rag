"""结构化处罚案例 schema（任务1输出）。"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class InstitutionType(str, Enum):
    """与 docs/change/n8-4/prompt.md 选项对齐（代理/经纪分开，无「分支机构」档）。"""

    LIFE_INSURANCE = "寿险公司"
    PROPERTY_INSURANCE = "财险公司"
    INSURANCE_AGENCY = "保险代理"
    INSURANCE_BROKER = "保险经纪"
    INSURANCE_COMPANY = "保险公司"
    OTHER = "其他"
    NON_INSURANCE = "非保险"
    UNKNOWN = "无法判断"


# 历史落库/金标别名 → 现行枚举值
_INSTITUTION_TYPE_ALIASES = {
    "保险代理/中介": "保险代理",
    "保险分支机构": "保险公司",
    "保险代理人": "其他",
    "其他金融机构": "其他",
}


def coerce_institution_type(raw: str | None) -> InstitutionType:
    """把 LLM/金标/旧库字符串规范到 InstitutionType。"""
    s = (raw or "").strip()
    if not s or s.lower() == "null":
        return InstitutionType.NON_INSURANCE
    s = _INSTITUTION_TYPE_ALIASES.get(s, s)
    try:
        return InstitutionType(s)
    except ValueError:
        return InstitutionType.NON_INSURANCE


class FieldConfidence(str, Enum):
    HIGH = "high"        # 正则精确匹配 + 校验通过
    MEDIUM = "medium"    # LLM 补全 / 规则推断
    LOW = "low"          # 可能存在错误，建议人工复核


@dataclass
class ExtractedCase:
    """从文档中抽取的结构化处罚案例"""
    # 来源信息
    file_id: str
    source_file: str
    source_page: Optional[int] = None

    # 核心字段
    party_name: str = ""
    institution_type: InstitutionType = InstitutionType.NON_INSURANCE
    penalty_doc_no: str = ""
    violation_behavior: str = ""
    penalty_content: str = ""
    fine_amount: str = ""
    regulator: str = ""
    publish_date: Optional[str] = None      # YYYY-MM-DD
    legal_basis: str = ""

    # 质量标记
    is_insurance_related: bool = False
    is_insurance_candidate: bool = False
    candidate_reasons: list[str] = field(default_factory=list)
    field_confidences: dict[str, str] = field(default_factory=dict)
    overall_confidence: float = 0.0

    # 分类结果
    risk_tags: list[str] = field(default_factory=list)         # 展示标签
    risk_type_ids: list[str] = field(default_factory=list)     # 赛题扁平 ID
    internal_tag_ids: list[str] = field(default_factory=list)  # 内部三级 ID
    case_summary: str = ""

    # 抽取元数据
    extraction_method: str = "regex"        # regex | table | llm | hybrid
    raw_text_snippet: str = ""
