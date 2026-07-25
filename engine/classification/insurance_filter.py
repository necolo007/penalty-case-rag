"""保险案例三维词典筛选：主体×0.4 + 业务×0.35 + 监管×0.25，排除词一票否决。"""

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_ENTITY_TERMS = [
    "人寿保险", "财产保险", "健康保险", "养老保险", "保险股份",
    "相互保险", "再保险", "保险代理", "保险经纪", "保险公估",
    "保险销售", "人寿", "财险", "寿险",
    "中国平安", "中国太保", "中国人保", "中国太平", "新华保险",
    "泰康保险", "阳光保险", "众安在线", "泰康在线",
]

DEFAULT_BUSINESS_TERMS = [
    "承保", "退保", "保单", "保费", "理赔", "投保人", "被保险人",
    "保险合同", "保险产品", "保险业务", "保险条款", "银保", "个险",
    "团险", "中介业务", "保险中介", "犹豫期", "双录", "产说会",
    "产品说明会", "重疾险", "医疗险", "车险", "年金险", "保全",
    "宽限期", "偿付能力", "核保", "核赔",
]

DEFAULT_REGULATORY_TERMS = [
    "保险法", "保险销售行为管理办法", "保险公司管理规定",
    "保险代理人监管规定", "保险经纪人监管规定", "人身保险",
    "银保监", "金融监督管理总局", "健康保险管理办法",
    "保险公司偿付能力管理规定", "农业保险条例",
]

DEFAULT_EXCLUDE_TERMS = [
    "银行股份", "农村商业银行", "城市商业银行", "村镇银行",
    "消费金融", "金融租赁", "信托有限", "小额贷款", "融资担保",
]


@dataclass
class FilterScore:
    entity: float
    business: float
    regulatory: float
    exclude: float
    final: float
    is_insurance: bool
    reasons: list[str]


def _load_terms(csv_path: Path, default: list[str]) -> list[str]:
    if not csv_path.exists():
        return default
    terms = []
    with csv_path.open(encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if row and row[0].strip() and not row[0].startswith("#"):
                terms.append(row[0].strip())
    terms = sorted(set(terms), key=len, reverse=True)
    return terms or default


def _hit_score(hits: list[str]) -> float:
    if not hits:
        return 0.0
    best = max(len(t) for t in hits)
    if best >= 6:
        return 1.0
    if best >= 4:
        return 0.9
    if best >= 3:
        return 0.75
    return 0.55


class InsuranceFilter:
    def __init__(self, dict_dir: str | Path = "data/dictionaries"):
        d = Path(dict_dir)
        self.entity_terms = _load_terms(d / "entity_name_dict.csv", DEFAULT_ENTITY_TERMS)
        self.business_terms = _load_terms(d / "insurance_business_dict.csv", DEFAULT_BUSINESS_TERMS)
        self.regulatory_terms = _load_terms(d / "regulatory_basis_dict.csv", DEFAULT_REGULATORY_TERMS)
        self.exclude_terms = _load_terms(d / "exclude_dict.csv", DEFAULT_EXCLUDE_TERMS)

    @staticmethod
    def _match(text: str, terms: list[str]) -> list[str]:
        if not text:
            return []
        return [t for t in terms if t in text]

    def score(self, party_name: str, violation_behavior: str, legal_basis: str) -> FilterScore:
        party = party_name or ""
        violation = violation_behavior or ""
        basis = legal_basis or ""
        entity_hits = self._match(party, self.entity_terms) or self._match(violation, self.entity_terms)
        business_hits = self._match(f"{violation}\n{party}\n{basis}", self.business_terms)
        regulatory_hits = self._match(basis, self.regulatory_terms) or self._match(
            violation, self.regulatory_terms,
        )
        exclude_hits = self._match(party, self.exclude_terms)

        entity = _hit_score(entity_hits)
        business = _hit_score(business_hits)
        regulatory = _hit_score(regulatory_hits)
        exclude = 1.0 if exclude_hits else 0.0

        final = 0.4 * entity + 0.35 * business + 0.25 * regulatory
        is_insurance = final >= 0.5 and exclude == 0.0

        reasons = []
        reasons.extend(f"命中机构关键词：{t}" for t in entity_hits[:3])
        reasons.extend(f"命中业务关键词：{t}" for t in business_hits[:3])
        reasons.extend(f"命中监管依据：{t}" for t in regulatory_hits[:3])
        reasons.extend(f"命中排除词：{t}" for t in exclude_hits[:3])

        return FilterScore(
            entity=entity, business=business, regulatory=regulatory,
            exclude=exclude, final=final, is_insurance=is_insurance, reasons=reasons,
        )

    def is_candidate(self, party_name: str, violation_behavior: str, legal_basis: str) -> tuple[bool, list[str]]:
        s = self.score(party_name, violation_behavior, legal_basis)
        candidate = (s.entity + s.business + s.regulatory) > 0 and s.exclude == 0
        return candidate, s.reasons
