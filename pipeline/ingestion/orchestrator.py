"""三阶段入库编排（任务1+2，对齐赛题交付流程）。

  Stage 1  解析 → 写 raw_text/{file_id}.txt → documents 表
  Stage 2  字段抽取 → 规则初筛（宽松口径）→ 候选标记
  Stage 3  三维词典精筛 + 标签归类 + 摘要 + 向量化 → penalty_cases + case_embeddings（事务）

jsonl 导出由 pipeline/export 从 DB 按需生成，不在入库主链路上阻塞。
"""

import json
import logging
from pathlib import Path

import asyncpg

from core.db import to_pgvector
from engine.classification.entity_normalizer import normalize_entity
from engine.classification.insurance_filter import InsuranceFilter
from engine.classification.risk_tagger import RiskTagger
from engine.embedding.provider import BaseEmbeddingProvider
from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import CASE_SUMMARY_PROMPT
from pipeline.extraction.extractor import ExtractorEngine
from pipeline.extraction.schema import ExtractedCase
from pipeline.parser.base import RawDocument
from pipeline.parser.router import DocumentRouter

logger = logging.getLogger(__name__)


class IngestOrchestrator:
    def __init__(
        self,
        pool: asyncpg.Pool,
        router: DocumentRouter,
        extractor: ExtractorEngine,
        insurance_filter: InsuranceFilter,
        risk_tagger: RiskTagger,
        embedder: BaseEmbeddingProvider,
        llm: DeepSeekClient | None = None,
        data_dir: str = "./data",
        generate_summary: bool = True,
    ):
        self.pool = pool
        self.router = router
        self.extractor = extractor
        self.insurance_filter = insurance_filter
        self.risk_tagger = risk_tagger
        self.embedder = embedder
        self.llm = llm
        self.data_dir = Path(data_dir)
        self.generate_summary = generate_summary

    async def ingest_document(self, doc: RawDocument, *, regulator: str | None = None,
                              publish_date: str | None = None) -> dict:
        # ---- Stage 1: 解析 ----
        await self._set_status(doc.file_id, "parsing")
        parse_result = self.router.parse(doc)

        if not parse_result.success:
            await self._set_status(doc.file_id, "failed", error=parse_result.error)
            return {"status": "failed", "file_id": doc.file_id, "error": parse_result.error}

        raw_text_path = self._write_raw_text(doc.file_id, parse_result.markdown)
        await self.pool.execute(
            """
            UPDATE documents
            SET raw_text = $2, raw_text_path = $3, parse_metadata = $4::jsonb,
                updated_at = NOW()
            WHERE file_id = $1
            """,
            doc.file_id, parse_result.markdown, raw_text_path,
            json.dumps(
                {k: v for k, v in parse_result.metadata.items() if k != "records"},
                ensure_ascii=False,
            ),
        )

        # ---- Stage 2: 字段抽取 + 规则初筛 ----
        cases = self.extractor.extract(parse_result, file_id=doc.file_id, source_file=doc.file_name)
        for case in cases:
            candidate, reasons = self.insurance_filter.is_candidate(
                case.party_name, case.violation_behavior, case.legal_basis,
            )
            case.is_insurance_candidate = candidate
            case.candidate_reasons = reasons

        # ---- Stage 3: 精筛 + 标签 + 摘要 + 向量化 + 入库 ----
        stored = 0
        for idx, case in enumerate(cases):
            score = self.insurance_filter.score(
                case.party_name, case.violation_behavior, case.legal_basis,
            )
            case.is_insurance_related = score.is_insurance

            if case.is_insurance_related and case.violation_behavior:
                tags = await self.risk_tagger.classify(case.violation_behavior)
                case.internal_tag_ids = tags["internal_ids"]
                case.risk_type_ids = tags["competition_ids"]
                case.risk_tags = tags["display_tags"]
                if self.generate_summary:
                    case.case_summary = self._summarize(case)

            case_id = await self._next_case_id()
            await self._store_case(case_id, case, regulator=regulator, publish_date=publish_date)
            stored += 1

        await self._set_status(doc.file_id, "done")
        return {"status": "completed", "file_id": doc.file_id, "case_count": stored}

    # ---------- helpers ----------

    def _write_raw_text(self, file_id: str, text: str) -> str:
        raw_dir = self.data_dir / "raw_text"
        raw_dir.mkdir(parents=True, exist_ok=True)
        rel_path = f"raw_text/{file_id}.txt"
        (self.data_dir / rel_path).write_text(text, encoding="utf-8")
        return rel_path

    def _summarize(self, case: ExtractedCase) -> str:
        if self.llm is None:
            return f"{case.party_name}因{case.violation_behavior[:40]}被处罚。"
        try:
            return self.llm.complete(
                CASE_SUMMARY_PROMPT.format(
                    party_name=case.party_name,
                    violation_behavior=case.violation_behavior[:300],
                    penalty_content=case.penalty_content[:200],
                ),
                max_tokens=200,
                temperature=0.3,
                thinking=ThinkingMode.DISABLED,
            ).strip()
        except Exception as e:  # noqa: BLE001
            logger.warning("Summary generation failed: %s", e)
            return f"{case.party_name}因{case.violation_behavior[:40]}被处罚。"

    async def _next_case_id(self) -> str:
        row = await self.pool.fetchrow(
            "SELECT COUNT(*) + 1 AS n FROM penalty_cases"
        )
        return f"C{row['n']:06d}"

    async def _store_case(self, case_id: str, case: ExtractedCase, *,
                          regulator: str | None, publish_date: str | None) -> None:
        # 索引文本 = 违法行为 + 处罚内容 + 标签（与检索 query 侧同模型编码）
        embedding_text = " ".join(filter(None, [
            case.violation_behavior, case.penalty_content, " ".join(case.risk_tags),
        ]))
        embedding = None
        if case.is_insurance_related and embedding_text.strip():
            embedding = self.embedder.encode_documents([embedding_text])[0]

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO penalty_cases (
                        case_id, file_id, party_name, institution_type, penalty_doc_no,
                        violation_behavior, penalty_content, fine_amount, regulator,
                        publish_date, legal_basis,
                        is_insurance_related, is_insurance_candidate, candidate_reasons,
                        risk_tags, risk_type_ids, case_summary,
                        overall_confidence, field_confidences, extraction_method
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9,
                        $10::date, $11, $12, $13, $14, $15, $16, $17, $18, $19::jsonb, $20
                    )
                    """,
                    case_id, case.file_id, case.party_name, case.institution_type.value,
                    case.penalty_doc_no, case.violation_behavior, case.penalty_content,
                    case.fine_amount, case.regulator or regulator,
                    case.publish_date or publish_date, case.legal_basis,
                    case.is_insurance_related, case.is_insurance_candidate,
                    case.candidate_reasons, case.risk_tags, case.risk_type_ids,
                    case.case_summary, case.overall_confidence,
                    json.dumps(case.field_confidences, ensure_ascii=False),
                    case.extraction_method,
                )

                if embedding is not None:
                    await conn.execute(
                        """
                        INSERT INTO case_embeddings (case_id, embedding, embedding_model)
                        VALUES ($1, $2::vector, $3)
                        """,
                        case_id, to_pgvector(embedding), self.embedder.model_name,
                    )

                # 主体关联表（任务2交付物）
                entity = normalize_entity(case.party_name)
                await conn.execute(
                    """
                    INSERT INTO subject_relations
                        (case_id, raw_party_name, normalized_name, entity_type, confidence)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    case_id, entity.raw_name, entity.normalized_name,
                    entity.entity_type, entity.confidence,
                )

    async def _set_status(self, file_id: str, status: str, error: str | None = None) -> None:
        await self.pool.execute(
            """
            UPDATE documents SET parse_status = $2, parse_error = $3, updated_at = NOW()
            WHERE file_id = $1
            """,
            file_id, status, error,
        )
