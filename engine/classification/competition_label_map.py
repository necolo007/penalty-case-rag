"""28 类中文 risk_tag 与赛题 R001–R011 的映射（双层）。

第一层（官方输出）：28 类中文细标签 —— 展示、提交、评测、训练。
第二层（内部召回）：写入 risk_type_dictionary.csv 中的 risk_type_R00；
  「编制虚假财务资料」为独立细标签，对应 R006（禁止落到虚列 R005）。

CSV 典型行为/排除边界参与关键词预测与消歧；risk_type / risk_type_R00 为竞赛粗类。
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
    "编制虚假财务资料",
    "其他",
)

CANONICAL_CN_TAG_SET = frozenset(CANONICAL_CN_TAGS)

# 与配套数据 risk_type_dictionary.csv 的 risk_type_R00 对齐（R001–R011）
CN_TAG_TO_COMPETITION: dict[str, str] = {
    "欺骗投保人": "R001",
    "销售误导": "R001",
    "夸大收益": "R001",
    "承诺收益": "R001",
    "保证收益": "R001",
    "弱化风险提示": "R001",
    "隐瞒重要信息": "R001",
    "电销违规": "R001",
    "不当比较": "R001",
    "贬低竞品": "R001",
    "诱导投保": "R001",
    "合同外利益": "R002",
    "赠送利益": "R002",
    "回扣返佣": "R002",
    "虚假宣传": "R003",
    "产品说明会违规": "R003",
    "绝对化表述": "R003",
    "虚构收益率": "R003",
    "避债避税": "R003",
    "代理人管理不到位": "R004",
    "委托无资质机构销售": "R004",
    "虚列费用套取资金": "R005",
    "回访违规": "R007",
    "客户信息不真实": "R008",
    "未按规定使用费率条款": "R009",
    "培训材料违规": "R010",
    "编制虚假财务资料": "R006",
    "其他": "R011",
}

# 粗类中文名（导航/展示；来自配套 risk_type 列）
CN_TAG_RISK_TYPE: dict[str, str] = {
    "欺骗投保人": "销售误导",
    "销售误导": "销售误导",
    "夸大收益": "销售误导",
    "承诺收益": "销售误导",
    "保证收益": "销售误导",
    "弱化风险提示": "销售误导",
    "隐瞒重要信息": "销售误导",
    "电销违规": "销售误导",
    "不当比较": "销售误导",
    "贬低竞品": "销售误导",
    "诱导投保": "销售误导",
    "合同外利益": "合同外利益",
    "赠送利益": "合同外利益",
    "回扣返佣": "合同外利益",
    "虚假宣传": "宣传材料不真实",
    "产品说明会违规": "宣传材料不真实",
    "绝对化表述": "宣传材料不真实",
    "虚构收益率": "宣传材料不真实",
    "避债避税": "宣传材料不真实",
    "代理人管理不到位": "销售人员职业登记管理不规范",
    "委托无资质机构销售": "销售人员职业登记管理不规范",
    "虚列费用套取资金": "虚挂中介费用套取资金",
    "回访违规": "售后服务违规",
    "客户信息不真实": "客户信息与隐私违规",
    "未按规定使用费率条款": "产品费率及合同执行违规",
    "培训材料违规": "内部管理与培训违规",
    "编制虚假财务资料": "编制虚假财务资料",
    "其他": "其他类型违规行为",
}

COMPETITION_TO_CN_DEFAULT: dict[str, str] = {
    "R001": "销售误导",
    "R002": "合同外利益",
    "R003": "虚假宣传",
    "R004": "代理人管理不到位",
    "R005": "虚列费用套取资金",
    "R006": "编制虚假财务资料",
    "R007": "回访违规",
    "R008": "客户信息不真实",
    "R009": "未按规定使用费率条款",
    "R010": "培训材料违规",
    "R011": "其他",
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
    # 编制虚假财务资料 ≠ 虚列套取；归一到独立细类 R006
    "编制虚假财务资料": ["编制虚假财务资料"],
    "编制虚假业务资料": ["编制虚假财务资料"],
    "编制虚假财务数据": ["编制虚假财务资料"],
    "编制提交虚假报表": ["编制虚假财务资料"],
    "业务财务数据不真实": ["编制虚假财务资料"],
    "财务数据不真实": ["编制虚假财务资料"],
    "保险代理人侵害消费者权益": ["其他"],
    "利用开展保险业务牟取不正当利益": ["其他"],
    "销售违规": ["销售误导"],
    "消费者权益保护": ["其他"],
    "误导": ["销售误导"],
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
    "诱导投保": ["诱导投保", "限时抢购", "名额有限", "限时限额", "即将停售", "并未停售"],
    "避债避税": ["避债", "避税", "规避债务", "收益免税"],
    "回访违规": [
        "阻碍.*回访", "阻挠.*回访", "回访过程中", r"回访.{0,6}(?:问题|电话)",
        r"诱导.{0,10}回访", "回访对象非", "回访记录",
    ],
    "虚列费用套取资金": ["虚列费用", "套取费用", "虚假列支", "虚挂中介"],
    "代理人管理不到位": [
        "代理人管理", "执业登记", "资格证书", "执业证书", "展业证", "未按规定进行执业",
        "职业登记管理不规范", "对代理人培训不到位",
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
    """从 CSV 读取 28 类标签目录（含典型行为/排除边界/监管依据/R00x）；失败时回退内置常量。"""
    if _DICT_PATH.exists():
        rows: list[dict[str, str]] = []
        with _DICT_PATH.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                tag = (row.get("risk_tag") or "").strip()
                if not tag or tag not in CANONICAL_CN_TAG_SET:
                    continue
                csv_cid = _row_field(row, "risk_type_R00", "competition_id").upper()
                if csv_cid and not re.fullmatch(r"R0\d{2}", csv_cid):
                    csv_cid = ""
                rows.append({
                    "risk_tag": tag,
                    "description": _row_field(row, "description"),
                    "typical_behavior": _row_field(row, "典型行为", "typical_behavior"),
                    "exclusion_boundary": _row_field(row, "排除边界", "exclusion_boundary"),
                    "legal_basis": _row_field(row, "监管依据", "legal_basis"),
                    "category": _row_field(row, "category"),
                    "risk_type": _row_field(row, "risk_type") or CN_TAG_RISK_TYPE.get(tag, ""),
                    "competition_id": csv_cid or CN_TAG_TO_COMPETITION.get(tag, ""),
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
            "risk_type": CN_TAG_RISK_TYPE.get(t, ""),
            "competition_id": CN_TAG_TO_COMPETITION.get(t, ""),
        }
        for t in CANONICAL_CN_TAGS
    ]


@lru_cache(maxsize=1)
def competition_id_from_cn_tag(tag: str) -> str:
    """优先读 CSV 目录中的 R00x，回退内置映射。"""
    by_tag = {r["risk_tag"]: r for r in load_cn_tag_catalog()}
    row = by_tag.get(tag) or {}
    return (row.get("competition_id") or CN_TAG_TO_COMPETITION.get(tag, "") or "").strip()


def cn_tags_to_competition_ids(tags: list[str] | None) -> list[str]:
    """中文 risk_tags → 去重后的 R00x 列表（内部召回）。"""
    ids: list[str] = []
    for tag in normalize_cn_tags(tags):
        cid = competition_id_from_cn_tag(tag)
        if cid and cid not in ids:
            ids.append(cid)
    return ids


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
    """将任意标签/别名/R00x/复合写法归一为 28 类标准标签。"""
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
    r"欺骗投保人|欺骗被保险人|欺骗受益人|私印保单|隐瞒投保人|"
    r"不履行.{0,30}如实告知|诱导投保人不履行"
)
_FAKE_STOP_SALE_RE = re.compile(
    r"即将停售|实际并未停售|从未停售|并未停售|以即将停售为由|"
    r"停售等情况作虚假宣传|对保险产品价格、停售|以产品升级名义诱导"
)
_INDUCE_RE = re.compile(
    r"限时抢购|名额有限|限时限额|即将停售|并未停售|"
    r"停售等情况作虚假宣传|以产品升级名义诱导"
)
_PERSON_UNLICENSED_RE = re.compile(
    r"(?:未取得|没有|无).{0,8}(?:资格证|执业证|展业证|资格证书|执业证书)|"
    r"无资格证|无执业证|无展业证|未按规定进行执业|执业登记|"
    r"执业证书人员|无资格证书.{0,8}人员|人员从事保险销售"
)
_INST_UNLICENSED_RE = re.compile(
    r"委托.{0,40}(?:无资质|不具备资质|未取得.{0,16}资质).{0,24}"
    r"(?:机构|公司|平台).{0,20}(?:销售|代理)|"
    r"与无资质的第三方|代理机构业务台账|台账要素不齐"
)
_TELESALES_RE = re.compile(r"电销|电话销售|电话营销|电话业务销售|销售录音")
# 银行/存款名义卖保险 → 销售误导（含「存款赠送保险」等，勿只认「银行存款」四字）
_BANK_MISLEAD_RE = re.compile(
    r"销售误导|错误解释保险责任|银行存款|储蓄计划|以银行.{0,8}名义|"
    r"存款赠送|存款送保险|以存款|像存款|存钱送|把保险当存款|"
    r"换个地方存钱|换种方式存储|换个方式存储|"
    r"银行理财名义|以理财名义|混淆.{0,8}存款|"
    r"以(?:银行存款|银行理财|储蓄|理财).{0,12}(?:名义|形式).{0,20}(?:宣传|销售|介绍)|"
    r"(?:购买保险|买保险|投保).{0,12}(?:宣传为|说成|称为).{0,8}(?:存钱|存款|储蓄)|"
    r"片面.{0,12}(?:解释|介绍|说明).{0,12}(?:条款|责任)"
)
_FAKE_GIFT_RE = re.compile(r"虚假宣传赠送|宣传赠送.{0,24}并未|实际并未赠送|并未赠送")
_REAL_EXTRA_INTEREST_RE = re.compile(
    r"合同约定以外|合同外利益|回扣|返佣|赠送油卡|赠送体检|赠送礼品|赠送洗车"
)
_WEAKEN_RE = re.compile(r"不用担心|零风险|无风险|完全无风险|忽略免责|免责.{0,8}不重要|一定赔")
_FAKE_CLIENT_RE = re.compile(
    r"客户信息不真实|客户行为不真实|"
    r"代签|代为签名|代投保人签名|代替投保人|客户签名代签|"
    r"代抄风险提示|笔迹与签名不一致|"
    r"代为抄写|抄录风险提示|抄录笔迹|"
    r"客户(?:电话|地址|联系方式).{0,8}不真实|"
    r"投保人.{0,12}信息不真实|被保险人.{0,12}信息不真实|"
    r"被保险人信息资料不真实|没有被保险人.{0,8}信息|无被保险人.{0,8}信息|"
    r"信息记录虚假|客户信息.{0,8}虚假|客户信息资料不真实|"
    r"回访记录造假|回访对象非|回访均不成功|"
    r"变更客户信息|更改.{0,12}电话号码|联系方式变更为|"
    r"虚构投保农户|虚假客户"
)
# 代理人入职/档案材料代签 → 勿打「客户信息不真实」
_AGENT_ARCHIVE_SIGN_RE = re.compile(
    r"(?:代理人|营销员|从业人员|入职|执业).{0,24}(?:档案|材料|资料).{0,24}代签|"
    r"代签.{0,24}(?:代理人|营销员).{0,16}(?:档案|材料|资料)|"
    r"入职档案.{0,16}代签|档案材料.{0,12}代签"
)
_OTHER_HINT_RE = re.compile(
    r"任职资格|未取得.{0,16}核准|牟取不正当利益|"
    r"保险资金委托|投资理财|问题档案|自查报告|"
    r"内控制度.{0,8}不到位|拒绝.{0,8}监督检查|妨碍监督检查|"
    r"唆使.{0,12}代理人.{0,16}诚信|隐瞒事实"
)
_GUARANTEE_RE = re.compile(
    r"保证年化|保证收益率|保证收益\d|保证.{0,8}\d+(?:\.\d+)?\s*%|"
    r"固定利息\s*\d|固定利息.{0,12}%|"
    r"复利分红\s*\d|日复利滚息|"
    r"分红\s*\d+\s*万|回报金额|保证回报|"
    r"(?:年化|收益|分红|利息).{0,6}\d+(?:\.\d+)?\s*%.{0,8}保证|"
    r"保证.{0,12}(?:年化|收益|分红|利息).{0,8}\d"
)
_INDUCE_NOT_DISCLOSE_RE = re.compile(r"诱导投保人不履行|不履行.{0,20}如实告知")
_PRODUCT_MEETING_RE = re.compile(r"产品说明会|产说会")
_TRAINING_MATERIAL_RE = re.compile(
    r"培训(?:材料|课件|PPT|话术)|营销员培训|个险营销员培训|培训用.{0,8}课件"
)
_FAKE_EXPENSE_DETAIL_RE = re.compile(
    r"虚列|虚构.{0,16}(?:费用|业务)|虚假列支|虚挂中介"
)
_SIPHON_OR_MISUSE_RE = re.compile(
    r"套取(?:费用|资金)|贴补手续费|"
    r"(?:用于|转入|支付|发放|拨付).{0,24}(?:手续费|奖励|返佣|补贴|福利|展业)|"
    r"假发票|虚假报销|虚假赔案|与列支名目不符"
)
_FAKE_REPORT_ONLY_RE = re.compile(
    r"营业费用核算不真实|费用列支不规范|会计记录不实|"
    r"业务财务数据不真实|编制提交虚假报表|编制虚假报表|编制虚假财务资料|"
    r"财务数据不真实|业务资料不真实"
)
_PROMISE_RATIO_RETURN_RE = re.compile(r"按比例返还保费|比例返还保费|承诺.{0,8}返还保费")
_SELF_PRINT_FLYER_RE = re.compile(r"自印宣传单|自印.{0,6}宣传单")
_STAFF_EXTRA_INTEREST_RE = re.compile(
    r"给予.{0,16}(?:工作人员|员工|营销员|代理人|保险机构).{0,24}"
    r"(?:合同外|约定以外|额外).{0,8}利益|"
    r"(?:工作人员|员工).{0,12}合同约定以外"
)


def refine_cn_tags(tags: list[str] | None, violation_behavior: str = "") -> list[str]:
    """对齐口径：停售类保留诱导投保；人员无证≠无资质机构；未兑现赠送≠合同外利益。"""
    out = normalize_cn_tags(tags)
    blob = violation_behavior or ""

    if blob and _FAKE_GIFT_RE.search(blob):
        out = [t for t in out if t != "赠送利益"]
        if "合同外利益" in out and not _REAL_EXTRA_INTEREST_RE.search(blob):
            out = [t for t in out if t != "合同外利益"]
        if "欺骗投保人" not in out:
            out.insert(0, "欺骗投保人")

    if blob and _STAFF_EXTRA_INTEREST_RE.search(blob) and "合同外利益" in out:
        # 给予机构/工作人员的合同外利益 ≠ 给予投保人的合同外利益
        if not re.search(r"投保人|被保险人|客户", blob):
            out = [t for t in out if t != "合同外利益"]

    if any(t in out for t in ("赠送利益", "回扣返佣")) and "合同外利益" not in out:
        out.insert(0, "合同外利益")

    if blob and _PROMISE_RATIO_RETURN_RE.search(blob) and "合同外利益" in out:
        # 承诺按比例返还保费 ≠ 给予投保人合同外利益（8.23 口径）
        out = [t for t in out if t != "合同外利益"]

    if blob and _TELESALES_RE.search(blob):
        mislead_hit = bool(_BANK_MISLEAD_RE.search(blob))
        induce_like = bool(_FAKE_STOP_SALE_RE.search(blob) or _INDUCE_RE.search(blob))
        if "虚假宣传" in out:
            out = [t for t in out if t != "虚假宣传"]
        if mislead_hit and "销售误导" not in out:
            out.append("销售误导")
        if "电销违规" not in out:
            out.append("电销违规")
        if induce_like and "销售误导" in out and not mislead_hit:
            out = [t for t in out if t != "销售误导"]

    # 非电销场景的存款/银行名义卖保险，同样补销售误导
    if blob and _BANK_MISLEAD_RE.search(blob) and "销售误导" not in out:
        out.append("销售误导")
    # 诱导不履行如实告知 → 欺骗投保人，不是诱导投保
    if blob and _INDUCE_NOT_DISCLOSE_RE.search(blob):
        if "欺骗投保人" not in out:
            out.insert(0, "欺骗投保人")
        if "诱导投保" in out and not (_FAKE_STOP_SALE_RE.search(blob) or _INDUCE_RE.search(blob)):
            out = [t for t in out if t != "诱导投保"]

    if blob and (_FAKE_STOP_SALE_RE.search(blob) or _INDUCE_RE.search(blob)):
        if "诱导投保" not in out:
            out.append("诱导投保")
        if _FAKE_STOP_SALE_RE.search(blob) and "欺骗投保人" not in out:
            out.insert(0, "欺骗投保人")

    if blob and _PRODUCT_MEETING_RE.search(blob) and "产品说明会违规" not in out:
        if re.search(r"管理不到位|违规|误导|虚假|未经备案|未按规定", blob):
            out.append("产品说明会违规")
    # 仅「产说会管理不到位」等笼统表述：保留产品说明会违规，不叠销售误导
    if (
        blob
        and _PRODUCT_MEETING_RE.search(blob)
        and re.search(r"管理不到位", blob)
        and "销售误导" in out
        and not re.search(r"销售误导行为|错误解释|银行存款|储蓄计划|片面", blob)
    ):
        out = [t for t in out if t != "销售误导"]

    if blob and _TRAINING_MATERIAL_RE.search(blob):
        if "培训材料违规" not in out and re.search(r"虚假宣传|误导|绝对化|不实", blob):
            out.append("培训材料违规")
        # 培训课件中的「虚假宣传」不是对客户的产品虚假宣传
        if "虚假宣传" in out and not re.search(
            r"宣传单|海报|公众号|短视频|对外宣传|广告|自印",
            blob,
        ):
            out = [t for t in out if t != "虚假宣传"]

    if blob and _SELF_PRINT_FLYER_RE.search(blob) and "虚假宣传" not in out:
        if not _TRAINING_MATERIAL_RE.search(blob):
            out.append("虚假宣传")

    person_unlicensed = bool(blob and _PERSON_UNLICENSED_RE.search(blob))
    inst_unlicensed = bool(blob and _INST_UNLICENSED_RE.search(blob))
    person_sales = bool(re.search(r"人员|营销员|从业人员|个人代理人", blob))
    if person_unlicensed or (person_sales and re.search(r"资格证|执业证|展业证", blob)):
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
        # 有具体数字/金额的保证时，优先保证收益而非夸大收益
        if "夸大收益" in out and not re.search(r"夸大收益|夸张|推测", blob):
            out = [t for t in out if t != "夸大收益"]

    if blob and "虚列费用套取资金" in out:
        has_xulie = bool(_FAKE_EXPENSE_DETAIL_RE.search(blob))
        has_misuse = bool(_SIPHON_OR_MISUSE_RE.search(blob))
        accounting_only = bool(_FAKE_REPORT_ONLY_RE.search(blob)) and not (has_xulie and has_misuse)
        xulie_without_misuse = has_xulie and not has_misuse
        if accounting_only or xulie_without_misuse:
            out = [t for t in out if t != "虚列费用套取资金"]
            if "编制虚假财务资料" not in out:
                out.append("编制虚假财务资料")

    if blob and _FAKE_REPORT_ONLY_RE.search(blob):
        has_xulie = bool(_FAKE_EXPENSE_DETAIL_RE.search(blob))
        has_misuse = bool(_SIPHON_OR_MISUSE_RE.search(blob))
        if not (has_xulie and has_misuse) and "编制虚假财务资料" not in out:
            out.append("编制虚假财务资料")

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

    fake_client_ok = bool(
        blob
        and _FAKE_CLIENT_RE.search(blob)
        and not _AGENT_ARCHIVE_SIGN_RE.search(blob)
    )
    # 裸「代签」且落在代理人档案语境时不算客户信息不真实
    if "客户信息不真实" in out and blob and _AGENT_ARCHIVE_SIGN_RE.search(blob):
        if not re.search(r"投保人|被保险人|客户签名|回访|客户电话|客户地址", blob):
            out = [t for t in out if t != "客户信息不真实"]
            fake_client_ok = False
    if fake_client_ok and "客户信息不真实" not in out:
        out.append("客户信息不真实")
    elif "客户信息不真实" in out and blob and not fake_client_ok and not _FAKE_CLIENT_RE.search(blob):
        out = [t for t in out if t != "客户信息不真实"]
        if _OTHER_HINT_RE.search(blob) and "其他" not in out and len(out) <= 1:
            out.append("其他")

    need_deceive = bool(blob and _DECEIVE_APPLICANT_RE.search(blob)) or any(
        t in out for t in ("绝对化表述", "虚构收益率")
    )
    if need_deceive and "欺骗投保人" not in out:
        out.insert(0, "欺骗投保人")

    # 仅「存款/银行名义」混淆产品属性 → 销售误导，不要升格为欺骗投保人
    if (
        blob
        and "欺骗投保人" in out
        and _BANK_MISLEAD_RE.search(blob)
        and not _DECEIVE_APPLICANT_RE.search(blob)
        and not _ABS_EXPR_RE.search(blob)
        and not _FICTIVE_YIELD_RE.search(blob)
        and not _FAKE_STOP_SALE_RE.search(blob)
        and not _FAKE_GIFT_RE.search(blob)
    ):
        out = [t for t in out if t != "欺骗投保人"]

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
