"""字段抽取引擎：公示表映射 + 长文 LLM 主抽（短字段正则回填）+ 轻量校验。

两条输入路径：
  ① 公示表解析结果（TableParser 已输出结构化 records）→ 直接映射
  ② 长文本 Markdown（决定书/OCR）→ 默认 LLM 提示词主抽长字段；
     文号/机关等短字段用正则回填空值、低置信或覆盖弱 LLM 值；
     无 LLM / 抽取失败时回退正则；regex_first 模式则正则主抽 + 低置信度纠错
"""

import json
import logging
import re
from typing import Any

from engine.classification.entity_normalizer import normalize_entity
from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT,
    FIELD_REFINE_PROMPT,
)
from pipeline.extraction.regex_patterns import (
    DOCNO_REGION_REGULATOR,
    INSTITUTION_TYPE_RULES,
    PATTERNS,
)
from pipeline.extraction.schema import ExtractedCase, FieldConfidence, InstitutionType
from pipeline.parser.base import ParseResult
from pipeline.parser.ocr_normalize import normalize_ocr_text

logger = logging.getLogger(__name__)

CORE_FIELDS = ["party_name", "violation_behavior", "penalty_content", "regulator"]
DEFAULT_LLM_REFINE_THRESHOLD = 0.6
DEFAULT_EXTRACTION_MODE = "llm_first"
DEFAULT_EXTRACTION_LLM_MAX_CHARS = 8000

# 无地区限定的顶层机关裸词：信息量低于带地区的具体机关名，即便字数更多也不应
# 在候选择优时占先（见 _from_text_regex 的 regulator 兜底逻辑）。
_BARE_REGULATOR_NAMES = {"国家金融监督管理总局", "中国银保监会", "中国保监会"}

_LLM_INSTITUTION_MAP: dict[str, InstitutionType | None] = {
    "寿险公司": InstitutionType.LIFE_INSURANCE,
    "财险公司": InstitutionType.PROPERTY_INSURANCE,
    "保险代理": InstitutionType.INSURANCE_AGENCY,
    "保险经纪": InstitutionType.INSURANCE_AGENCY,
    "保险代理/中介": InstitutionType.INSURANCE_AGENCY,
    "保险公司": None,  # 过粗，交给规则从当事人名称细判
    "其他": InstitutionType.OTHER_FINANCIAL,
    "其他金融机构": InstitutionType.OTHER_FINANCIAL,
    "非保险": InstitutionType.NON_INSURANCE,
    "无法判断": None,
}

# LLM 主抽后：长字段保留 LLM；短字段按策略用正则加固精确匹配。
_SHORT_FIELDS_PREFER_REGEX = ("penalty_doc_no", "regulator")
_SHORT_FIELDS_FILL_IF_EMPTY = ("party_name",)


def _matched_text(m: "re.Match") -> str:
    """兼容含多个可选捕获组（转折短语懒惰分支 / 定长兜底分支）的模式。"""
    for g in m.groups():
        if g:
            return g
    return m.group(0)


def _parse_json_object(raw: str) -> dict[str, Any]:
    """解析模型 JSON；容忍偶发 Markdown 代码围栏。"""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


