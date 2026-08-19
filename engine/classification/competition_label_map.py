"""27 类中文 risk_tag 与赛题 R001–R008 的映射（双层）。

第一层（官方输出）：27 类中文细标签 —— 展示、提交、评测、训练。
第二层（内部召回）：仅在语义确属赛题八大类时写入 R00x；无法对齐的细标签
  （如费率条款合规、客户信息不实）不强制挂靠，避免污染标签通道。

CSV 典型行为/排除边界参与关键词预测与消歧。
"""

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
    # 产品合规 / 业务数据问题：不属于「编制虚假财务资料」(R006)，不强制映射官方八大类
    "未按规定使用费率条款": "",
    "客户信息不真实": "",
    "其他": "",
}

# 内部粗分桶（导航/统计用，非赛题官方 R00x）
CN_TAG_INTERNAL_BUCKET: dict[str, str] = {
    "未按规定使用费率条款": "产品合规",
    "客户信息不真实": "业务数据不实",
}

COMPETITION_TO_CN_DEFAULT: dict[str, str] = {
    "R001": "销售误导",
    "R002": "合同外利益",
    "R003": "虚假宣传",
    "R004": "代理人管理不到位",
    "R005": "虚列费用套取资金",
    # R006 编制虚假财务资料：27 类无一一对应细标签，禁止默认落到「虚列费用」(R005)
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
    # 训练集近义/错写（P0-4）
    "夸大服务": ["夸大收益", "虚假宣传"],
    "隐藏重要信息": ["隐瞒重要信息"],
    "错误解释保险责任": ["销售误导", "欺骗投保人"],
    "夸大宣传": ["虚假宣传"],
    "引诱投保": ["诱导投保"],
    "诱导购买": ["诱导投保"],
    "隐瞒信息": ["隐瞒重要信息"],
}

_BUILTIN_CN_TAG_KEYWORDS: dict[str, list[str]] = {
    "合同外利益": [
        "合同约定以外", "合同外利益", "赠送体检卡", "赠送加油卡", "赠送洗车券",
        "体检卡", "加油卡", "洗车券", "代金券", "油卡",
        "保费优惠", "首年.*折", "预交.*保费", "预缴.*保费",
    ],
    "赠送利益": ["赠送礼品", "赠送服务", "免费领", "领取礼品", "赠送油卡", "赠送代金券"],
    "回扣返佣": [
        "返佣", "回扣", "返现", "预缴费打折", "缴费打折", r"\d折",
    ],
    "销售误导": [
        "销售误导", "误导性", "引人误解", "储蓄计划", "把钱从银行",
        "利息.*倍", "像存款",
    ],
    "欺骗投保人": ["欺骗投保人", "虚假告知", r"不履行.{0,24}如实告知", "诱导投保人不履行"],
    "夸大收益": [
        "夸大收益", "最高收益", "稳赚", "年化收益", "翻好几倍",
        "收益翻倍", "比存银行", r"夸大.{0,8}收益", r"夸大.{0,8}(?:保单|产品|服务)",
    ],
    "承诺收益": [
        "承诺收益", "保本保息", "保证回报", "一定赚钱", "买了肯定不亏",
        r"承诺.{0,10}收益", r"承诺(?:给予|保证).{0,10}(?:利益|回报)",
    ],
    "保证收益": ["保证收益", "保证收益率", "稳赚不赔", "保证年化"],
    "弱化风险提示": [
        "不用担心", "无风险", "零风险", "弱化风险", "完全无风险",
        "比银行更安全", "免责.*不重要",
    ],
    "隐瞒重要信息": ["未充分告知", "未向投保人说明", "隐瞒与保险合同"],
    "虚构收益率": [
        "虚构收益", "编造收益", "伪造收益", "虚构分红", "夸大分红",
        "分红数值", "共同分红率", "错误介绍保险产品收益", r"虚构.{0,8}分红",
    ],
    "绝对化表述": [
        "行业领先", "全国第一", "独一无二", "行业第一", "排名第一",
        "市场唯一", "全国唯一", "绝对领先",
    ],
    "虚假宣传": ["虚假宣传", "夸大宣传", "未经.*备案的宣传"],
    "产品说明会违规": ["产品说明会", "产说会"],
    "培训材料违规": [
        "培训材料", "培训话术", "培训PPT", "培训课件", "培训班", r"培训.{0,10}课件",
    ],
    "电销违规": ["电销", "电话销售"],
    "不当比较": [
        "不当对比", "不当类比", "比存款", "比理财更安全", "片面比较",
        r"(?:收益|利益|分红).{0,15}(?:存款|银行|证券|理财).{0,10}(?:比较|类比)",
        r"(?:存款|银行).{0,15}(?:比较|类比)",
    ],
    "贬低竞品": ["贬低竞品", "诋毁同业", "同业负面"],
    "诱导投保": ["诱导投保", "限时抢购", "名额有限", "即将停售", "并未停售", "限时限额"],
    "避债避税": ["避债", "避税", "规避债务", "收益免税"],
    "回访违规": [
        "阻碍.*回访", "阻挠.*回访", "回访过程中", r"回访.{0,6}(?:问题|电话)",
        r"诱导.{0,10}回访", "回访对象非", "回访记录",
    ],
    "虚列费用套取资金": ["虚列费用", "套取费用", "虚假列支", "虚挂中介"],
    "代理人管理不到位": [
        "代理人管理", "执业登记", "资格证书", "执业证书", "展业证", "未按规定进行执业",
    ],
    "委托无资质机构销售": ["委托无资质", "无资质机构", r"委托.{0,20}(?:机构|公司|平台).{0,12}(?:销售|代理)"],
    "未按规定使用费率条款": ["费率条款", "未按规定使用", "擅自变更.*条款"],
    "客户信息不真实": ["客户信息不真实", "回访记录造假"],
}

