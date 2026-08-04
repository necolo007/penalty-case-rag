"""OCR 文本后处理：修复「逐字重复」等扫描件识别噪声。

典型现象（公示表/扫描 PDF）：
  行行政政处处罚罚决决定定书书文文号号 → 行政处罚决定书文号
  主主要要违违法法违违规规事事实实(案案由由) → 主要违法违规事实(案由)

策略：
  1. 按行估计「汉字成对重复」比例，超过阈值则对该行做 CJK 成对折叠；
  2. 折叠后修补被拆断的标签与跨行公司名；
  3. 压缩汉字间孤立空格，保留换行结构。
"""

from __future__ import annotations

import re

# 连续相同汉字折叠一轮（行行政政 → 行政政；循环至稳定）
_DOUBLE_CJK = re.compile(r"([\u4e00-\u9fff])\1")

# 折叠后：公示表把「被处罚当事人」拆成多行单元格
_PARTY_LABEL_SPLIT = re.compile(
    r"被处罚当\s*(.*?)\s*\n\s*名称\s*\n\s*事人\s*(?:单\s*)?(.*?)\s*\n\s*位",
    re.S,
)
_PARTY_LABEL_SPLIT_SHOU = re.compile(
    r"受处罚当\s*(.*?)\s*\n\s*名称\s*\n\s*事人\s*(?:单\s*)?(.*?)\s*\n\s*位",
    re.S,
)

_LABEL_REPAIRS: list[tuple[re.Pattern[str], str]] = [
    (_PARTY_LABEL_SPLIT, r"被处罚当事人 \1\2"),
    (_PARTY_LABEL_SPLIT_SHOU, r"受处罚当事人 \1\2"),
    (re.compile(r"被处罚当\s*名称?\s*事人\s*单?\s*位?"), "被处罚当事人"),
    (re.compile(r"受处罚当\s*名称?\s*事人\s*单?\s*位?"), "受处罚当事人"),
    (re.compile(r"被处罚当\s*事人"), "被处罚当事人"),
    (re.compile(r"受处罚当\s*事人"), "受处罚当事人"),
    # 公司名被拆成「…北京\n市宣武支公司」
    (
        re.compile(
            r"(公司(?:北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|"
            r"安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|"
            r"陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆)?)\s*\n\s*(市|区|县)"
        ),
        r"\1\2",
    ),
]


def _cjk_double_ratio(line: str) -> float:
    """统计行内「相邻相同汉字」占汉字量的比例（成对重复越严重越高）。"""
    cjk_idxs = [i for i, ch in enumerate(line) if "\u4e00" <= ch <= "\u9fff"]
    if len(cjk_idxs) < 4:
        return 0.0
    doubles = 0
    for i in range(len(line) - 1):
        a, b = line[i], line[i + 1]
        if a == b and "\u4e00" <= a <= "\u9fff":
            doubles += 1
    # 每个成对重复贡献 2 个汉字位置
    return min(1.0, (2.0 * doubles) / len(cjk_idxs))


def _collapse_doubled_cjk(line: str) -> str:
    prev = None
    cur = line
    # 最多折叠若干轮，避免极端输入死循环
    for _ in range(8):
        if prev == cur:
            break
        prev = cur
        cur = _DOUBLE_CJK.sub(r"\1", cur)
    return cur


# 连续 ≥3 组成对汉字（行行政政处处…），局部折叠；避免误伤「谢谢」「妈妈」
_PAIR_RUN = re.compile(r"(([\u4e00-\u9fff])\2){3,}")


def _collapse_local_pair_runs(line: str) -> str:
    """折叠行内连续成对重复片段（标签被 OCR 逐字加倍时常见）。"""
    return _PAIR_RUN.sub(lambda m: _collapse_doubled_cjk(m.group(0)), line)


def _repair_labels(text: str) -> str:
    out = text
    for pat, repl in _LABEL_REPAIRS:
        out = pat.sub(repl, out)
    return out


def _collapse_spaces_in_cjk_runs(text: str) -> str:
    """去掉汉字之间的孤立空格（受 处 罚 → 受处罚），保留换行。"""
    return re.sub(r"(?<=[\u4e00-\u9fff])[ \t　]+(?=[\u4e00-\u9fff])", "", text)


# 压空格后标签常与内容粘连，补回分隔便于下游正则
_FIELD_LABEL_SEP = re.compile(
    r"(行政处罚决定书文号|被处罚当事人|受处罚当事人|被处罚单位|受处罚单位|"
    r"主要违法违规事实(?:[（(][^）)\n]*[）)])?|主要违法违规行为|"
    r"行政处罚依据|行政处罚决定|行政处罚内容|"
    r"作出处罚决定的机关名称|作出处罚决定的日期|"
    r"个人姓名|主要负责人)"
    r"(?=[\u4e00-\u9fff0-9《责给处作我本经])"
)

# 公示表 OCR 常把编号事实行排在「主要违法违规事实」标签之前
_VIOLATION_ITEMS_BEFORE_LABEL = re.compile(
    r"(?m)((?:^\d+[\.、．][^\n]*\n)+)"
    r"(主要违法违规事实(?:[（(][^）)\n]*[）)])?[：:]?)\n"
)


def _ensure_label_separators(text: str) -> str:
    return _FIELD_LABEL_SEP.sub(r"\1 ", text)


def _reorder_violation_items(text: str) -> str:
    return _VIOLATION_ITEMS_BEFORE_LABEL.sub(r"\2\n\1", text)


def normalize_ocr_text(text: str, *, double_ratio_threshold: float = 0.28) -> str:
    """归一化 OCR/扫描公示表文本。幂等，对干净文本近似无副作用。"""
    if not text or not text.strip():
        return text or ""

    ended_nl = text.endswith("\n")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fixed: list[str] = []
    for line in lines:
        line = _collapse_local_pair_runs(line)
        if _cjk_double_ratio(line) >= double_ratio_threshold:
            line = _collapse_doubled_cjk(line)
        fixed.append(line)

    joined = "\n".join(fixed)
    joined = _repair_labels(joined)
    joined = _collapse_spaces_in_cjk_runs(joined)
    joined = _ensure_label_separators(joined)
    joined = _reorder_violation_items(joined)
    # 连续空行压成单个空行
    joined = re.sub(r"\n{3,}", "\n\n", joined).strip()
    return joined + ("\n" if ended_nl else "")
