"""配套数据 27 类中文 risk_tag ↔ 赛题扁平 R001–R008 映射。

提交 submission.jsonl 的 risk_type 使用中文标签（分号；拼接），
库内 risk_type_ids 仍存 R00x，便于标签召回。
"""

from __future__ import annotations

# 中文标签 → 扁平赛题 ID（未列出的归入最接近大类，无法归类则空）
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
    "合同外利益": "R002",
    "赠送利益": "R002",
    "回扣返佣": "R002",
    "诱导投保": "R002",
    "虚假宣传": "R003",
    "产品说明会违规": "R003",
    "培训材料违规": "R003",
    "不当比较": "R003",
    "贬低竞品": "R003",
    "电销违规": "R001",  # 常与销售误导叠加，映射 R001
    "回访违规": "R001",
    "避债避税": "R001",
    "代理人管理不到位": "R004",
    "委托无资质机构销售": "R004",
    "虚列费用套取资金": "R005",
    "未按规定使用费率条款": "R006",
    "客户信息不真实": "R006",
    "其他": "",
}

# R00x → 默认展示用中文标签（提交兜底）
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

# 口语/话术关键词 → 中文标签（规则预测与同义词扩充）
CN_TAG_KEYWORDS: dict[str, list[str]] = {
    "合同外利益": [
        "合同约定以外", "合同外利益", "赠送", "体检卡", "加油卡", "洗车券", "代金券", "油卡",
        "保费优惠", "首年.*折", "预交.*保费", "预缴.*保费",
    ],
    "赠送利益": ["赠送礼品", "赠送服务", "免费领", "领取礼品"],
    "回扣返佣": [
        "返佣", "回扣", "返现", "预缴费打折", "缴费打折", "打折", "折扣",
        r"\d折", "优惠活动",
    ],
    "销售误导": [
        "销售误导", "误导性", "引人误解", "储蓄计划", "活期", "把钱从银行",
        "利息.*倍", "像存款", "存钱",
    ],
    "欺骗投保人": ["欺骗投保人", "虚假告知"],
    "夸大收益": [
        "夸大收益", "最高收益", "稳赚", "年化收益", "年化", "翻好几倍",
        "利息马上", "撬动杠杆", "赚概率",
    ],
    "承诺收益": ["承诺收益", "保本保息", "保证回报", "保本", "保息", "固定收益"],
    "保证收益": ["保证收益", "保证收益率", "稳赚不赔"],
    "弱化风险提示": [
        "不用担心", "无风险", "零风险", "忽略风险", "弱化风险", "一定会赔",
        "完全无风险", "比银行更安全", "免责.*不重要", "免责条款.*没事",
    ],
    "隐瞒重要信息": ["隐瞒", "未充分告知", "未披露"],
    "虚构收益率": ["虚构收益", "编造收益", "伪造收益"],
    "绝对化表述": ["最好", "最优", "第一", "唯一"],
    "虚假宣传": ["虚假宣传", "夸大宣传"],
    "产品说明会违规": ["产品说明会", "产说会"],
    "培训材料违规": ["培训材料", "培训话术"],
    "电销违规": ["电销", "电话销售"],
    "不当比较": ["不当对比", "与其他公司产品", "和银行", "比存款"],
    "贬低竞品": ["贬低", "诋毁"],
    "诱导投保": ["诱导投保", "不当手段"],
    "避债避税": ["避债", "避税", "规避债务"],
    "回访违规": ["回访", "阻碍.*回访", "阻挠.*回访"],
    "虚列费用套取资金": ["虚列费用", "套取费用", "虚假列支"],
    "代理人管理不到位": ["代理人管理", "执业登记"],
    "委托无资质机构销售": ["无资质", "委托.*销售"],
}


def cn_tags_to_competition_ids(tags: list[str] | None) -> list[str]:
    """中文 risk_tags → 去重后的 R00x 列表。"""
    ids: list[str] = []
    for tag in tags or []:
        cid = CN_TAG_TO_COMPETITION.get(tag.strip(), "")
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def competition_ids_to_cn_tags(competition_ids: list[str] | None,
                               preferred_cn: list[str] | None = None) -> list[str]:
    """R00x → 中文标签。优先保留 preferred_cn 中已映射到该 ID 的原标签。"""
    if preferred_cn:
        mapped = [t for t in preferred_cn if CN_TAG_TO_COMPETITION.get(t)]
        if mapped:
            return list(dict.fromkeys(mapped))
    result: list[str] = []
    for cid in competition_ids or []:
        name = COMPETITION_TO_CN_DEFAULT.get(cid)
        if name and name not in result:
            result.append(name)
    return result


def format_submission_risk_type(cn_tags: list[str] | None = None,
                                competition_ids: list[str] | None = None) -> str:
    """submission.risk_type：中文标签用中文分号拼接。"""
    tags = list(dict.fromkeys(cn_tags or []))
    if not tags:
        tags = competition_ids_to_cn_tags(competition_ids)
    return "；".join(tags)


def predict_cn_tags_by_keywords(text: str) -> list[str]:
    """基于关键词词典初判中文风险标签（用于检索风险预测增强）。"""
    import re

    hits: list[str] = []
    for tag, keywords in CN_TAG_KEYWORDS.items():
        for kw in keywords:
            try:
                if re.search(kw, text):
                    hits.append(tag)
                    break
            except re.error:
                if kw in text:
                    hits.append(tag)
                    break
    return list(dict.fromkeys(hits))[:5]
