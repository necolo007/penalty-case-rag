"""27 类中文 risk_tag ↔ R001–R008；CSV 典型行为/排除边界参与关键词预测与消歧。"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

CANONICAL_CN_TAGS: tuple[str, ...] = (
    "欺骗投保人",
    "销售误导",
    "夸大收益",
    "虚假宣传",
    "合同外利益",
    "赠送利益",
    "回扣返佣",
    "产品说明会违规",
    "培训材料违规",
    "回访违规",
    "电销违规",
    "不当比较",
    "贬低竞品",
    "绝对化表述",
    "承诺收益",
    "保证收益",
    "弱化风险提示",
    "隐瞒重要信息",
    "虚构收益率",
    "诱导投保",
    "避债避税",
    "虚列费用套取资金",
    "代理人管理不到位",
    "委托无资质机构销售",
    "未按规定使用费率条款",
    "客户信息不真实",
    "其他",
)

CANONICAL_CN_TAG_SET = frozenset(CANONICAL_CN_TAGS)

CN_TAG_TO_COMPETITION: dict[str, str] = {
    "欺骗投保人": "R001",
    "销售误导": "R001",
    "夸大收益": "R001",
    "承诺收益": "R001",
    "保证收益": "R001",
    "弱化风险提示": "R001",
    "隐瞒重要信息": "R001",
    "虚构收益率": "R001",
    "绝对化表述": "R001",
    "电销违规": "R001",
    "回访违规": "R001",
    "避债避税": "R001",
    "合同外利益": "R002",
    "赠送利益": "R002",
    "回扣返佣": "R002",
    "诱导投保": "R002",
    "虚假宣传": "R003",
    "产品说明会违规": "R003",
    "培训材料违规": "R003",
    "不当比较": "R003",
    "贬低竞品": "R003",
    "代理人管理不到位": "R004",
    "委托无资质机构销售": "R004",
    "虚列费用套取资金": "R005",
    "未按规定使用费率条款": "R006",
    "客户信息不真实": "R006",
    "其他": "",
}

COMPETITION_TO_CN_DEFAULT: dict[str, str] = {
    "R001": "销售误导",
    "R002": "合同外利益",
    "R003": "虚假宣传",
    "R004": "代理人管理不到位",
    "R005": "虚列费用套取资金",
    "R006": "虚列费用套取资金",
    "R007": "其他",
    "R008": "其他",
}

CN_TAG_ALIASES: dict[str, list[str]] = {
    "给予保险合同约定以外利益": ["合同外利益"],
    "给予投保人保险合同约定以外的其他利益": ["合同外利益"],
    "给予投保人合同外利益": ["合同外利益"],
    "销售误导/夸大收益": ["销售误导", "夸大收益"],
    "欺骗投保人/销售误导": ["欺骗投保人", "销售误导"],
    "宣传材料或产品说明会数据资料不真实": ["虚假宣传", "产品说明会违规"],
    "销售人员执业登记管理不规范": ["代理人管理不到位"],
    "虚构/虚挂中介业务套取费用": ["虚列费用套取资金"],
    "编制虚假财务资料": ["虚列费用套取资金"],
    "保险代理人侵害消费者权益": ["其他"],
    "利用开展保险业务牟取不正当利益": ["其他"],
    "销售违规": ["销售误导"],
    "消费者权益保护": ["其他"],
    "误导": ["销售误导"],
}

CN_TAG_KEYWORDS: dict[str, list[str]] = {
    "合同外利益": [
        "合同约定以外", "合同外利益", "赠送", "体检卡", "加油卡", "洗车券", "代金券", "油卡",
        "保费优惠", "首年.*折", "预交.*保费", "预缴.*保费",
    ],
    "赠送利益": ["赠送礼品", "赠送服务", "免费领", "领取礼品", "体检卡", "加油卡", "洗车券"],
    "回扣返佣": [
        "返佣", "回扣", "返现", "预缴费打折", "缴费打折", "打折", "折扣",
        r"\d折", "优惠活动",
    ],
    "销售误导": [
        "销售误导", "误导性", "引人误解", "储蓄计划", "活期", "把钱从银行",
        "利息.*倍", "像存款", "存钱",
    ],
    "欺骗投保人": ["欺骗投保人", "虚假告知", "伪造", "变造"],
    "夸大收益": [
        "夸大收益", "最高收益", "稳赚", "年化收益", "年化", "翻好几倍",
        "利息马上", "撬动杠杆", "赚概率", "收益翻倍", "比存银行",
    ],
    "承诺收益": ["承诺收益", "保本保息", "保证回报", "保本", "保息", "固定收益", "一定赚钱", "买了肯定不亏"],
    "保证收益": ["保证收益", "保证收益率", "稳赚不赔", "保证年化"],
    "弱化风险提示": [
        "不用担心", "无风险", "零风险", "忽略风险", "弱化风险", "一定会赔",
        "完全无风险", "比银行更安全", "免责.*不重要", "免责条款.*没事",
    ],
    "隐瞒重要信息": ["隐瞒", "未充分告知", "未披露", "未向投保人说明"],
    "虚构收益率": ["虚构收益", "编造收益", "伪造收益", "虚构分红"],
    "绝对化表述": ["最好", "最优", "第一", "唯一", "行业领先"],
    "虚假宣传": ["虚假宣传", "夸大宣传", "未经.*备案的宣传"],
    "产品说明会违规": ["产品说明会", "产说会"],
    "培训材料违规": ["培训材料", "培训话术", "培训PPT"],
    "电销违规": ["电销", "电话销售"],
    "不当比较": ["不当对比", "与其他公司产品", "和银行", "比存款", "比理财更安全"],
    "贬低竞品": ["贬低", "诋毁", "同业负面"],
    "诱导投保": ["诱导投保", "不当手段", "限时抢购", "名额有限", "即将停售"],
    "避债避税": ["避债", "避税", "规避债务", "收益免税"],
    "回访违规": ["回访", "阻碍.*回访", "阻挠.*回访"],
    "虚列费用套取资金": ["虚列费用", "套取费用", "虚假列支", "虚挂中介"],
    "代理人管理不到位": ["代理人管理", "执业登记"],
    "委托无资质机构销售": ["无资质", "委托.*销售"],
    "未按规定使用费率条款": ["费率条款", "未按规定使用", "擅自变更.*条款"],
    "客户信息不真实": ["客户信息不真实", "信息不真实", "回访记录造假", "代签"],
}

_DICT_PATH = Path(__file__).resolve().parents[2] / "data" / "dictionaries" / "risk_type_dictionary.csv"

_QUOTE_RE = re.compile(r'[“"『「]([^”"』」]{2,24})[”"』」]')
_REDIRECT_RE = re.compile(r"归入([^；;，,、（(]{2,20})")


def _row_field(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        val = (row.get(key) or "").strip()
        if val:
            return val
    return ""


def _extract_phrases_from_typical(text: str) -> list[str]:
    """从典型行为描述中抽取可匹配短语。"""
    if not text:
        return []
    phrases: list[str] = []
    for q in _QUOTE_RE.findall(text):
        q = q.strip()
        if 2 <= len(q) <= 24:
            phrases.append(q)
    for part in re.split(r"[；;。]", text):
        part = part.strip().strip("。；;，,")
        if not part:
            continue
        for chunk in re.split(r"[、，,（(]", part):
            chunk = chunk.strip(" ）)」》\"'“”")
            if 2 <= len(chunk) <= 16 and not chunk.startswith(("不包括", "区别于", "上位", "涵盖")):
                phrases.append(chunk)
    return list(dict.fromkeys(phrases))[:20]


@lru_cache(maxsize=1)
def load_cn_tag_catalog() -> list[dict[str, str]]:
    """从 CSV 读取 27 类标签目录（含典型行为/排除边界/监管依据）；失败时回退内置常量。"""
    if _DICT_PATH.exists():
        rows: list[dict[str, str]] = []
        with _DICT_PATH.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                tag = (row.get("risk_tag") or "").strip()
                if not tag:
                    continue
                rows.append({
                    "risk_tag": tag,
                    "description": _row_field(row, "description"),
                    "typical_behavior": _row_field(row, "典型行为", "typical_behavior"),
                    "exclusion_boundary": _row_field(row, "排除边界", "exclusion_boundary"),
                    "legal_basis": _row_field(row, "监管依据", "legal_basis"),
                    "category": _row_field(row, "category"),
                    "competition_id": CN_TAG_TO_COMPETITION.get(tag, ""),
                })
        if rows:
            return rows
    return [
        {
            "risk_tag": t,
            "description": "",
            "typical_behavior": "",
            "exclusion_boundary": "",
            "legal_basis": "",
            "category": "",
            "competition_id": CN_TAG_TO_COMPETITION.get(t, ""),
        }
        for t in CANONICAL_CN_TAGS
    ]


@lru_cache(maxsize=1)
def _merged_keyword_map() -> dict[str, list[str]]:
    """硬编码关键词 ∪ CSV 典型行为抽取短语。"""
    merged: dict[str, list[str]] = {k: list(v) for k, v in CN_TAG_KEYWORDS.items()}
    for row in load_cn_tag_catalog():
        tag = row["risk_tag"]
        if tag == "其他":
            continue
        extra = _extract_phrases_from_typical(row.get("typical_behavior") or "")
        if not extra:
            continue
        bucket = merged.setdefault(tag, [])
        for phrase in extra:
            if phrase not in bucket:
                bucket.append(phrase)
    return merged


@lru_cache(maxsize=1)
def _exclusion_redirects() -> dict[str, list[tuple[str, list[str]]]]:
    """tag → [(更具体标签, 触发短语列表), ...]，来自排除边界「归入X」。"""
    out: dict[str, list[tuple[str, list[str]]]] = {}
    for row in load_cn_tag_catalog():
        tag = row["risk_tag"]
        excl = row.get("exclusion_boundary") or ""
        if not excl:
            continue
        triggers = _QUOTE_RE.findall(excl)
        for m in _REDIRECT_RE.finditer(excl):
            target = m.group(1).strip()
            mapped = next((t for t in CANONICAL_CN_TAGS if t != "其他" and (t == target or t in target)), None)
            if not mapped or mapped == tag:
                continue
            out.setdefault(tag, []).append((mapped, triggers))
    return out


def format_cn_tag_guide_for_prompt(*, max_tags: int = 27, max_chars: int = 3500) -> str:
    """供审查/分类 Prompt 使用的标签消歧指南。"""
    lines: list[str] = []
    for row in load_cn_tag_catalog()[:max_tags]:
        tag = row["risk_tag"]
        if tag == "其他":
            continue
        tip = row.get("exclusion_boundary") or row.get("typical_behavior") or row.get("description") or ""
        tip = tip.replace("\n", " ").strip()
        if len(tip) > 90:
            tip = tip[:90] + "…"
        line = f"- {tag}：{tip}" if tip else f"- {tag}"
        lines.append(line)
        if sum(len(x) + 1 for x in lines) >= max_chars:
            break
    return "\n".join(lines)


def cn_tags_to_competition_ids(tags: list[str] | None) -> list[str]:
    """中文 risk_tags → 去重后的 R00x 列表（内部召回）。"""
    ids: list[str] = []
    for tag in normalize_cn_tags(tags):
        cid = CN_TAG_TO_COMPETITION.get(tag, "")
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def competition_ids_to_cn_tags(competition_ids: list[str] | None,
                               preferred_cn: list[str] | None = None) -> list[str]:
    """R00x → 中文标签。优先保留 preferred_cn 中已映射到该 ID 的原标签。"""
    preferred = normalize_cn_tags(preferred_cn)
    if preferred:
        return preferred
    result: list[str] = []
    for cid in competition_ids or []:
        name = COMPETITION_TO_CN_DEFAULT.get(str(cid).strip().upper())
        if name and name not in result:
            result.append(name)
    return result


def normalize_cn_tags(tags: list[str] | None) -> list[str]:
    """将任意标签/别名/R00x/复合写法归一为 27 类标准标签。"""
    if not tags:
        return []
    out: list[str] = []
    for raw in tags:
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        parts = [text]
        for sep in ("；", ";", "/", "|", "、", ","):
            if sep in text:
                parts = [p.strip() for p in text.split(sep) if p.strip()]
                break
        for part in parts:
            for tag in _expand_one_tag(part):
                if tag not in out:
                    out.append(tag)
    return out


def _expand_one_tag(text: str) -> list[str]:
    if text in CANONICAL_CN_TAG_SET:
        return [text]
    if text.upper() in COMPETITION_TO_CN_DEFAULT:
        return [COMPETITION_TO_CN_DEFAULT[text.upper()]]
    if text in CN_TAG_ALIASES:
        return list(CN_TAG_ALIASES[text])
    hits = [t for t in CANONICAL_CN_TAGS if t != "其他" and t in text]
    if hits:
        return hits
    for alias, mapped in CN_TAG_ALIASES.items():
        if alias in text or text in alias:
            return list(mapped)
    return []


def format_submission_risk_type(cn_tags: list[str] | None = None,
                                competition_ids: list[str] | None = None) -> str:
    tags = normalize_cn_tags(cn_tags)
    if not tags:
        tags = competition_ids_to_cn_tags(competition_ids)
    return "；".join(tags)


def _apply_exclusion_boundaries(text: str, hits: list[str]) -> list[str]:
    if len(hits) <= 1:
        return hits
    redirects = _exclusion_redirects()
    demote: set[str] = set()
    promote: list[str] = []
    for tag in hits:
        for target, triggers in redirects.get(tag, []):
            trigger_ok = (not triggers) or any(t in text for t in triggers)
            if not trigger_ok:
                continue
            if target in hits or triggers:
                demote.add(tag)
                if target not in hits and target not in promote:
                    promote.append(target)
    result = [t for t in hits if t not in demote]
    for t in promote:
        if t not in result:
            result.append(t)
    return result


def predict_cn_tags_by_keywords(text: str) -> list[str]:
    hits: list[str] = []
    for tag, keywords in _merged_keyword_map().items():
        for kw in keywords:
            try:
                if re.search(kw, text):
                    hits.append(tag)
                    break
            except re.error:
                if kw in text:
                    hits.append(tag)
                    break
    hits = list(dict.fromkeys(hits))
    hits = _apply_exclusion_boundaries(text, hits)
    return hits[:5]


def resolve_final_cn_tags(
    *,
    query_text: str = "",
    keyword_tags: list[str] | None = None,
    case_tags: list[str] | None = None,
    llm_tags: list[str] | None = None,
    competition_ids: list[str] | None = None,
    max_tags: int = 5,
) -> list[str]:
    merged: list[str] = []
    for src in (keyword_tags, llm_tags, case_tags):
        for tag in normalize_cn_tags(src):
            if tag not in merged:
                merged.append(tag)
    if not merged and query_text:
        for tag in predict_cn_tags_by_keywords(query_text):
            if tag not in merged:
                merged.append(tag)
    if not merged and competition_ids:
        for tag in competition_ids_to_cn_tags(competition_ids):
            if tag not in merged:
                merged.append(tag)
    if query_text and len(merged) > 1:
        merged = _apply_exclusion_boundaries(query_text, merged)
    if len(merged) > 1:
        merged = [t for t in merged if t != "其他"] or merged
    return merged[:max_tags]
