"""字段抽取正则模式库。"""

import re
from pathlib import Path


def _sp(label: str) -> str:
    """构造允许字间夹杂空白的标签正则。

    OCR/PDF 抽取的公示表表头常见逐字加空格（如「受 处 罚 单 位 名 称」），
    若按字面量精确匹配会导致标签整体 NOMATCH。对标签中每个字符之间插入
    可选空白（含全角空格），内容字符本身不受影响。
    """
    return r"[ \t\u3000]*".join(re.escape(ch) for ch in label)


# 违法事实描述常跨多行（OCR/PDF 逐行断行），需用 [\s\S] 跨行匹配；
# 用以下"转折短语"作为终止边界（进入法律依据/处罚决定部分即停止），
# 避免把处罚依据、处罚决定文字也吞进 violation_behavior。
_VIOLATION_STOP = (
    r"(?:"
    r"你(?:公司|单位|机构)?[^\n]{0,20}(?:上述行为)?违反"
    r"|上述(?:行为|事实)(?:[，,])?(?:已)?违反"
    r"|违反(?:了)?《"
    r"|已构成[^\n]{0,10}(?:情形|行为)"
    r"|根据《"
    r"|依据《"
    r"|依照《"
    r"|我(?:会|局|处|厅)(?:认为|决定|拟)"
    r"|本机关(?:认为|决定)"
    r"|经研究决定"
    r"|经审议决定"
    r"|综上"
    r")"
)

_PARTY_LABEL = (
    r"(?:" + _sp("当事人名称") + r"|" + _sp("当事人单位名称") + r"|" + _sp("当事人单位") + r"|"
    + _sp("当事人") + r"|" + _sp("受处罚单位名称") + r"|" + _sp("受处罚单位") + r"|"
    + _sp("受处罚人") + r"|" + _sp("被处罚人") + r")"
)

_VIOLATION_LABEL = (
    r"(?:" + _sp("主要违法违规事实") + r"|" + _sp("主要违法违规行为") + r"|"
    + _sp("违法违规事实") + r"|" + _sp("违法违规行为") + r"|"
    + _sp("违法事实") + r"|" + _sp("违法行为") + r"|"
    + _sp("违规事实") + r"|" + _sp("违规行为") + r")"
)

_PENALTY_LABEL = (
    r"(?:" + _sp("行政处罚决定") + r"|" + _sp("行政处罚内容") + r"|" + _sp("行政处罚意见") + r"|"
    + _sp("处罚决定") + r"|" + _sp("处罚内容") + r"|" + _sp("处罚意见") + r")"
)

_REGULATOR_LABEL = (
    r"(?:" + _sp("作出处罚决定的机关名称") + r"|" + _sp("作出处罚决定的机关") + r"|"
    + _sp("处罚机关") + r"|" + _sp("决定机关") + r"|" + _sp("作出机关") + r")"
)

