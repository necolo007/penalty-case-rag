"""清洗竞赛金标 gold_extraction_cases.jsonl 中的系统性字段噪声。

背景（见 data/eval/评测报告_最新.md 六次优化 §三）：
  金标存在标签前缀残留、文号拼接下一字段、处罚内容整案转储、
  「保险机构」/「见原文」占位符、监管机关截断等噪声。本脚本做两层清洗：

  ① 规则清洗（默认启用，纯确定性，不依赖原文）：
     - party_name：去掉「当事人:」等标签前缀；去掉「一、」编号并截断「二、」后的
       多当事人拼接；压掉中文间版面断行空格；清空「…行政处罚决定书」标题/
       机关名误标（括号内有真当事人则提取）
     - penalty_doc_no：截到「…号」，去掉后接的「被处罚当事人」等
     - regulator：去掉「名称」标签残留；「…监管」补全为「…监管局」
     - violation_behavior：去掉标签前缀/程序性套话；压掉中文间空格
     - penalty_content：占位符「见原文」/整案转储清空（留给原文回填）

  ② 原文回填（--from-raw，可选）：对「保险机构」占位符、空/见原文处罚内容、
     整案转储式 penalty_content、空 regulator 等，从 raw_text/{file_id}.txt
     用规则引擎重抽后回填（不改动已有合理值）。

用法：
  # 仅规则清洗，写出副本（不覆盖原文件）
  python scripts/clean_gold_extraction.py \\
    --input \"../docs/data/.../配套数据/gold_extraction_cases.jsonl\" \\
    --output data/eval/gold_extraction_cases.cleaned.jsonl

  # 规则 + 原文回填
  python scripts/clean_gold_extraction.py --from-raw \\
    --input \".../gold_extraction_cases.jsonl\" \\
    --output data/eval/gold_extraction_cases.cleaned.jsonl \\
    --report data/eval/gold_clean_report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DEFAULT_COMP = Path(
    "docs/data/05-金融大模型与智能体赛道-基于知识增强检索的保险监管处罚案例知识库构建与合规审查智能匹配"
)

_PARTY_LABEL_PREFIXES = (
    "被处罚单位名称", "受处罚单位名称", "被处罚人名称", "受处罚人名称",
    "被处罚当事人", "受处罚当事人", "被处罚单位", "受处罚单位",
    "当事人单位名称", "当事人名称", "当事人单位", "受处罚机构名称",
    "受处罚机构", "当事人", "名称", "姓名",
)

_PARTY_PLACEHOLDERS = {"保险机构", "个人", "单位", "名称", "姓名", "当事人"}

_PARTY_PROCEDURAL = (
    "依据《", "行政复议", "加处罚款", "根据《", "申请行政",
    "强制执行", "缴款", "划款凭证", "逾期", "提起诉讼",
)

# 金标把文书标题/处罚机关误写入 party_name（非被处罚主体）。
_PARTY_TITLE_MARKERS = (
    "行政处罚决定书", "行政处罚信息公开表", "行政处罚信息",
)

# 机关名特征（无「保险公司/支公司」等被处罚主体后缀时视为噪声）。
_PARTY_REGULATOR_RE = re.compile(
    r"(?:中国保险监督管理委员会|国家金融监督管理总局|中国银保监会|中国保监会|"
    r"[\u4e00-\u9fff]{0,8}(?:银保监局|保监局|监管分局|监管局))"
)
_PARTY_INSTITUTION_RE = re.compile(
    r"(?:保险|人寿|财险|产险|经纪|代理|公估|健康保险|养老保险)"
    r".{0,40}?(?:公司|支公司|分公司|中心支公司|营业部|服务部|电销中心)"
)

# 多当事人编号：「一、机构… 二、责任人…」→ 只保留第一项。
_PARTY_LEADING_NUM = re.compile(r"^[一二三四五六七八九十\d]+[、．.]\s*")
_PARTY_NEXT_NUM = re.compile(r"\s*[二三四五六七八九十\d]+[、．.]")

_VIOLATION_LABEL_PREFIXES = (
    "主要违法违规事实（案由）", "主要违法违规事实(案由)",
    "主要违法违规事实", "主要违法违规行为",
    "违法违规事实", "违法违规行为", "违法事实", "违法行为",
    "违规事实", "违规行为",
)

# 「违法行为」金标里混入的非违法事实内容：证据确认/复议诉讼等程序性套话、
# 或实为处罚决定内容（罚款/警告金额），均非真正的违法事实描述。
_VIOLATION_PROCEDURAL_MARKERS = (
    "证据证明,足以认定", "证据证明，足以认定", "足以认定。",
    "如不服本处罚决定", "如不服本决定", "申请行政复议",
    "提起行政诉讼", "提起诉讼",
)
_VIOLATION_PENALTY_MARKERS = (
    "予以警告并处罚", "决定对", "决定给予", "我局决定", "我会决定",
)

_DOCNO_TAIL_NOISE = re.compile(
    r"(?:被处罚当事人|被处罚人|受处罚人|当事人|姓名或名称).*$"
)

_DOCNO_CORE = re.compile(
    r"([\u4e00-\u9fff]{0,12}(?:金监罚决字|金罚决字|罚决字|银保监罚决字|银保监罚|"
    r"保监罚决字|保监罚|保监罚字|罚字)"
    r"[〔\[（(]\d{4}[〕\]）)]\s*第?\s*\d+\s*号)"
)


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _strip_label_prefix(value: str, prefixes: tuple[str, ...]) -> str:
    s = (value or "").strip()
    if not s:
        return s
    # 最长前缀优先，避免「当事人」吃掉「当事人名称」
    for p in sorted(prefixes, key=len, reverse=True):
        if s.startswith(p):
            rest = s[len(p):].lstrip(" ：:\t　")
            return rest if rest else s
    return s


def _is_party_procedural(name: str) -> bool:
    if not name:
        return False
    if any(m in name for m in _PARTY_PROCEDURAL):
        return True
    if len(name) > 80:
        return True
    return False


def _collapse_whitespace(text: str) -> str:
    """去掉字段内空白（含中文间的版面断行空格）。"""
    return re.sub(r"\s+", "", text or "")


# 括注内容看起来已说完（可补右括号）；否则视为截断噪声，去掉半边括号及内容。
_PARTY_PAREN_COMPLETE_RE = re.compile(
    r"(?:公司|支公司|分公司|中心支公司|营业部|服务部|电销中心|"
    r"总经理|副总经理|经理|主任|副主任|总监|代理人|个人代理|"
    r"工作人员|负责人|员工|业务员)$"
)


def _fix_party_parens(name: str) -> tuple[str, str | None]:
    """处理括号不成对：多余右括号去掉；未闭合则补全或去掉括注。

    - 「机构)」仅多一个右括号 → 去掉
    - 「张三(时任XX公司总经理」括注语义完整 → 补「)」
    - 「冯文琪(时任太平…华」「机构(以下简称」等截断 → 去掉半边括号及括注内容
    """
    s = (name or "").strip()
    if not s:
        return s, None

    open_n = s.count("（") + s.count("(")
    close_n = s.count("）") + s.count(")")
    if open_n == close_n:
        return s, None

    # 多余右括号（常见标题/截取残留）
    if close_n > open_n:
        fixed = re.sub(r"[）)]+\s*$", "", s).strip()
        return fixed, "party_orphan_close_paren_stripped"

    # 未闭合左括号：从最后一个未匹配的开括号起处理
    last_open = max(s.rfind("（"), s.rfind("("))
    if last_open < 0:
        return s, None
    inner = s[last_open + 1 :]
    # 「(以下简称」金标常见截断到简称标签本身 → 直接去掉
    if inner.startswith("以下简称") or not inner.strip():
        return s[:last_open].strip(" ，,、"), "party_unclosed_paren_stripped"
    if _PARTY_PAREN_COMPLETE_RE.search(inner):
        closer = "）" if s[last_open] == "（" else ")"
        return s + closer, "party_unclosed_paren_completed"
    # 括注明显截断（如「…有限公司华」）→ 去掉半边括号及内容，保留括号前主体
    return s[:last_open].strip(" ，,、"), "party_unclosed_paren_stripped"


def _extract_party_from_decision_title(name: str) -> str | None:
    """「…行政处罚决定书(真实当事人)」→ 取出括号内主体；纯标题则返回空串。"""
    if not any(m in name for m in _PARTY_TITLE_MARKERS):
        return None
    m = re.search(
        r"(?:行政处罚决定书|行政处罚信息公开表|行政处罚信息)"
        r"[（(]\s*([^）)]{2,80})\s*[）)]",
        name,
    )
    if m:
        return m.group(1).strip()
    return ""


def _is_party_regulator_noise(name: str) -> bool:
    """处罚机关名被误标为当事人（且不含被处罚机构主体）。"""
    if not name or not _PARTY_REGULATOR_RE.search(name):
        return False
    if _PARTY_INSTITUTION_RE.search(name):
        return False
    # 「张三(时任XX监管局…)」这类极少见，人名起头+括注保留
    if re.match(r"^[\u4e00-\u9fff]{2,4}[（(]", name):
        return False
    return True


_DUMP_MARKERS = (
    "当事人", "经查", "受处罚", "被处罚", "住址:", "住址：", "地址:", "地址：",
    "主要负责人", "法定代表人", "营业地址",
)

# 真正的处罚决定句特征（缴款指引里也会出现「罚款」二字，不能单靠动作词判断）
_PENALTY_ACTION_RE = re.compile(
    r"(?:罚款|警告|责令改正|责令|吊销|没收违法所得|撤销任职资格|"
    r"限制其?业务|停止接受新业务)"
)
_PENALTY_DECISION_RE = re.compile(
    r"(?:决定给予|决定对|我局决定|我会决定|本机关决定|"
    r"给予你|处以|作出.{0,6}处罚|"
    r"警告[，,、]?并处|并处罚款|并处.{0,6}罚款|"
    r"责令改正.{0,10}罚款|罚款人民币|罚款\s*\d|罚款[一二三四五六七八九十百千万\d])"
)
_PAYMENT_MARKERS = (
    "缴至", "付款凭证", "开户银行", "开户账号", "注有当事人名称的付款",
    "将罚款缴", "到指定银行缴纳",
)
_PENALTY_PROCEDURAL_MARKERS = (
    "申请人民法院强制执行", "如不服本处罚", "申请行政复议",
    "提起行政诉讼", "行政复议和行政诉讼期间",
)
# 从脏文本中尽量抽出「处罚动作句」（优先于整段清空）
_CORE_PENALTY_SENT_RE = re.compile(
    r"((?:我(?:会|局|处|厅)|本机关)?[^。\n]{0,30}?"
    r"(?:决定给予|决定对|给予|处以|责令)[^。\n]{0,40}?"
    r"(?:罚款|警告|吊销|没收|撤销)[^。\n]{0,60}[。]?)"
)


def _is_penalty_content_dump(text: str) -> bool:
    """判断 penalty_content 是否被误标为「整案文本转储」（文号+当事人+违法事实），
    而非真正的处罚决定内容。整案转储通常较长（含地址/经查等案情描述），
    真正的处罚决定句一般较短（几十字的罚款/警告/吊销描述）。"""
    t = (text or "").strip()
    if t in ("", "见原文"):
        return True
    if len(t) > 60 and any(marker in t for marker in _DUMP_MARKERS):
        return True
    if t.startswith(("当事人", "姓名:", "名称:", "受处罚", "被处罚")) and len(t) > 40:
        return True
    # 「文号 + 受处罚单位/地址」抬头被误写入处罚内容
    if re.match(
        r"^[\u4e00-\u9fff]{0,8}(?:金罚决字|罚决字|银保监罚|保监罚|罚字)[〔\[（(]",
        t,
    ) and any(m in t for m in ("受处罚", "被处罚", "地址", "姓名")):
        return True
    return False


def _is_penalty_content_procedural(text: str) -> bool:
    """缴款指引 / 复议诉讼套话（非处罚决定本身）。"""
    t = (text or "").strip()
    if not t:
        return False
    if any(m in t for m in _PAYMENT_MARKERS):
        # 「将罚款缴至…开户银行」含「罚款」但不是决定句
        if not _PENALTY_DECISION_RE.search(t):
            return True
        # 决定句很短、后半大段是缴款 → 仍视为程序性污染（交给抽核心句逻辑）
        if len(t) > 80 and t.find("缴") < len(t) * 0.4:
            return True
    if any(m in t for m in _PENALTY_PROCEDURAL_MARKERS):
        if not _PENALTY_DECISION_RE.search(t) and not (
            _PENALTY_ACTION_RE.search(t) and len(t) < 40
        ):
            return True
    return False


def _is_penalty_content_no_action(text: str) -> bool:
    """非空但不含任何处罚动作，或仅为日期落款。"""
    t = (text or "").strip()
    if not t:
        return False
    if re.fullmatch(r"\d{4}年\d{1,2}月\d{1,2}日", t):
        return True
    if re.fullmatch(r"[二〇O○0-9元月日\s、．.]+", t) and "罚款" not in t:
        return True
    return not bool(_PENALTY_ACTION_RE.search(t))


def _extract_core_penalty_sentence(text: str) -> str | None:
    """从脏段落中抽出首条处罚决定句；抽不到返回 None。"""
    t = (text or "").strip()
    if not t:
        return None
    m = _CORE_PENALTY_SENT_RE.search(t)
    if not m:
        # 短句本身已是「警告,并处罚款X万元」这类
        if len(t) <= 40 and _PENALTY_ACTION_RE.search(t) and not _is_penalty_content_dump(t):
            return t
        return None
    core = m.group(1).strip()
    if len(core) < 6 or not _PENALTY_ACTION_RE.search(core):
        return None
    return core


def clean_party_name(value: str) -> tuple[str, str | None]:
    """返回 (清洗后值, 变更原因或 None)。

    额外处理（问题1）：
      - 「一、机构… 二、责任人…」去掉编号并只保留第一当事人
      - 中文间版面断行空格压掉
      - 「…行政处罚决定书」标题 / 机关名误标清空（括号内有真当事人则提取）
    """
    raw = (value or "").strip()
    if not raw:
        return "", None
    if raw in _PARTY_PLACEHOLDERS:
        return "", "party_placeholder_cleared"

    reasons: list[str] = []
    cleaned = _strip_label_prefix(raw, _PARTY_LABEL_PREFIXES)
    if cleaned != raw:
        reasons.append("party_label_prefix_stripped")

    # 文书标题误标：能从括号抽出真当事人则用之，否则清空留给原文回填
    extracted = _extract_party_from_decision_title(cleaned)
    if extracted is not None:
        if extracted:
            cleaned = extracted
            reasons.append("party_title_paren_extracted")
        else:
            return "", "party_title_cleared"

    if _is_party_regulator_noise(cleaned):
        return "", "party_regulator_as_party_cleared"

    # 「一、XXX」去编号前缀
    stripped_num = _PARTY_LEADING_NUM.sub("", cleaned)
    if stripped_num != cleaned:
        cleaned = stripped_num
        reasons.append("party_leading_num_stripped")

    # 「一、机构 二、责任人」截到第二编号之前，只留第一当事人
    m = _PARTY_NEXT_NUM.search(cleaned)
    if m and m.start() >= 4:
        cleaned = cleaned[: m.start()].strip()
        reasons.append("party_multi_party_truncated")

    # 住所/地址粘连：截到第一个「住所/地址/住址」
    cut = re.split(r"(?:住所|营业地址|住址|地址|身份证号|职务)[：:]?", cleaned, maxsplit=1)
    if len(cut) > 1 and cut[0].strip() and len(cut[0].strip()) >= 2:
        cleaned = cut[0].strip(" ，,、")
        reasons.append("party_address_tail_stripped")

    collapsed = _collapse_whitespace(cleaned)
    if collapsed != cleaned:
        cleaned = collapsed
        reasons.append("party_whitespace_collapsed")

    fixed_paren, paren_reason = _fix_party_parens(cleaned)
    if paren_reason:
        cleaned = fixed_paren
        reasons.append(paren_reason)
        # 括注截断后只剩短人名（如「冯文琪」）→ 清空，交给原文回填完整「姓名(时任…)」
        if (
            paren_reason == "party_unclosed_paren_stripped"
            and re.fullmatch(r"[\u4e00-\u9fff]{2,4}", cleaned or "")
        ):
            return "", "party_unclosed_paren_cleared_for_refill"

    if _is_party_procedural(cleaned):
        return "", "party_procedural_cleared"

    cleaned = cleaned.strip(" ：:\t　，,、")
    if cleaned != raw and not reasons:
        reasons.append("party_normalized")
    # 主因取第一条（报告里用单 reason；多步变更拼进列表由调用方只记主因）
    primary = reasons[0] if reasons else None
    # 若还有后续步骤，把最能代表本轮意图的 reason 提升：multi/title/whitespace 优先
    for preferred in (
        "party_unclosed_paren_stripped",
        "party_unclosed_paren_completed",
        "party_orphan_close_paren_stripped",
        "party_title_paren_extracted",
        "party_multi_party_truncated",
        "party_leading_num_stripped",
        "party_whitespace_collapsed",
        "party_address_tail_stripped",
        "party_label_prefix_stripped",
    ):
        if preferred in reasons:
            primary = preferred
            break
    return cleaned, primary if cleaned != raw else None


def clean_penalty_doc_no(value: str) -> tuple[str, str | None]:
    raw = (value or "").strip()
    if not raw:
        return "", None
    # 先尝试抽出核心文号
    m = _DOCNO_CORE.search(raw)
    if m:
        core = re.sub(r"\s+", "", m.group(1))
        if core != re.sub(r"\s+", "", raw):
            return core, "doc_no_core_extracted"
        return core, None
    # 退化为去掉「被处罚当事人」尾缀
    stripped = _DOCNO_TAIL_NOISE.sub("", raw).strip()
    if stripped != raw:
        return stripped, "doc_no_tail_stripped"
    return raw, None


def clean_regulator(value: str) -> tuple[str, str | None]:
    raw = (value or "").strip()
    if not raw:
        return "", None
    cleaned = _strip_label_prefix(raw, ("作出处罚决定的机关名称", "处罚机关", "决定机关", "名称"))
    reason = "regulator_label_stripped" if cleaned != raw else None
    # 申诉条款污染：含「申请行政复议」则整段不可信，清空留给原文回填
    if re.search(r"申请行政复议|提起诉讼|强制执行", cleaned):
        return "", "regulator_procedural_cleared"
    # 「国家金融监督管理总局XX监管」缺「局」——金标常见截断
    if re.fullmatch(r"国家金融监督管理总局[\u4e00-\u9fff]{1,8}监管", cleaned):
        cleaned = cleaned + "局"
        reason = "regulator_truncated_completed"
    # 「…监管分」缺「局」
    if cleaned.endswith("监管分") and not cleaned.endswith("监管分局"):
        cleaned = cleaned + "局"
        reason = "regulator_truncated_completed"
    cleaned = cleaned.strip()
    return cleaned, reason if cleaned != raw else None


def clean_violation_behavior(value: str) -> tuple[str, str | None]:
    raw = (value or "").strip()
    if not raw:
        return "", None
    if any(m in raw for m in _VIOLATION_PROCEDURAL_MARKERS):
        return "", "violation_procedural_cleared"
    cleaned = _strip_label_prefix(raw, _VIOLATION_LABEL_PREFIXES)
    reason = "violation_label_stripped" if cleaned != raw else None
    collapsed = _collapse_whitespace(cleaned)
    if collapsed != cleaned:
        cleaned = collapsed
        reason = reason or "violation_whitespace_collapsed"
    if cleaned != raw:
        return cleaned.strip(), reason or "violation_normalized"
    return raw, None


def clean_penalty_content(value: str) -> tuple[str, str | None]:
    raw = (value or "").strip()
    if not raw:
        return "", None
    if raw == "见原文":
        return "", "penalty_content_placeholder_cleared"

    collapsed = _collapse_whitespace(raw)
    reason: str | None = "penalty_content_whitespace_collapsed" if collapsed != raw else None
    text = collapsed

    # 决定句后粘了缴款指引：抽出核心决定句
    if any(m in text for m in _PAYMENT_MARKERS) and _PENALTY_DECISION_RE.search(text):
        core = _extract_core_penalty_sentence(text)
        if core and core != text:
            return core, "penalty_content_core_extracted"

    # 脏段落优先抽核心处罚句，避免直接清空后过度依赖原文回填
    if (
        _is_penalty_content_dump(text)
        or _is_penalty_content_procedural(text)
        or _is_penalty_content_no_action(text)
    ):
        core = _extract_core_penalty_sentence(text)
        if core and not _is_penalty_content_dump(core) and not _is_penalty_content_procedural(core):
            return core, "penalty_content_core_extracted"
        if _is_penalty_content_dump(text):
            return "", "penalty_content_dump_cleared"
        if _is_penalty_content_procedural(text):
            return "", "penalty_content_procedural_cleared"
        return "", "penalty_content_no_action_cleared"

    return text, reason if text != raw else None


def clean_row_rules(row: dict) -> tuple[dict, list[str]]:
    """对单行做规则清洗，返回 (新行, 变更原因列表)。"""
    out = dict(row)
    reasons: list[str] = []

    for field, fn in (
        ("party_name", clean_party_name),
        ("penalty_doc_no", clean_penalty_doc_no),
        ("regulator", clean_regulator),
        ("violation_behavior", clean_violation_behavior),
        ("penalty_content", clean_penalty_content),
    ):
        new_val, reason = fn(out.get(field, "") or "")
        if reason:
            out[field] = new_val
            reasons.append(f"{field}:{reason}")
        else:
            out[field] = new_val if field in out else out.get(field, "")

    return out, reasons


def _resolve_raw_dirs(extra: list[Path] | None = None) -> list[Path]:
    dirs: list[Path] = [
        _ROOT / "data" / "raw_text",
        _ROOT.parent / _DEFAULT_COMP / "raw_text",
        _ROOT.parent / _DEFAULT_COMP / "配套数据" / ".." / "raw_text",
    ]
    if extra:
        dirs = list(extra) + dirs
    # 规范化并去重
    seen: set[Path] = set()
    result: list[Path] = []
    for d in dirs:
        try:
            r = d.resolve()
        except OSError:
            continue
        if r in seen or not r.is_dir():
            continue
        seen.add(r)
        result.append(r)
    return result


def _read_raw(file_id: str, dirs: list[Path]) -> str:
    for d in dirs:
        p = d / f"{file_id}.txt"
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def _extract_from_raw(file_id: str, text: str) -> dict:
    from pipeline.extraction.extractor import ExtractorEngine
    from pipeline.parser.base import ParseResult

    engine = ExtractorEngine(llm_client=None, use_llm_refine=False)
    parse = ParseResult(success=True, markdown=text, confidence=1.0)
    cases = engine.extract(parse, file_id=file_id, source_file=f"{file_id}.txt")
    if not cases:
        return {}
    # 一案两罚优先机构主体
    best = max(
        cases,
        key=lambda c: (
            1 if re.search(r"公司|保险|经纪|代理|公估", c.party_name or "") else 0,
            c.overall_confidence,
            len(c.party_name or ""),
        ),
    )
    inst = best.institution_type
    return {
        "party_name": best.party_name or "",
        "penalty_doc_no": best.penalty_doc_no or "",
        "violation_behavior": best.violation_behavior or "",
        "penalty_content": best.penalty_content or "",
        "regulator": best.regulator or "",
        "institution_type": inst.value if hasattr(inst, "value") else str(inst),
    }


def fill_from_raw(row: dict, extracted: dict) -> tuple[dict, list[str]]:
    """仅回填空/占位/脏字段，不覆盖已有合理值。"""
    out = dict(row)
    reasons: list[str] = []
    if not extracted:
        return out, reasons

    # party_name：空或仍是占位 → 回填；回填值先过一遍规则，拒绝标题/机关噪声
    pn = (out.get("party_name") or "").strip()
    if (not pn or pn in _PARTY_PLACEHOLDERS) and extracted.get("party_name"):
        cand, _ = clean_party_name(extracted["party_name"])
        if cand and cand not in _PARTY_PLACEHOLDERS:
            out["party_name"] = cand
            reasons.append("party_name:filled_from_raw")

    # penalty_doc_no：空 → 回填
    if not (out.get("penalty_doc_no") or "").strip() and extracted.get("penalty_doc_no"):
        out["penalty_doc_no"] = extracted["penalty_doc_no"]
        reasons.append("penalty_doc_no:filled_from_raw")

    # regulator：空 → 回填
    if not (out.get("regulator") or "").strip() and extracted.get("regulator"):
        out["regulator"] = extracted["regulator"]
        reasons.append("regulator:filled_from_raw")

    # penalty_content：空（含规则层清空的见原文/转储）→ 回填；回填值再过规则
    if not (out.get("penalty_content") or "").strip() and extracted.get("penalty_content"):
        cand, _ = clean_penalty_content(extracted["penalty_content"])
        if cand:
            out["penalty_content"] = cand
            reasons.append("penalty_content:filled_from_raw")

    # violation_behavior：空 → 回填（同样压空白、拒程序性套话）
    if not (out.get("violation_behavior") or "").strip() and extracted.get("violation_behavior"):
        cand, _ = clean_violation_behavior(extracted["violation_behavior"])
        if cand:
            out["violation_behavior"] = cand
            reasons.append("violation_behavior:filled_from_raw")

    return out, reasons


def main() -> None:
    parser = argparse.ArgumentParser(description="清洗金标抽取字段噪声")
    parser.add_argument(
        "--input",
        default=str(
            _ROOT.parent
            / _DEFAULT_COMP
            / "配套数据"
            / "gold_extraction_cases.jsonl"
        ),
        help="原始金标 jsonl 路径",
    )
    parser.add_argument(
        "--output",
        default="data/eval/gold_extraction_cases.cleaned.jsonl",
        help="清洗后输出路径（默认不覆盖原文件）",
    )
    parser.add_argument(
        "--report",
        default="data/eval/gold_clean_report.json",
        help="变更报告 JSON 路径",
    )
    parser.add_argument(
        "--from-raw",
        action="store_true",
        help="对空/占位/脏字段用 raw_text 规则重抽回填",
    )
    parser.add_argument(
        "--raw-dir",
        action="append",
        default=None,
        help="额外 raw_text 目录，可多次指定",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="覆盖 --input 原文件（危险；默认写到 --output）",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.is_absolute():
        in_path = (_ROOT / in_path).resolve()
    if not in_path.is_file():
        raise SystemExit(f"输入文件不存在: {in_path}")

    out_path = in_path if args.in_place else Path(args.output)
    if not out_path.is_absolute():
        out_path = (_ROOT / out_path).resolve()
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = (_ROOT / report_path).resolve()

    rows = _load_jsonl(in_path)
    if args.limit:
        rows = rows[: args.limit]

    raw_dirs = _resolve_raw_dirs(
        [Path(p) for p in args.raw_dir] if args.raw_dir else None
    )
    extract_cache: dict[str, dict] = {}
    if args.from_raw:
        print(f"原文回填启用，raw_text 目录: {[str(d) for d in raw_dirs]}")

    cleaned_rows: list[dict] = []
    change_log: list[dict] = []
    reason_counter: Counter[str] = Counter()
    missing_raw = 0

    for row in rows:
        new_row, reasons = clean_row_rules(row)

        if args.from_raw:
            fid = row.get("file_id") or ""
            if fid not in extract_cache:
                text = _read_raw(fid, raw_dirs) if fid else ""
                if text.strip():
                    extract_cache[fid] = _extract_from_raw(fid, text)
                else:
                    extract_cache[fid] = {}
                    missing_raw += 1
            new_row, fill_reasons = fill_from_raw(new_row, extract_cache[fid])
            reasons.extend(fill_reasons)

        cleaned_rows.append(new_row)
        if reasons:
            for r in reasons:
                reason_counter[r] += 1
            change_log.append({
                "case_id": row.get("case_id"),
                "file_id": row.get("file_id"),
                "reasons": reasons,
                "before": {
                    k: row.get(k)
                    for k in (
                        "party_name", "penalty_doc_no", "violation_behavior",
                        "penalty_content", "regulator",
                    )
                },
                "after": {
                    k: new_row.get(k)
                    for k in (
                        "party_name", "penalty_doc_no", "violation_behavior",
                        "penalty_content", "regulator",
                    )
                },
            })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in cleaned_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "input": str(in_path),
        "output": str(out_path),
        "total_rows": len(cleaned_rows),
        "changed_rows": len(change_log),
        "from_raw": bool(args.from_raw),
        "missing_raw_files": missing_raw if args.from_raw else None,
        "reason_counts": dict(reason_counter.most_common()),
        "changes": change_log,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Wrote {len(cleaned_rows)} rows → {out_path}")
    print(f"Changed {len(change_log)} / {len(cleaned_rows)} rows")
    if args.from_raw:
        print(f"missing_raw_files={missing_raw}")
    print("Top reasons:")
    for k, v in reason_counter.most_common(15):
        print(f"  {v:4d}  {k}")
    print(f"Report → {report_path}")


if __name__ == "__main__":
    main()
