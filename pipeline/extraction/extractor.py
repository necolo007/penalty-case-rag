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
LLM_REFINE_THRESHOLD = 0.6


class ExtractorEngine:
    def __init__(self, llm_client: DeepSeekClient | None = None, use_llm_refine: bool = True):
        self.llm = llm_client
        self.use_llm_refine = use_llm_refine

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
            # 路径②：长文本正则抽取（单文档单案例；多案例决定书由段落切分扩展）
            case = self._from_text(parse_result.markdown, file_id=file_id, source_file=source_file)
            cases = [case] if case else []

        for case in cases:
            self._infer_institution_type(case)
            self._validate(case)
            if (case.overall_confidence < LLM_REFINE_THRESHOLD
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

    def _from_text(self, text: str, *, file_id: str, source_file: str) -> ExtractedCase | None:
        if not text.strip():
            return None

        case = ExtractedCase(
            file_id=file_id, source_file=source_file,
            extraction_method="regex",
            raw_text_snippet=text[:500],
        )

        for field_name in ("penalty_doc_no", "party_name", "violation_behavior",
                           "penalty_content", "fine_amount", "legal_basis"):
            m = PATTERNS[field_name].search(text)
            if m:
                setattr(case, field_name, m.group(1).strip())
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
                case.violation_behavior = m.group(1).strip()[:500]
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
            # 金标常见截断：公司名(以下简称
            m = re.search(r"^(.+?)\(以下简称", name)
            if m:
                name = m.group(1).rstrip() + "(以下简称"
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
            # 截到机关名为止，去掉「行政处罚决定…」尾巴
            m = re.search(
                r"^([\u4e00-\u9fff]{2,40}?(?:监管分局|监管局|银保监局|保监局|"
                r"金融监督管理总局|银保监会|保监会))",
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