PATTERNS = {
    "penalty_doc_no": re.compile(
        r"([\u4e00-\u9fff]{0,8}(?:金罚决字|罚决字|银保监罚决字|银保监罚|保监罚决字|保监罚|罚字)"
        r"[〔\[（(]\d{4}[〕\]）)]\s*第?\s*\d+\s*号)"
    ),

    # 当事人：覆盖决定书/公示表多种写法，标签本身容忍逐字空格（OCR 表头常见）。
    # 排除逗号：公示表常紧跟「，地址XX，负责人XX」，逗号后不属于主体名称。
    "party_name": re.compile(
        _PARTY_LABEL + r"[：:\s]*([^\n。；;，,]{2,80})"
    ),
    "party_name_alt": re.compile(
        r"(?:经查[，,]?\s*|对)([\u4e00-\u9fffA-Za-z0-9（）()]{4,60}?"
        r"(?:保险|人寿|财险|产险)[\u4e00-\u9fffA-Za-z0-9（）()]{0,40}"
        r"(?:公司|支公司|分公司|中心支公司))"
    ),

    # 主分支：懒惰匹配至转折短语（跨行）；找不到转折短语则退化为定长跨行截取，
    # 保证长文本仍能抓到完整违法事实枚举（而不是被首个换行截断为几个字）。
    "violation_behavior": re.compile(
        _VIOLATION_LABEL + r"(?:[（(][^）)]*[）)])?[：:]\s*"
        r"(?:([\s\S]{10,1200}?)(?=" + _VIOLATION_STOP + r")|([\s\S]{10,700}))"
    ),
    "violation_behavior_alt": re.compile(
        r"(?:存在(?:以下|下列)?(?:违法|违规)行为[：:]?\s*|经查[，,]?\s*)"
        r"(?:([\s\S]{8,1200}?)(?=" + _VIOLATION_STOP + r")|([\s\S]{8,500}))"
    ),

    "penalty_content": re.compile(
        _PENALTY_LABEL + r"[：:]\s*([^\n]{1,400})"
    ),
    # 处罚决定句常跨行且以「。」收尾，用 [^。] 天然跨行、并锚定在具体处罚动作词上，
    # 避免吞并前面的违法事实枚举。
    "penalty_content_alt": re.compile(
        r"((?:我(?:会|局|处|厅)|本机关|经研究决定|经审议决定)?[^。]{0,20}?"
        r"(?:决定(?:给予|对)?|给予|处以|责令)[^。]{0,30}?"
        r"(?:罚款|警告|没收违法所得|吊销(?:业务)?许可证|暂停[^。]{0,10}业务)[^。]{0,120}。)"
    ),

    "fine_amount": re.compile(
        r"罚款\s*(?:人民币)?\s*([\d,.]+\s*(?:万|千|百)?\s*元)"
    ),

    "regulator": re.compile(
        _REGULATOR_LABEL + r"[：:\s]*([\u4e00-\u9fff]{4,50}?(?:监管局|监管分局|银保监局|金融监督管理总局"
        r"[\u4e00-\u9fff]{0,12}|保监局|银保监会|保监会))"
    ),

    "regulator_inline": re.compile(
        r"(国家金融监督管理总局[\u4e00-\u9fff]{0,12}(?:监管局|监管分局)?"
        r"|中国银保监会[\u4e00-\u9fff]{0,10}(?:监管局|监管分局)?"
        r"|[\u4e00-\u9fff]{2,10}银保监局(?:[\u4e00-\u9fff]{0,8}分局)?"
        r"|[\u4e00-\u9fff]{2,8}保监局"
        r"|中国银保监会|中国保监会)"
    ),

    "publish_date": re.compile(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
    ),

    "legal_basis": re.compile(
        r"((?:依据|根据)\s*《[^》]{2,40}》[^\n。；;]{0,100})"
    ),
}

# 文号地域字 → 常见监管机关简称（用于 regulator 缺失时兜底）
_DOCNO_REGION_PATH = Path(__file__).resolve().parents[2] / "data" / "dictionaries" / "docno_region_regulator.csv"

_BUILTIN_DOCNO_REGION_REGULATOR = {
    "京": "北京银保监局",
    "沪": "上海银保监局",
    "津": "天津银保监局",
    "渝": "重庆银保监局",
    "粤": "广东银保监局",
    "鲁": "山东银保监局",
    "苏": "江苏银保监局",
    "浙": "浙江银保监局",
    "闽": "福建银保监局",
    "湘": "湖南银保监局",
    "鄂": "湖北银保监局",
    "豫": "河南银保监局",
    "冀": "河北银保监局",
    "晋": "山西银保监局",
    "陕": "陕西银保监局",
    "甘": "甘肃银保监局",
    "青": "青海银保监局",
    "宁": "宁夏银保监局",
    "新": "新疆银保监局",
    "藏": "西藏银保监局",
    "川": "四川银保监局",
    "黔": "贵州银保监局",
    "滇": "云南银保监局",
    "桂": "广西银保监局",
    "琼": "海南银保监局",
    "赣": "江西银保监局",
    "皖": "安徽银保监局",
    "辽": "辽宁银保监局",
    "吉": "吉林银保监局",
    "黑": "黑龙江银保监局",
    "蒙": "内蒙古银保监局",
}


def _load_docno_region_regulator() -> dict[str, str]:
    if _DOCNO_REGION_PATH.exists():
        import csv
        loaded: dict[str, str] = {}
        with _DOCNO_REGION_PATH.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                region = (row.get("region") or "").strip()
                regulator = (row.get("regulator") or "").strip()
                if region and regulator:
                    loaded[region] = regulator
        if loaded:
            return loaded
    return dict(_BUILTIN_DOCNO_REGION_REGULATOR)


DOCNO_REGION_REGULATOR = _load_docno_region_regulator()

INSURANCE_KEYWORDS = [
    "人寿保险", "财产保险", "健康保险", "养老保险",
    "保险股份", "相互保险", "再保险", "保险代理",
    "保险经纪", "保险公估", "保险销售",
]

NON_INSURANCE_KEYWORDS = [
    "银行股份", "农村商业银行", "城市商业银行",
    "消费金融", "金融租赁", "信托",
]

INSTITUTION_TYPE_RULES = [
    ("人寿保险|寿险", "寿险公司"),
    ("财产保险|财险|产险", "财险公司"),
    ("保险代理|保险经纪|保险公估|保险销售", "保险代理/中介"),
    ("分公司|支公司|营业部|营销服务部", "保险分支机构"),
]
