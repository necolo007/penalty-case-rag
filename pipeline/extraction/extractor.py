"""字段抽取引擎：正则规则 + LLM 二次纠错 + 字段校验置信度打分。

两条输入路径：
  ① 公示表解析结果（TableParser 已输出结构化 records）→ 直接映射
  ② 长文本 Markdown（决定书/OCR）→ 正则抽取 → 低置信度 LLM 补全
"""

import json
import logging
import re

from engine.classification.entity_normalizer import normalize_entity
from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import FIELD_REFINE_PROMPT
from pipeline.extraction.regex_patterns import (
    DOCNO_REGION_REGULATOR,
    INSTITUTION_TYPE_RULES,
    PATTERNS,
)
from pipeline.extraction.schema import ExtractedCase, FieldConfidence, InstitutionType
from pipeline.parser.base import ParseResult

logger = logging.getLogger(__name__)

CORE_FIELDS = ["party_name", "violation_behavior", "penalty_content", "regulator"]
DEFAULT_LLM_REFINE_THRESHOLD = 0.6

# 无地区限定的顶层机关裸词：信息量低于带地区的具体机关名，即便字数更多也不应
# 在候选择优时占先（见 _from_text 的 regulator 兜底逻辑）。
_BARE_REGULATOR_NAMES = {"国家金融监督管理总局", "中国银保监会", "中国保监会"}


def _matched_text(m: "re.Match") -> str:
    """兼容含多个可选捕获组（转折短语懒惰分支 / 定长兜底分支）的模式。"""
    for g in m.groups():
        if g:
            return g
    return m.group(0)


