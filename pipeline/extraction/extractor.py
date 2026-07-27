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
        # 同一文号在正文中重复出现（页眉/页脚/多次引用）不代表多案例，需先去重
        docnos: list[re.Match] = []
        seen_no: set[str] = set()
        for m in PATTERNS["penalty_doc_no"].finditer(text):
            key = re.sub(r"\s+", "", m.group(1))
            if key in seen_no:
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

        for field_name in ("penalty_doc_no", "party_name", "violation_behavior",
                           "penalty_content", "fine_amount", "legal_basis"):
            m = PATTERNS[field_name].search(text)
            if m:
                setattr(case, field_name, _matched_text(m).strip())
                case.field_confidences[field_name] = FieldConfidence.HIGH.value
            else:
                case.field_confidences[field_name] = FieldConfidence.LOW.value

        if not case.party_name:
            m = PATTERNS["party_name_alt"].search(text)
            if m:
                case.party_name = m.group(1).strip()
                case.field_confidences["party_name"] = FieldConfidence.MEDIUM.value

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
            m = PATTERNS["regulator_inline"].search(text)
            if m:
                case.regulator = m.group(1).strip()
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
        return case

    @staticmethod
    def _sanitize_fields(case: ExtractedCase) -> None:
        """清洗当事人/机关噪声，对齐常见公示截断写法。"""
        if case.party_name:
            name = case.party_name.strip(" ：:\t")
            # 金标常见写法：公司名(以下简称XX) —— 需保留完整括注，
            # 之前只截到「(以下简称」四字、丢掉简称与右括号，导致必然不等。
            m = re.search(r"^(.+?[（(]以下简称[^）)]*[）)])", name)
            if m:
                name = m.group(1)
            else:
                # 去掉尾部「告知了…」「行政处罚…」等粘连
                name = re.split(
                    r"(?:告知了|作出行政|行政处罚|强制执行|划款凭证|抄报我局)",
                    name,
                    maxsplit=1,
                )[0].strip(" ，,、")
            # 明显噪声：过短、或含非主体词
            junk = ("名称的", "留待申请", "复印件", "强制执行")
            if len(name) < 2 or any(j in name for j in junk):
                case.party_name = ""
                case.field_confidences["party_name"] = FieldConfidence.LOW.value
            else:
                case.party_name = name[:80]

        if case.regulator:
            reg = case.regulator.strip()
            # 截到机关名为止，去掉「行政处罚决定…」尾巴。
            # 「金融监督管理总局」后常跟地区+「监管局/监管分局」（2023 新称谓），
            # 该分支必须放在前面，否则懒惰量词会在「总局」处过早停止，丢掉地区部分。
            m = re.search(
                r"^([\u4e00-\u9fff]{2,40}?(?:"
                r"金融监督管理总局[\u4e00-\u9fff]{0,10}监管分局"
                r"|金融监督管理总局[\u4e00-\u9fff]{0,10}监管局"
                r"|金融监督管理总局"
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