# 过短/泛化词：禁止从典型行为自动并入
_GENERIC_PHRASE_BLOCKLIST = frozenset({
    "隐瞒", "伪造", "变造", "打折", "折扣", "最好", "最优", "第一", "唯一",
    "年化", "保本", "保息", "存钱", "活期", "回访", "电销", "赠送", "优惠活动",
    "不当手段", "虚假告知",
})

_DICT_PATH = Path(__file__).resolve().parents[2] / "data" / "dictionaries" / "risk_type_dictionary.csv"
_CN_KEYWORDS_PATH = Path(__file__).resolve().parents[2] / "data" / "dictionaries" / "cn_tag_keywords.csv"


@lru_cache(maxsize=1)
def load_cn_tag_keywords() -> dict[str, list[str]]:
    """优先读 data/dictionaries/cn_tag_keywords.csv；缺失时回退内置默认。"""
    if _CN_KEYWORDS_PATH.exists():
        loaded: dict[str, list[str]] = {}
        with _CN_KEYWORDS_PATH.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                tag = (row.get("risk_tag") or "").strip()
                kw = (row.get("keyword") or "").strip()
                if not tag or not kw or tag == "其他":
                    continue
                bucket = loaded.setdefault(tag, [])
                if kw not in bucket:
                    bucket.append(kw)
        if loaded:
            return loaded
    return {k: list(v) for k, v in _BUILTIN_CN_TAG_KEYWORDS.items()}


@lru_cache(maxsize=1)
def _merged_keyword_map() -> dict[str, list[str]]:
    """CSV/内置关键词 ∪ risk_type_dictionary 典型行为引号短语。"""
    merged: dict[str, list[str]] = {k: list(v) for k, v in load_cn_tag_keywords().items()}
    for row in load_cn_tag_catalog():
        tag = row["risk_tag"]
        if tag == "其他":
            continue
        for phrase in _extract_phrases_from_typical(row.get("typical_behavior") or ""):
            bucket = merged.setdefault(tag, [])
            if phrase not in bucket and phrase not in _GENERIC_PHRASE_BLOCKLIST:
                bucket.append(phrase)
    return merged