class ExtractorEngine:
    def __init__(
        self,
        llm_client: DeepSeekClient | None = None,
        use_llm_refine: bool = True,
        *,
        llm_refine_threshold: float | None = None,
    ):
        self.llm = llm_client
        self.use_llm_refine = use_llm_refine
        if llm_refine_threshold is None:
            try:
                from core.config import get_settings
                llm_refine_threshold = get_settings().LLM_REFINE_THRESHOLD
            except Exception:  # noqa: BLE001
                llm_refine_threshold = DEFAULT_LLM_REFINE_THRESHOLD
        self.llm_refine_threshold = llm_refine_threshold

    def extract(self, parse_result: ParseResult, *, file_id: str,
                source_file: str) -> list[ExtractedCase]:
        # 路径①：公示表结构化 records
        records = parse_result.metadata.get("records")
        if records:
            cases = [
                self._from_table_record(r, file_id=file_id, source_file=source_file)
                for r in records
            ]
        else:
            # 路径②：长文本 → 按文号/当事人切分多案例后分别抽取
            segments = self._split_case_segments(parse_result.markdown)
            cases = []
            for seg in segments:
                case = self._from_text(seg, file_id=file_id, source_file=source_file)
                if case:
                    cases.append(case)
            if not cases:
                case = self._from_text(parse_result.markdown, file_id=file_id, source_file=source_file)
                cases = [case] if case else []

        for case in cases:
            self._infer_institution_type(case)
            self._validate(case)
            if (case.overall_confidence < self.llm_refine_threshold
                    and self.use_llm_refine and self.llm is not None):
                self._llm_refine(case)
                self._validate(case)
        return cases

    # ---------- 路径①：公示表 ----------

    def _from_table_record(self, record: dict, *, file_id: str, source_file: str) -> ExtractedCase:
        case = ExtractedCase(
            file_id=file_id,
            source_file=source_file,
            party_name=record.get("party_name", ""),
            penalty_doc_no=record.get("penalty_doc_no", ""),
            violation_behavior=record.get("violation_behavior", ""),
            penalty_content=record.get("penalty_content", ""),
            regulator=record.get("regulator", ""),
            legal_basis=record.get("legal_basis", ""),
            publish_date=self._normalize_date(record.get("publish_date", "")),
            extraction_method="table",
        )
        m = PATTERNS["fine_amount"].search(case.penalty_content)
        if m:
            case.fine_amount = m.group(1)
        for f in CORE_FIELDS:
            case.field_confidences[f] = (
                FieldConfidence.HIGH.value if getattr(case, f) else FieldConfidence.LOW.value
            )
        return case

    # ---------- 路径②：长文本 ----------

    def _split_case_segments(self, text: str) -> list[str]:
        """按处罚文号切分为多案例片段（仅在文号确有差异时才拆分）。

        注意：不再仅凭「当事人」出现次数拆分——单一处罚决定书里常见
        「机构 + 责任人」两个「当事人」小节（一案两罚），若按此拆分会把
        同一案例误切成两段，反而丢失机构主体的完整字段。
        """
        if not text or not text.strip():
            return []
        # 同一文号在正文中重复出现（页眉/页脚/多次引用）不代表多案例，需先去重。
        # 标题常写成「重庆保监局渝保监罚〔2013〕46号」，正文为「渝保监罚〔2013〕46号」，
        # 规范化到「关键词+年份+号」后再去重，避免误拆。
        docnos: list[re.Match] = []
        seen_no: set[str] = set()
        for m in PATTERNS["penalty_doc_no"].finditer(text):
            key = self._normalize_docno_key(m.group(1))
            if not key or key in seen_no:
                continue
            seen_no.add(key)
            docnos.append(m)

        if len(docnos) >= 2:
            segments: list[str] = []
            for i, m in enumerate(docnos):
                start = m.start()
                end = docnos[i + 1].start() if i + 1 < len(docnos) else len(text)
                lookback = text[max(0, start - 320):start]
                party_hits = list(re.finditer(r"当事人", lookback))
                seg_start = start
                if party_hits:
                    nearest = party_hits[-1]
                    # 若回看跨越了更早的文号，则从当前文号起切，避免吞并上一案例
                    earlier_doc = PATTERNS["penalty_doc_no"].search(lookback[nearest.start():])
                    if not earlier_doc:
                        seg_start = max(0, start - 320) + nearest.start()
                seg = text[seg_start:end].strip()
                if len(seg) > 40:
                    segments.append(seg)
            if len(segments) >= 2:
                return segments
        return [text]

    @staticmethod
    def _normalize_docno_key(docno: str) -> str:
        """文号去重键：去掉空白与机关前缀，保留「罚字类型+年份+序号」。"""
        s = re.sub(r"\s+", "", docno or "")
        m = re.search(
            r"((?:金罚决字|罚决字|银保监罚决字|银保监罚|保监罚决字|保监罚|罚字)"
            r"[〔\[（(]\d{4}[〕\]）)]\s*第?\s*\d+\s*号)",
            s,
        )
        return re.sub(r"\s+", "", m.group(1)) if m else s

    @staticmethod
    def _build_evidence_snippet(text: str, max_chars: int = 1800) -> str:
        """汇聚文号/当事人/违法事实/处罚/落款附近片段，供 LLM 纠错（非简单截头 500 字）。"""
        chunks: list[str] = []
        if text[:280].strip():
            chunks.append(text[:280].strip())
        for key in ("penalty_doc_no", "party_name", "violation_behavior",
                    "penalty_content", "regulator", "legal_basis"):
            pat = PATTERNS.get(key)
            if not pat:
                continue
            m = pat.search(text)
            if not m:
                continue
            start = max(0, m.start() - 48)
            end = min(len(text), m.end() + 160)
            chunks.append(text[start:end].strip())
        if len(text) > 400:
            chunks.append(text[-400:].strip())
        seen: set[str] = set()
        ordered: list[str] = []
        for c in chunks:
            if c and c not in seen:
                seen.add(c)
                ordered.append(c)
        joined = "\n…\n".join(ordered)
        return joined[:max_chars]

    def _from_text(self, text: str, *, file_id: str, source_file: str) -> ExtractedCase | None:
        if not text.strip():
            return None

        case = ExtractedCase(
            file_id=file_id, source_file=source_file,
            extraction_method="regex",
            raw_text_snippet=self._build_evidence_snippet(text),
        )

        for field_name in ("penalty_doc_no", "violation_behavior",
                           "penalty_content", "fine_amount", "legal_basis"):
            m = PATTERNS[field_name].search(text)
            if m:
                setattr(case, field_name, _matched_text(m).strip())
                case.field_confidences[field_name] = FieldConfidence.HIGH.value
            else:
                case.field_confidences[field_name] = FieldConfidence.LOW.value

        party, party_conf = self._extract_party_name(text)
        case.party_name = party
        case.field_confidences["party_name"] = party_conf

        if not case.violation_behavior:
            m = PATTERNS["violation_behavior_alt"].search(text)
            if m:
                case.violation_behavior = _matched_text(m).strip()[:1200]
                case.field_confidences["violation_behavior"] = FieldConfidence.MEDIUM.value

        if not case.penalty_content:
            m = PATTERNS["penalty_content_alt"].search(text)
            if m:
                case.penalty_content = m.group(1).strip()
                case.field_confidences["penalty_content"] = FieldConfidence.MEDIUM.value

        # 处罚机关：显式字段 → 正文 → 文号地域兜底
        m = PATTERNS["regulator"].search(text)
        if m:
            case.regulator = m.group(1).strip()
            case.field_confidences["regulator"] = FieldConfidence.HIGH.value
        else:
            # 决定书常见「地方局简称+文号(当事人)」的旧式标题写在文首，早于正文
            # 抬头「中国XX监管会XX监管局行政处罚决定书」出现；若取首个命中（如
            # 「重庆保监局」）会丢掉更完整的地区全称。改为收集全文所有候选，优先
            # 挑「带地区」的具体机关名（而非仅"中国银保监会"这类无地区的裸词——
            # 裸词虽字数多，但信息量反而不如短小的地区级机关名，纯比长度会选错，
            # 例如误选申诉条款里提到的"国家金融监督管理总局"而非落款的"辽宁银保
            # 监局"）；同一档位内再取更长、更靠后（落款通常在文末）的。
            matches = list(PATTERNS["regulator_inline"].finditer(text))
            if matches:
                def _score(mm: "re.Match") -> tuple:
                    text_ = mm.group(1)
                    is_specific = text_ not in _BARE_REGULATOR_NAMES
                    return (is_specific, len(text_), mm.start())

                best = max(matches, key=_score)
                case.regulator = best.group(1).strip()
                case.field_confidences["regulator"] = FieldConfidence.MEDIUM.value
            elif case.penalty_doc_no:
                for region, name in DOCNO_REGION_REGULATOR.items():
                    if case.penalty_doc_no.startswith(region):
                        case.regulator = name
                        case.field_confidences["regulator"] = FieldConfidence.LOW.value
                        break

        m = PATTERNS["publish_date"].search(text)
        if m:
            case.publish_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            case.field_confidences["publish_date"] = FieldConfidence.MEDIUM.value

        self._sanitize_fields(case)
        # sanitize 可能清空噪声当事人；此时再走一次兜底通道
        if not case.party_name:
            party, party_conf = self._extract_party_name(text, skip_label=True)
            if party:
                case.party_name = party
                case.field_confidences["party_name"] = party_conf
                self._sanitize_fields(case)
        return case

    @classmethod
    def _extract_party_name(
        cls, text: str, *, skip_label: bool = False,
    ) -> tuple[str, str]:
        """抽取当事人：收集候选后优先机构主体，避免一案两罚时命中责任人姓名。"""
        candidates: list[tuple[str, str, int]] = []  # (name, confidence, priority)

        if not skip_label:
            for m in PATTERNS["party_name"].finditer(text):
                raw = (m.group(1) or "").strip()
                cleaned = cls._clean_party_candidate(raw)
                if cleaned and not cls._is_party_noise(cleaned):
                    # 机构标签命中优先于后续人名标签
                    pri = 3 if cls._looks_like_institution(cleaned) else 1
                    candidates.append((cleaned, FieldConfidence.HIGH.value, pri))

        for key, conf, pri_base in (
            ("party_name_title", FieldConfidence.MEDIUM.value, 2),
            ("party_name_alt", FieldConfidence.MEDIUM.value, 2),
            ("party_name_header", FieldConfidence.MEDIUM.value, 2),
        ):
            m = PATTERNS[key].search(text)
            if not m:
                continue
            cleaned = cls._clean_party_candidate(m.group(1))
            if cleaned and not cls._is_party_noise(cleaned):
                pri = pri_base + (1 if cls._looks_like_institution(cleaned) else 0)
                candidates.append((cleaned, conf, pri))

        if not candidates:
            return "", FieldConfidence.LOW.value

        # 去重保序后按 priority 选最优；同分时偏好更长的机构名
        seen: set[str] = set()
        uniq: list[tuple[str, str, int]] = []
        for item in candidates:
            if item[0] in seen:
                continue
            seen.add(item[0])
            uniq.append(item)
        uniq.sort(key=lambda x: (x[2], len(x[0]) if cls._looks_like_institution(x[0]) else 0), reverse=True)
        return uniq[0][0], uniq[0][1]

    @staticmethod
    def _is_party_noise(name: str) -> bool:
        """过滤表头残留/字段名误捕获。"""
        noise = {
            "个人姓名", "单位名称", "名称", "姓名", "当事人", "主要负责人",
            "法定代表人", "负责人姓名", "营业地址", "住所",
        }
        if name in noise:
            return True
        if re.fullmatch(r"(?:个人|单位|机构)?(?:姓名|名称)", name):
            return True
        return False

    @staticmethod
    def _looks_like_institution(name: str) -> bool:
        if re.search(
            r"(?:公司|保险|人寿|财险|产险|经纪|代理|公估|支公司|分公司|"
            r"中心支公司|营业部|服务部|电销中心)",
            name,
        ):
            return True
        return False

    @staticmethod
    def _clean_party_candidate(name: str) -> str:
        """单条候选的轻量清洗（不含会清空字段的 junk 判定）。"""
        name = name.strip(" ：:\t　")
        # 「受处罚人名称:名称:XXX」或捕获组以「名称:」开头
        name = re.sub(r"^(?:名称|姓名)\s*[：:]\s*", "", name)
        # 标题括号捕获可能带上后续责任人「公司,张三」——只留机构段
        if "，" in name or "," in name:
            parts = re.split(r"[，,]", name, maxsplit=1)
            if ExtractorEngine._looks_like_institution(parts[0]) and not ExtractorEngine._looks_like_institution(parts[1] if len(parts) > 1 else ""):
                name = parts[0].strip()
        # 补全/截断括注：保留完整「(以下简称XX)」，缺右括号则截到「以下简称」
        m = re.search(r"^(.+?[（(]以下简称[^）)]*[）)])", name)
        if m:
            name = m.group(1)
        else:
            m = re.search(r"^(.+?[（(]以下简称)", name)
            if m and not re.search(r"[）)]", name[m.end():m.end() + 40]):
                # 金标常见截断到「(以下简称」；若原文本身缺右括号也按此收束
                name = m.group(1)
            else:
                name = re.split(
                    r"(?:告知了|作出行政|行政处罚|强制执行|划款凭证|抄报我局|"
                    r"营业地址|住\s*所|地址|身份证号|职务)",
                    name,
                    maxsplit=1,
                )[0].strip(" ，,、")
        # 去掉未闭合的多余右括号（如标题截取残留）
        if name.count(")") + name.count("）") > name.count("(") + name.count("（"):
            name = re.sub(r"[）)]\s*$", "", name).strip()
        return name.strip()[:80]

    @staticmethod
    def _sanitize_fields(case: ExtractedCase) -> None:
        """清洗当事人/机关噪声，对齐常见公示截断写法。"""
        if case.party_name:
            name = ExtractorEngine._clean_party_candidate(case.party_name)
            # 明显噪声：过短、或含非主体词、或仍以标签残留开头
            junk = ("名称的", "留待申请", "复印件", "强制执行", "划款凭证",
                    "付款凭证", "加处罚款", "申请行政复议", "违法行为")
            if (
                len(name) < 2
                or any(j in name for j in junk)
                or name in ("名称", "姓名", "当事人")
            ):
                case.party_name = ""
                case.field_confidences["party_name"] = FieldConfidence.LOW.value
            else:
                case.party_name = name[:80]

        if case.regulator:
            reg = case.regulator.strip()
            # 截到机关名为止，去掉「行政处罚决定…」尾巴。
            # 「金融监督管理总局/银保监会/保监会」后常跟地区+「监管局/监管分局」，
            # 这些带地区的分支必须排在裸词分支之前——否则懒惰量词一遇到「银保监
            # 会/保监会」这类短别名就会立即成功匹配并提前截断，丢掉后面的地区部分
            # （例如「中国银保监会宜昌监管分局」被截断成「中国银保监会」）。
            m = re.search(
                r"^([\u4e00-\u9fff]{2,40}?(?:"
                r"金融监督管理总局[\u4e00-\u9fff]{0,10}监管分局"
                r"|金融监督管理总局[\u4e00-\u9fff]{0,10}监管局"
                r"|金融监督管理总局"
                r"|银保监会[\u4e00-\u9fff]{0,10}监管分局"
                r"|银保监会[\u4e00-\u9fff]{0,10}监管局"
                r"|保监会[\u4e00-\u9fff]{0,10}监管分局"
                r"|保监会[\u4e00-\u9fff]{0,10}监管局"
                r"|监管分局|监管局|银保监局|保监局|银保监会|保监会"
                r"))",
                reg,
            )
            if m:
                case.regulator = m.group(1)
            else:
                # 非法粘连（如含「申请行政复议」）则清空，留给文号兜底
                if re.search(r"申请|复议|诉讼|强制执行|行政处罚决", reg):
                    case.regulator = ""
                    case.field_confidences["regulator"] = FieldConfidence.LOW.value

    # ---------- LLM 纠错 ----------

    def _llm_refine(self, case: ExtractedCase) -> None:
        extracted = {
            f: getattr(case, f)
            for f in ("party_name", "penalty_doc_no", "violation_behavior",
                      "penalty_content", "regulator", "publish_date", "legal_basis")
        }
        try:
            resp = self.llm.complete(
                FIELD_REFINE_PROMPT.format(
                    raw_text=case.raw_text_snippet or "（无原文片段）",
                    extracted_fields=json.dumps(extracted, ensure_ascii=False),
                ),
                max_tokens=500,
                temperature=0.1,
                json_mode=True,
                thinking=ThinkingMode.DISABLED,
            )
            data = json.loads(resp)
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM refine failed for %s: %s", case.file_id, e)
            return

        for field_name, value in data.items():
            if value and not getattr(case, field_name, None):
                setattr(case, field_name, str(value).strip())
                case.field_confidences[field_name] = FieldConfidence.MEDIUM.value
        case.extraction_method = "hybrid"

    # ---------- 校验与置信度 ----------

    # 字段级档位 → 数值；overall 由加权平均得到，避免「字段齐了就 100%」
    _LEVEL_SCORE = {
        FieldConfidence.HIGH.value: 0.92,
        FieldConfidence.MEDIUM.value: 0.72,
        FieldConfidence.LOW.value: 0.38,
    }
    _FIELD_WEIGHTS = {
        "party_name": 1.5,
        "violation_behavior": 1.5,
        "penalty_content": 1.5,
        "regulator": 1.2,
        "penalty_doc_no": 1.0,
        "publish_date": 0.6,
        "fine_amount": 0.5,
        "legal_basis": 0.5,
    }

    def _validate(self, case: ExtractedCase) -> None:
        score = 0.0
        total_w = 0.0
        for field_name, weight in self._FIELD_WEIGHTS.items():
            raw = getattr(case, field_name, None)
            filled = bool(str(raw).strip()) if raw is not None else False
            total_w += weight
            if not filled:
                case.field_confidences.setdefault(field_name, FieldConfidence.LOW.value)
                continue
            level = case.field_confidences.get(field_name, FieldConfidence.MEDIUM.value)
            score += weight * self._LEVEL_SCORE.get(level, 0.55)

        # 抽取路径微调：纯正则略降、表格/金标略升，避免全部顶满
        method_adj = {
            "regex": -0.03,
            "hybrid": 0.0,
            "table": 0.02,
            "gold": 0.04,
            "llm": -0.02,
        }.get(case.extraction_method, 0.0)

        if total_w <= 0:
            case.overall_confidence = 0.0
            return
        case.overall_confidence = round(min(max(score / total_w + method_adj, 0.05), 0.98), 3)

    def _infer_institution_type(self, case: ExtractedCase) -> None:
        name = case.party_name or ""
        blob = f"{name} {case.violation_behavior or ''}"
        entity = normalize_entity(name)
        if entity.entity_type == "责任人员":
            case.institution_type = InstitutionType.INSURANCE_AGENT
            return
        for pattern, type_name in INSTITUTION_TYPE_RULES:
            if re.search(pattern, blob):
                case.institution_type = InstitutionType(type_name)
                return
        case.institution_type = InstitutionType.NON_INSURANCE

    @staticmethod
    def _normalize_date(raw: str) -> str | None:
        if not raw:
            return None
        m = PATTERNS["publish_date"].search(raw)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return None
