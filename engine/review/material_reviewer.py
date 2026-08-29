"""整篇材料合规审查引擎（任务4核心）。

流程：材料文本 → 切分 → 风险句定位（三重判断）
      → 逐风险句：相似案例检索 + 审查意见生成
      → 汇总审查报告（风险高亮位置 + 案例归因 + 整改建议 + 可追溯引用）
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass

import asyncpg

from engine.retrieval.assemble import AnyRetriever
from engine.retrieval.base import SearchQuery
from engine.review.generator import ReviewGenerator
from engine.review.risk_locator import RiskSentence, RiskSentenceLocator
from engine.review.segmenter import segment_text
from pipeline.parser.ocr_normalize import normalize_ocr_text

logger = logging.getLogger(__name__)


@dataclass
class SentenceReview:
    sentence_text: str
    position_start: int
    position_end: int
    paragraph_idx: int
    severity: str
    detection_method: str
    detection_reasons: list[str]
    risk_type_ids: list[str]
    risk_types: list[str]
    retrieved_cases: list[dict]
    compliance_reason: str
    suggestion: str
    confidence: float


@dataclass
class MaterialReviewReport:
    material_id: str
    total_sentences: int
    risk_sentence_count: int
    overall_risk: str                       # high / medium / low / none
    sentence_reviews: list[SentenceReview]
    overall_suggestion: str
    scene: str | None = None
    source_file: str | None = None
    raw_text: str | None = None

    def to_dict(self) -> dict:
        """同时输出后端内部字段与前端兼容字段（risk_sentences / summary）。"""
        payload = asdict(self)
        payload["summary"] = self.overall_suggestion
        payload["file_name"] = self.source_file

        def _case_score(case: dict) -> float:
            try:
                return float(case.get("score") or 0.0)
            except (TypeError, ValueError):
                return 0.0

        risk_sentences: list[dict] = []
        for sr in self.sentence_reviews:
            # 案例列表按检索分降序，保证 Top1 = 最相似
            cases = sorted(
                list(sr.retrieved_cases or []),
                key=_case_score,
                reverse=True,
            )
            top = cases[0] if cases else {}
            hit_score = _case_score(top) if cases else None
            # 风险句卡片不重复展示整改建议（整份材料统一一条，见 overall_suggestion）
            risk_sentences.append(
                {
                    "text": sr.sentence_text,
                    "risk_level": sr.severity,
                    "suggestion": None,
                    "position_start": sr.position_start,
                    "position_end": sr.position_end,
                    "paragraph_idx": sr.paragraph_idx,
                    "risk_types": sr.risk_types,
                    "risk_type_ids": sr.risk_type_ids,
                    "compliance_reason": sr.compliance_reason,
                    "confidence": sr.confidence,
                    "detection_method": sr.detection_method,
                    "detection_reasons": sr.detection_reasons,
                    "retrieved_cases": cases,
                    "hit_score": hit_score,
                    "hit_case_id": top.get("case_id"),
                    "hit_penalty_doc_no": top.get("penalty_doc_no"),
                    "hit_party_name": top.get("party_name"),
                    "case_key_field": (top.get("violation_behavior") or "")[:80] or None,
                    "match_reason": top.get("match_reason"),
                    "source_file": self.source_file or top.get("source_file"),
                }
            )

        # 风险句卡片按 Top1 案例相似度降序
        risk_sentences.sort(
            key=lambda x: float(x["hit_score"]) if x.get("hit_score") is not None else -1.0,
            reverse=True,
        )
        payload["risk_sentences"] = risk_sentences
        payload["case_blocks"] = [
            {
                "block_id": "block-1",
                "paragraph_idx": 0,
                "label": "风险识别结果（按相似度）",
                "risk_sentences": risk_sentences,
            }
        ]
        return payload


class MaterialReviewer:
    def __init__(
        self,
        pool: asyncpg.Pool,
        locator: RiskSentenceLocator,
        retriever: AnyRetriever,
        generator: ReviewGenerator,
        per_sentence_top_k: int = 5,
        max_risk_sentences: int = 20,
    ):
        self.pool = pool
        self.locator = locator
        self.retriever = retriever
        self.generator = generator
        self.per_sentence_top_k = per_sentence_top_k
        self.max_risk_sentences = max_risk_sentences

    async def review(self, raw_text: str, *, scene: str | None = None,
                     source_type: str = "paste", file_name: str | None = None) -> MaterialReviewReport:
        material_id = str(uuid.uuid4())
        raw_text = normalize_ocr_text(raw_text)

        # 落库材料记录
        await self.pool.execute(
            """
            INSERT INTO material_reviews (material_id, source_type, file_name, scene, raw_text, review_status)
            VALUES ($1::uuid, $2, $3, $4, $5, 'reviewing')
            """,
            material_id, source_type, file_name, scene, raw_text,
        )

        try:
            report = await self._do_review(material_id, raw_text, scene)
            report.source_file = file_name
            report.raw_text = raw_text
            await self.pool.execute(
                """
                UPDATE material_reviews
                SET review_status = 'done', total_sentences = $2, risk_sentences = $3,
                    overall_risk = $4, suggestion = $5
                WHERE material_id = $1::uuid
                """,
                material_id, report.total_sentences, report.risk_sentence_count,
                report.overall_risk, report.overall_suggestion,
            )
            return report
        except Exception:
            await self.pool.execute(
                "UPDATE material_reviews SET review_status = 'failed' WHERE material_id = $1::uuid",
                material_id,
            )
            raise

    async def save_human_review(
        self,
        material_id: str,
        *,
        reviewer: str | None = None,
        note: str | None = None,
        status: str = "done",
    ) -> dict:
        """人工复核落库：更新材料审查状态与建议附注。"""
        row = await self.pool.fetchrow(
            "SELECT material_id, suggestion FROM material_reviews WHERE material_id = $1::uuid",
            material_id,
        )
        if not row:
            raise ValueError("material not found")
        merged = row["suggestion"] or ""
        if note:
            merged = (merged + "\n\n【人工复核】" + note).strip()
        await self.pool.execute(
            """
            UPDATE material_reviews
            SET review_status = $2, suggestion = $3
            WHERE material_id = $1::uuid
            """,
            material_id, status, merged,
        )
        return {
            "material_id": material_id,
            "review_status": status,
            "reviewer": reviewer or "",
            "note": note or "",
        }

    async def _do_review(self, material_id: str, raw_text: str,
                         scene: str | None) -> MaterialReviewReport:
        # 1. 切分
        sentences = segment_text(raw_text)

        # 2. 风险句定位
        risk_sentences = await self.locator.locate(sentences, scene=scene)
        risk_sentences = risk_sentences[: self.max_risk_sentences]

        # 3. 逐句检索 + 审查生成
        sentence_reviews: list[SentenceReview] = []
        for rs in risk_sentences:
            sentence_reviews.append(await self._review_sentence(material_id, rs, scene))

        # 4. 汇总：整改对象=整份材料（唯一），不按案例逐条出整改
        overall_risk = self._overall_risk(sentence_reviews)
        risk_items = [
            {
                "text": r.sentence_text,
                "risk_types": r.risk_types,
                "suggestion": r.suggestion,
            }
            for r in sentence_reviews
        ]
        overall_suggestion = self.generator.generate_material_suggestion(
            raw_text, risk_items,
        )

        return MaterialReviewReport(
            material_id=material_id,
            total_sentences=len(sentences),
            risk_sentence_count=len(sentence_reviews),
            overall_risk=overall_risk,
            sentence_reviews=sentence_reviews,
            overall_suggestion=overall_suggestion,
            scene=scene,
        )

    async def _review_sentence(self, material_id: str, rs: RiskSentence,
                               scene: str | None) -> SentenceReview:
        query = SearchQuery(
            query_text=rs.sentence.text,
            scene=scene,
            top_k=self.per_sentence_top_k,
        )
        retrieval = await self.retriever.retrieve(query)
        review = self.generator.generate(rs.sentence.text, retrieval.results)

        # 落库风险句 + 审查日志
        review_id = str(uuid.uuid4())
        await self.pool.execute(
            """
            INSERT INTO review_logs (review_id, query_text, rewritten_query, risk_types, suggestion, raw_response)
            VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb)
            """,
            review_id, rs.sentence.text, retrieval.rewritten_query,
            review.get("risk_types", []), review.get("suggestion", ""),
            json.dumps(review, ensure_ascii=False),
        )
        await self.pool.execute(
            """
            INSERT INTO risk_sentences
                (material_id, sentence_text, position_start, position_end, paragraph_idx,
                 risk_type_ids, severity, detection_method, review_id)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9::uuid)
            """,
            material_id, rs.sentence.text, rs.sentence.start, rs.sentence.end,
            rs.sentence.paragraph_idx, rs.risk_type_ids, rs.severity,
            rs.detection_method, review_id,
        )
        for rank, r in enumerate(retrieval.results, start=1):
            await self.pool.execute(
                """
                INSERT INTO review_case_refs (review_id, case_id, rank, relevance, reason)
                VALUES ($1::uuid, $2, $3, $4, $5)
                ON CONFLICT DO NOTHING
                """,
                review_id, r.case_id, rank, "medium", r.match_reason,
            )

        return SentenceReview(
            sentence_text=rs.sentence.text,
            position_start=rs.sentence.start,
            position_end=rs.sentence.end,
            paragraph_idx=rs.sentence.paragraph_idx,
            severity=rs.severity,
            detection_method=rs.detection_method,
            detection_reasons=rs.reasons,
            risk_type_ids=rs.risk_type_ids,
            risk_types=review.get("risk_types", []),
            retrieved_cases=[
                {
                    "case_id": r.case_id,
                    "penalty_doc_no": r.penalty_doc_no,
                    "party_name": r.party_name,
                    "violation_behavior": r.violation_behavior,
                    "penalty_content": r.penalty_content,
                    "regulator": r.regulator,
                    "score": r.score,
                    "match_reason": r.match_reason,
                    "source_file": r.source_file,
                }
                for r in retrieval.results
            ],
            compliance_reason=review.get("compliance_reason", ""),
            suggestion=review.get("suggestion", ""),
            confidence=float(review.get("confidence", 0.0) or 0.0),
        )

    @staticmethod
    def _overall_risk(reviews: list[SentenceReview]) -> str:
        if not reviews:
            return "none"
        if any(r.severity == "high" for r in reviews):
            return "high"
        if any(r.severity == "medium" for r in reviews):
            return "medium"
        return "low"

    @staticmethod
    def _merge_suggestions(reviews: list[SentenceReview]) -> str:
        suggestions = [r.suggestion for r in reviews if r.suggestion]
        return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(dict.fromkeys(suggestions)))