class ExtractorEngine:
    def __init__(
        self,
        llm_client: DeepSeekClient | None = None,
        use_llm_refine: bool = True,
        *,
        llm_refine_threshold: float | None = None,
        extraction_mode: str | None = None,
        extraction_llm_max_chars: int | None = None,
    ):
        self.llm = llm_client
        self.use_llm_refine = use_llm_refine
        settings = None
        try:
            from core.config import get_settings
            settings = get_settings()
        except Exception:  # noqa: BLE001
            settings = None

        if llm_refine_threshold is None:
            llm_refine_threshold = (
                settings.LLM_REFINE_THRESHOLD if settings else DEFAULT_LLM_REFINE_THRESHOLD
            )
        self.llm_refine_threshold = llm_refine_threshold

        if extraction_mode is None:
            extraction_mode = (
                settings.EXTRACTION_MODE if settings else DEFAULT_EXTRACTION_MODE
            )
        mode = (extraction_mode or DEFAULT_EXTRACTION_MODE).strip().lower()
        self.extraction_mode = mode if mode in ("llm_first", "regex_first") else DEFAULT_EXTRACTION_MODE

        if extraction_llm_max_chars is None:
            extraction_llm_max_chars = (
                settings.EXTRACTION_LLM_MAX_CHARS
                if settings
                else DEFAULT_EXTRACTION_LLM_MAX_CHARS
            )
        self.extraction_llm_max_chars = max(1000, int(extraction_llm_max_chars))

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
            # 扫描 OCR 兜底：逐字重复等噪声先归一再切分/抽取
            text = normalize_ocr_text(parse_result.markdown)
            if text != parse_result.markdown:
                parse_result.markdown = text
            # 路径②：长文本 → 按文号切分多案例后分别抽取
            segments = self._split_case_segments(parse_result.markdown)
            cases = []
            for seg in segments:
                case = self._from_text(seg, file_id=file_id, source_file=source_file)
                if case:
                    cases.append(case)
            if not cases:
                case = self._from_text(
                    parse_result.markdown, file_id=file_id, source_file=source_file,
                )
                cases = [case] if case else []

        for case in cases:
            self._finalize_institution_type(case)
            self._validate(case)
            # LLM 已主抽（含 hybrid 短字段回填）时不再二次 refine
            if (
                case.extraction_method not in ("llm", "hybrid")
                and case.overall_confidence < self.llm_refine_threshold
                and self.use_llm_refine
                and self.llm is not None
            ):
                self._llm_refine(case)
                self._validate(case)
        return cases

    def _finalize_institution_type(self, case: ExtractedCase) -> None:
        """机构类型：LLM 已给出明确类型则保留；否则规则细判。"""
        if getattr(case, "_institution_locked", False):
            return
        self._infer_institution_type(case)

    def _from_text(self, text: str, *, file_id: str, source_file: str) -> ExtractedCase | None:
        """长文抽取入口：按 EXTRACTION_MODE 选择 LLM 主抽或正则主抽。"""
        if not text.strip():
            return None
        prefer_llm = self.extraction_mode == "llm_first" and self.llm is not None
        if prefer_llm:
            case = self._from_text_llm(text, file_id=file_id, source_file=source_file)
            if case is not None:
                return case
            logger.warning("LLM extraction failed for %s, fallback to regex", file_id)
        return self._from_text_regex(text, file_id=file_id, source_file=source_file)

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

    # ---------- 路径②：长文本切分 ----------

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

    # ---------- 路径②a：LLM 主抽 ----------

    def _from_text_llm(self, text: str, *, file_id: str, source_file: str) -> ExtractedCase | None:
        case_text = text.strip()
        if len(case_text) > self.extraction_llm_max_chars:
            case_text = case_text[: self.extraction_llm_max_chars]
        try:
            resp = self.llm.complete(
                EXTRACTION_USER_PROMPT.format(case_text=case_text),
                system=EXTRACTION_SYSTEM_PROMPT,
                max_tokens=1600,
                temperature=0.1,
                json_mode=True,
                thinking=ThinkingMode.DISABLED,
            )
            data = _parse_json_object(resp)
            if not isinstance(data, dict):
                return None
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM extraction call failed for %s: %s", file_id, e)
            return None

        case = ExtractedCase(
            file_id=file_id,
            source_file=source_file,
            extraction_method="llm",
            raw_text_snippet=self._build_evidence_snippet(text),
        )
        self._apply_llm_fields(case, data)
        # 轻量补齐：日期/金额/依据不在主 Prompt 内，用正则从原文摘
        self._supplement_aux_fields(case, text)
        self._sanitize_fields(case)

        # 短字段混合：跑一遍正则，回填空/低置信，并保住文号/机关精确匹配
        regex_case = self._from_text_regex(text, file_id=file_id, source_file=source_file)
        if regex_case is not None:
            self._merge_regex_short_fields(case, regex_case)

        # 至少一个核心字段才算成功，否则交给正则兜底
        if not any(getattr(case, f) for f in CORE_FIELDS):
            return None
        return case

    def _merge_regex_short_fields(
        self, llm_case: ExtractedCase, regex_case: ExtractedCase,
    ) -> bool:
        """用正则加固短字段，长字段（违法事实/处罚内容）始终保留 LLM。

        策略：
        - penalty_doc_no / regulator：正则有可用值（非空且非 LOW）时优先采用，
          以保住精确匹配；LLM 仅在正则缺失时保留。
        - party_name：仅当 LLM 为空或 LOW 时回填（避免覆盖一案两罚主体选择）。
        """
        changed = False

        for field in _SHORT_FIELDS_PREFER_REGEX:
            rx_val = (getattr(regex_case, field) or "").strip()
            if not rx_val:
                continue
            rx_conf = regex_case.field_confidences.get(field, FieldConfidence.MEDIUM.value)
            llm_val = (getattr(llm_case, field) or "").strip()
            llm_empty = self._field_empty_or_low(llm_case, field)

            # 正则 LOW：仅救急空/低置信 LLM
            if rx_conf == FieldConfidence.LOW.value and not llm_empty:
                continue
            if llm_val == rx_val:
                llm_case.field_confidences[field] = rx_conf
                continue

            # 正则可用（或 LLM 空）：采用正则，保住文号/机关精确匹配
            setattr(llm_case, field, rx_val)
            llm_case.field_confidences[field] = rx_conf
            changed = True

        for field in _SHORT_FIELDS_FILL_IF_EMPTY:
            if not self._field_empty_or_low(llm_case, field):
                continue
            rx_val = (getattr(regex_case, field) or "").strip()
            if not rx_val:
                continue
            rx_conf = regex_case.field_confidences.get(field, FieldConfidence.MEDIUM.value)
            setattr(llm_case, field, rx_val)
            llm_case.field_confidences[field] = rx_conf
            changed = True

        if changed:
            llm_case.extraction_method = "hybrid"
            self._sanitize_fields(llm_case)
        return changed

    @staticmethod
    def _field_empty_or_low(case: ExtractedCase, field: str) -> bool:
        val = (getattr(case, field, None) or "").strip()
        if not val:
            return True
        conf = case.field_confidences.get(field, FieldConfidence.LOW.value)
        return conf == FieldConfidence.LOW.value

    def _apply_llm_fields(self, case: ExtractedCase, data: dict[str, Any]) -> None:
        str_fields = (
            "party_name",
            "penalty_doc_no",
            "violation_behavior",
            "penalty_content",
            "regulator",
            "case_summary",
        )
        for name in str_fields:
            raw = data.get(name)
            if raw is None:
                case.field_confidences[name] = FieldConfidence.LOW.value
                continue
            value = str(raw).strip()
            if not value or value.lower() == "null":
                case.field_confidences[name] = FieldConfidence.LOW.value
                continue
            setattr(case, name, value)
            case.field_confidences[name] = FieldConfidence.HIGH.value

        inst_raw = data.get("institution_type")
        if inst_raw is not None and str(inst_raw).strip() and str(inst_raw).lower() != "null":
            label = str(inst_raw).strip()
            if label in _LLM_INSTITUTION_MAP:
                mapped = _LLM_INSTITUTION_MAP[label]
                if mapped is not None:
                    case.institution_type = mapped
                    setattr(case, "_institution_locked", True)
                elif label == "非保险":
                    case.institution_type = InstitutionType.NON_INSURANCE
                    setattr(case, "_institution_locked", True)
                # 「保险公司」/无法判断 → 不锁定，交给规则从当事人细判
            else:
                # 未知标签不锁定，避免脏值写死
                logger.debug("Unknown institution_type from LLM: %s", label)

        related = data.get("is_insurance_related")
        if related is True:
            case.is_insurance_related = True
        elif related is False:
            case.is_insurance_related = False

    def _supplement_aux_fields(self, case: ExtractedCase, text: str) -> None:
        """主抽后补齐日期/金额/依据（轻量正则，不作主抽取）。"""
        if not case.publish_date:
            m = PATTERNS["publish_date"].search(text)
            if m:
                case.publish_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                case.field_confidences["publish_date"] = FieldConfidence.MEDIUM.value
        if not case.fine_amount and case.penalty_content:
            m = PATTERNS["fine_amount"].search(case.penalty_content)
            if m:
                case.fine_amount = m.group(1)
                case.field_confidences["fine_amount"] = FieldConfidence.MEDIUM.value
        if not case.fine_amount:
            m = PATTERNS["fine_amount"].search(text)
            if m:
                case.fine_amount = m.group(1)
                case.field_confidences["fine_amount"] = FieldConfidence.MEDIUM.value
        if not case.legal_basis:
            m = PATTERNS["legal_basis"].search(text)
            if m:
                case.legal_basis = _matched_text(m).strip()
                case.field_confidences["legal_basis"] = FieldConfidence.MEDIUM.value

    # ---------- 路径②b：正则主抽（兜底 / regex_first） ----------

    def _from_text_regex(self, text: str, *, file_id: str, source_file: str) -> ExtractedCase | None:
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
            # 抬头；收集全文候选，优先挑带地区的具体机关名。
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
                cleaned = cls._extend_party_across_linebreak(cleaned, text)
                if cleaned and not cls._is_party_noise(cleaned):
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
            cleaned = cls._extend_party_across_linebreak(cleaned, text)
            if cleaned and not cls._is_party_noise(cleaned):
                pri = pri_base + (1 if cls._looks_like_institution(cleaned) else 0)
                candidates.append((cleaned, conf, pri))

        if not candidates:
            return "", FieldConfidence.LOW.value

        seen: set[str] = set()
        uniq: list[tuple[str, str, int]] = []
        for item in candidates:
            if item[0] in seen:
                continue
            seen.add(item[0])
            uniq.append(item)
        uniq.sort(
            key=lambda x: (x[2], len(x[0]) if cls._looks_like_institution(x[0]) else 0),
            reverse=True,
        )
        return uniq[0][0], uniq[0][1]

    @staticmethod
    def _extend_party_across_linebreak(name: str, text: str) -> str:
        """跨断行拼接被截断的当事人名称。"""
        if not name:
            return name
        idx = text.find(name)
        if idx == -1:
            return name
        end = idx + len(name)
        if end >= len(text) or text[end] != "\n":
            return name
        rest = text[end + 1:end + 61]
        stop_markers = ("当事人", "住所", "地址", "身份证", "职务：", "统一社会信用代码",
                        "案由", "主要违法", "违法事实", "违法行为", "\n", "：", ":")
        cut = len(rest)
        for marker in stop_markers:
            p = rest.find(marker)
            if p != -1:
                cut = min(cut, p)
        continuation = rest[:cut]
        if not continuation or not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9（）()]{1,50}", continuation):
            return name
        open_parens = name.count("（") + name.count("(")
        close_parens = name.count("）") + name.count(")")
        if open_parens > close_parens:
            m = re.search(r"^([\u4e00-\u9fffA-Za-z0-9]{1,50}?[）)])", continuation)
            return name + m.group(1) if m else name
        if re.search(r"(?:公司|支公司|分公司|中心支公司|营业部|服务部|电销中心)$", continuation):
            return name + continuation
        return name

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
        name = re.sub(r"^(?:名称|姓名)\s*[：:]\s*", "", name)
        if "，" in name or "," in name:
            parts = re.split(r"[，,]", name, maxsplit=1)
            if ExtractorEngine._looks_like_institution(parts[0]) and not ExtractorEngine._looks_like_institution(parts[1] if len(parts) > 1 else ""):
                name = parts[0].strip()
        m = re.search(r"^(.+?[（(]以下简称[^）)]*[）)])", name)
        if m:
            name = m.group(1)
        else:
            m = re.search(r"^(.+?[（(]以下简称)", name)
            if m and not re.search(r"[）)]", name[m.end():m.end() + 40]):
                name = m.group(1)
            else:
                name = re.split(
                    r"(?:告知了|作出行政|行政处罚|强制执行|划款凭证|抄报我局|"
                    r"营业地址|住\s*所|地址|身份证号|职务)",
                    name,
                    maxsplit=1,
                )[0].strip(" ，,、")
        if name.count(")") + name.count("）") > name.count("(") + name.count("（"):
            name = re.sub(r"[）)]\s*$", "", name).strip()
        return name.strip()[:80]

    @staticmethod
    def _sanitize_fields(case: ExtractedCase) -> None:
        """清洗当事人/机关噪声，对齐常见公示截断写法。"""
        if case.party_name:
            name = ExtractorEngine._clean_party_candidate(case.party_name)
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
                if re.search(r"申请|复议|诉讼|强制执行|行政处罚决", reg):
                    case.regulator = ""
                    case.field_confidences["regulator"] = FieldConfidence.LOW.value

    # ---------- LLM 纠错（regex_first / 表格低置信度） ----------

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
            data = _parse_json_object(resp)
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM refine failed for %s: %s", case.file_id, e)
            return

        for field_name, value in data.items():
            if value and not getattr(case, field_name, None):
                setattr(case, field_name, str(value).strip())
                case.field_confidences[field_name] = FieldConfidence.MEDIUM.value
        case.extraction_method = "hybrid"

    # ---------- 校验与置信度 ----------

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

        method_adj = {
            "regex": -0.03,
            "hybrid": 0.0,
            "table": 0.02,
            "gold": 0.04,
            "llm": 0.01,
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