_QUOTE_RE = re.compile(r'[“"『「]([^”"』」]{2,24})[”"』」]')
_REDIRECT_RE = re.compile(r"归入([^；;，,、（(]{2,20})")


def _row_field(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        val = (row.get(key) or "").strip()
        if val:
            return val
    return ""


def _extract_phrases_from_typical(text: str) -> list[str]:
    """仅抽取引号内高特异性短语，避免短句泛化导致假阳性。"""
    if not text:
        return []
    phrases: list[str] = []
    for q in _QUOTE_RE.findall(text):
        q = q.strip()
        if len(q) < 4 or q in _GENERIC_PHRASE_BLOCKLIST:
            continue
        if 4 <= len(q) <= 24:
            phrases.append(q)
    return list(dict.fromkeys(phrases))[:12]


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
    return [r["normalized_label"] for r in normalize_cn_tags_detailed(tags)
            if r["status"] == "ok" and r.get("normalized_label")]


_ABS_EXPR_RE = re.compile(
    r"行业第一|排名第一|市场唯一|独一无二|全国第一|行业领先|全国唯一|绝对领先"
)
_FICTIVE_YIELD_RE = re.compile(
    r"虚构.{0,8}(?:分红|收益)|夸大分红|编造收益|伪造收益|虚构收益率|"
    r"错误介绍.{0,12}收益|分红数值|共同分红率"
)
_DECEIVE_APPLICANT_RE = re.compile(
    r"欺骗投保人|不履行.{0,30}如实告知|诱导投保人不履行"
)
_INDUCE_RE = re.compile(
    r"即将停售|即将结束|限时(?:抢购|限额|限售)|名额有限|限时限额|"
    r"虚构.{0,8}限售|实际并未停售|从未停售|并未停售"
)
_PERSON_UNLICENSED_RE = re.compile(
    r"(?:未取得|没有|无).{0,8}(?:资格证|执业证|展业证|资格证书|执业证书)|"
    r"无资格证|无执业证|无展业证|未按规定进行执业|执业登记"
)
_INST_UNLICENSED_RE = re.compile(
    r"委托.{0,40}(?:无资质|不具备资质|未取得.{0,16}资质).{0,24}"
    r"(?:机构|公司|平台).{0,20}(?:销售|代理)|"
    r"与无资质的第三方"
)
_WEAKEN_RE = re.compile(r"不用担心|零风险|无风险|完全无风险|忽略免责|免责.{0,8}不重要|一定赔")
_FAKE_CLIENT_RE = re.compile(
    r"代签|代为签名|代投保人签名|代替投保人|"
    r"代为抄写|抄录风险提示|抄录笔迹|"
    r"信息不真实|信息记录虚假|信息资料不真实|"
    r"回访记录造假|回访对象非|回访均不成功|"
    r"变更客户信息|更改.{0,12}电话号码|联系方式变更为|"
    r"虚构投保农户|虚假客户"
)
_OTHER_HINT_RE = re.compile(
    r"任职资格|未取得.{0,16}核准|牟取不正当利益|"
    r"保险资金委托|投资理财|问题档案|自查报告"
)
_GUARANTEE_RE = re.compile(r"保证年化|保证收益率|保证收益\d|保证.{0,8}\d+(?:\.\d+)?\s*%")


def refine_cn_tags(tags: list[str] | None, violation_behavior: str = "") -> list[str]:
    """对齐金标口径：细标签补上位；纠正代理人/无资质、停售诱导等易混标签。"""
    out = normalize_cn_tags(tags)
    blob = violation_behavior or ""

    if any(t in out for t in ("赠送利益", "回扣返佣")) and "合同外利益" not in out:
        out.insert(0, "合同外利益")

    if "虚假宣传" in out and any(k in blob for k in ("电销", "电话销售", "电话营销")):
        out = [t for t in out if t != "虚假宣传"]
        if "销售误导" not in out:
            out.append("销售误导")

    if blob and _INDUCE_RE.search(blob) and "诱导投保" not in out:
        out.append("诱导投保")

    person_unlicensed = bool(blob and _PERSON_UNLICENSED_RE.search(blob))
    inst_unlicensed = bool(blob and _INST_UNLICENSED_RE.search(blob))
    if person_unlicensed:
        if "代理人管理不到位" not in out:
            out.append("代理人管理不到位")
        if "委托无资质机构销售" in out and not inst_unlicensed:
            out = [t for t in out if t != "委托无资质机构销售"]
    if "委托无资质机构销售" in out and "投资理财" in blob and not inst_unlicensed:
        out = [t for t in out if t != "委托无资质机构销售"]
        if "其他" not in out:
            out.append("其他")

    if blob and _GUARANTEE_RE.search(blob) and "保证收益" not in out:
        out.append("保证收益")

    if blob and _ABS_EXPR_RE.search(blob) and "绝对化表述" not in out:
        out.append("绝对化表述")
    elif blob and "绝对化表述" in out and not _ABS_EXPR_RE.search(blob):
        out = [t for t in out if t != "绝对化表述"]

    if blob and _FICTIVE_YIELD_RE.search(blob) and "虚构收益率" not in out:
        out.append("虚构收益率")
    elif blob and "虚构收益率" in out and not _FICTIVE_YIELD_RE.search(blob):
        out = [t for t in out if t != "虚构收益率"]

    if "弱化风险提示" in out and blob and not _WEAKEN_RE.search(blob):
        out = [t for t in out if t != "弱化风险提示"]
    if blob and _FAKE_CLIENT_RE.search(blob) and "客户信息不真实" not in out:
        out.append("客户信息不真实")
    elif "客户信息不真实" in out and blob and not _FAKE_CLIENT_RE.search(blob):
        out = [t for t in out if t != "客户信息不真实"]
        if _OTHER_HINT_RE.search(blob) and "其他" not in out and len(out) <= 1:
            out.append("其他")

    need_deceive = bool(blob and _DECEIVE_APPLICANT_RE.search(blob)) or any(
        t in out for t in ("绝对化表述", "虚构收益率")
    )
    if need_deceive and "欺骗投保人" not in out:
        out.insert(0, "欺骗投保人")

    return normalize_cn_tags(out)


def normalize_cn_tags_detailed(tags: list[str] | None) -> list[dict]:
    """带复核状态的标准化：无法识别时标记 needs_review，不静默丢弃原始标签。"""
    if not tags:
        return []
    out: list[dict] = []
    seen_norm: set[str] = set()
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
            mapped = _expand_one_tag(part)
            if mapped:
                for tag in mapped:
                    if tag not in seen_norm:
                        seen_norm.add(tag)
                        out.append({
                            "raw_label": part,
                            "normalized_label": tag,
                            "status": "ok",
                        })
            else:
                out.append({
                    "raw_label": part,
                    "normalized_label": None,
                    "status": "needs_review",
                })
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


def predict_cn_tags_by_keywords(text: str, *, max_tags: int = 3) -> list[str]:
    """基于关键词词典初判中文风险标签；按命中词长度计分，优先细粒度标签。"""
    scored: list[tuple[int, str]] = []
    for tag, keywords in _merged_keyword_map().items():
        best = 0
        for kw in keywords:
            try:
                m = re.search(kw, text)
                hit = bool(m)
                span = len(m.group(0)) if m else 0
            except re.error:
                hit = kw in text
                span = len(kw) if hit else 0
            if hit:
                best = max(best, span if span >= 2 else len(kw.replace(".*", "")))
        if best > 0:
            # 更长命中优先；同长度时细粒度标签名更长者优先
            scored.append((best * 10 + min(len(tag), 9), tag))
    scored.sort(key=lambda x: x[0], reverse=True)
    hits = [t for _, t in scored]
    hits = list(dict.fromkeys(hits))
    hits = _apply_exclusion_boundaries(text, hits)
    return hits[:max_tags]


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
