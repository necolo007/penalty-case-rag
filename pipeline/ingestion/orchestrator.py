"""三阶段入库编排（任务1+2，对齐赛题交付流程）。

  Stage 1  解析 → 写 raw_text/{file_id}.txt → documents 表
  Stage 2  字段抽取 → 规则初筛（宽松口径）→ 候选标记
  Stage 3  三维词典精筛 + 标签归类 + 摘要 + 向量化 → penalty_cases + case_embeddings（事务）

进度写入 documents.parse_metadata：
  stage / progress_pct / cases_done / cases_total —— 供 API 推导五步 parse_stages。

jsonl 导出由 pipeline/export 从 DB 按需生成，不在入库主链路上阻塞。
"""

import json
import logging
from pathlib import Path

import asyncpg

from core.dates import parse_optional_date
from engine.classification.entity_normalizer import normalize_entity
from engine.classification.insurance_filter import InsuranceFilter
from engine.classification.risk_tagger import RiskTagger
from engine.embedding.provider import BaseEmbeddingProvider
from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import CASE_SUMMARY_PROMPT
from pipeline.extraction.extractor import ExtractorEngine
from pipeline.extraction.schema import ExtractedCase
from pipeline.parser.base import RawDocument
from pipeline.parser.ocr_normalize import normalize_ocr_text
from pipeline.parser.router import DocumentRouter

logger = logging.getLogger(__name__)

# 与前端 / API 五步进度 key 对齐
PARSE_STAGE_DOC = "doc"
PARSE_STAGE_OCR = "ocr"
PARSE_STAGE_EXTRACT = "extract"
PARSE_STAGE_ENTITY = "entity"
PARSE_STAGE_REVIEW = "review"


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
        await self._set_progress(
            doc.file_id,
            status="parsing",
            stage=PARSE_STAGE_DOC,
            progress_pct=5,
        )
        await self._set_progress(
            doc.file_id,
            stage=PARSE_STAGE_OCR,
            progress_pct=12,
        )
        parse_result = self.router.parse(doc)

        if not parse_result.success:
            await self._set_progress(
                doc.file_id,
                status="failed",
                stage=PARSE_STAGE_OCR,
                progress_pct=20,
                error=parse_result.error,
            )
            return {"status": "failed", "file_id": doc.file_id, "error": parse_result.error}

        # 扫描公示表常见「逐字重复」OCR 噪声，入库前归一化
        parse_result.markdown = normalize_ocr_text(parse_result.markdown)

        raw_text_path = self._write_raw_text(doc.file_id, parse_result.markdown)
        parse_meta = {
            k: v for k, v in parse_result.metadata.items() if k != "records"
        }
        parse_meta.update({
            "stage": PARSE_STAGE_OCR,
            "progress_pct": 28,
        })
        await self.pool.execute(
            """
            UPDATE documents
            SET raw_text = $2,
                raw_text_path = $3,
                parse_metadata = COALESCE(parse_metadata, '{}'::jsonb) || $4::jsonb,
                updated_at = NOW()
            WHERE file_id = $1
            """,
            doc.file_id, parse_result.markdown, raw_text_path,
            json.dumps(parse_meta, ensure_ascii=False),
        )

        # ---- Stage 2: 字段抽取 + 规则初筛 ----
        await self._set_progress(
            doc.file_id,
            stage=PARSE_STAGE_EXTRACT,
            progress_pct=35,
        )
        cases = self.extractor.extract(parse_result, file_id=doc.file_id, source_file=doc.file_name)
        for case in cases:
            candidate, reasons = self.insurance_filter.is_candidate(
                case.party_name, case.violation_behavior, case.legal_basis,
            )
            case.is_insurance_candidate = candidate
            case.candidate_reasons = reasons

        await self._set_progress(
            doc.file_id,
            stage=PARSE_STAGE_ENTITY,
            progress_pct=52,
            cases_total=len(cases),
            cases_done=0,
        )

        # ---- Stage 3: 精筛 + 标签 + 摘要 + 向量化 + 入库 ----
        # 重试/重复入库前清掉本文件旧案例，避免 case_id 撞主键与脏数据残留
        await self._clear_cases_for_file(doc.file_id)

        await self._set_progress(
            doc.file_id,
            stage=PARSE_STAGE_REVIEW,
            progress_pct=58,
            cases_total=len(cases),
            cases_done=0,
        )

        stored = 0
        total = len(cases)
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

            # 入库循环中按完成比例上报，避免长任务 UI 卡住
            done_n = idx + 1
            if total <= 1 or done_n == total or done_n % max(1, total // 8) == 0:
                pct = 58 + int(37 * done_n / max(total, 1))
                await self._set_progress(
                    doc.file_id,
                    stage=PARSE_STAGE_REVIEW,
                    progress_pct=min(95, pct),
                    cases_done=done_n,
                    cases_total=total,
                )

        await self._set_progress(
            doc.file_id,
            status="done",
            stage=PARSE_STAGE_REVIEW,
            progress_pct=100,
            cases_done=stored,
            cases_total=total,
        )
        return {"status": "completed", "file_id": doc.file_id, "case_count": stored}

    # ---------- helpers ----------

    async def _clear_cases_for_file(self, file_id: str) -> None:
        """删除某文档已生成的案例及相关引用（embeddings / subject 有 CASCADE）。"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                case_ids = [
                    r["case_id"]
                    for r in await conn.fetch(
                        "SELECT case_id FROM penalty_cases WHERE file_id = $1",
                        file_id,
                    )
                ]
                if not case_ids:
                    return
                # review_case_refs 无 ON DELETE CASCADE
                await conn.execute(
                    "DELETE FROM review_case_refs WHERE case_id = ANY($1::text[])",
                    case_ids,
                )
                await conn.execute(
                    "DELETE FROM penalty_cases WHERE file_id = $1",
                    file_id,
                )
                logger.info(
                    "Cleared %d existing case(s) for file_id=%s before re-ingest",
                    len(case_ids), file_id,
                )

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
        from core.ids import allocate_unique_case_id

        return await allocate_unique_case_id(self.pool)

    async def _store_case(self, case_id: str, case: ExtractedCase, *,
                          regulator: str | None, publish_date: str | None) -> None:
        # 索引文本 = 违法行为 + 处罚内容 + 标签（与检索 query 侧同模型编码）
        embedding_text = " ".join(filter(None, [
            case.violation_behavior, case.penalty_content, " ".join(case.risk_tags),
        ]))
        embedding = None
        sparse = None
        if case.is_insurance_related and embedding_text.strip():
            from engine.embedding.store import encode_documents_maybe_dual

            dense_list, sparse_list = encode_documents_maybe_dual(
                self.embedder, [embedding_text],
            )
            embedding = dense_list[0]
            sparse = sparse_list[0] if sparse_list is not None else None

        last_err: Exception | None = None
        cid = case_id
        for attempt in range(8):
            try:
                await self._insert_case_row(
                    cid, case, regulator=regulator, publish_date=publish_date,
                    embedding=embedding, sparse=sparse,
                )
                return
            except asyncpg.UniqueViolationError as e:
                last_err = e
                logger.warning(
                    "unique violation storing case %s (attempt %d), reallocating: %s",
                    cid, attempt + 1, e,
                )
                cid = await self._next_case_id()
        raise RuntimeError(f"store_case failed after retries: {last_err}") from last_err

    async def _insert_case_row(
        self,
        case_id: str,
        case: ExtractedCase,
        *,
        regulator: str | None,
        publish_date: str | None,
        embedding: list[float] | None,
        sparse: dict[str, float] | None = None,
    ) -> None:
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
                        $10, $11, $12, $13, $14, $15, $16, $17, $18, $19::jsonb, $20
                    )
                    """,
                    case_id, case.file_id, case.party_name, case.institution_type.value,
                    case.penalty_doc_no, case.violation_behavior, case.penalty_content,
                    case.fine_amount, case.regulator or regulator,
                    parse_optional_date(case.publish_date or publish_date), case.legal_basis,
                    case.is_insurance_related, case.is_insurance_candidate,
                    case.candidate_reasons, case.risk_tags, case.risk_type_ids,
                    case.case_summary, case.overall_confidence,
                    json.dumps(case.field_confidences, ensure_ascii=False),
                    case.extraction_method,
                )

                if embedding is not None:
                    from core.db import to_pgvector
                    from engine.embedding.store import UPSERT_EMBEDDING_SQL, upsert_embedding_args
                    from engine.retrieval.assemble import get_sparse_index

                    await conn.execute(
                        UPSERT_EMBEDDING_SQL,
                        *upsert_embedding_args(
                            case_id,
                            embedding,
                            self.embedder.model_name,
                            sparse=sparse,
                            to_pgvector=to_pgvector,
                        ),
                    )
                    if sparse is not None:
                        get_sparse_index().upsert(case_id, sparse)

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
        await self._set_progress(file_id, status=status, error=error)

    async def _set_progress(
        self,
        file_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress_pct: int | None = None,
        cases_done: int | None = None,
        cases_total: int | None = None,
        error: str | None = None,
    ) -> None:
        """更新 parse_status，并合并写入 parse_metadata 进度字段。"""
        patch: dict = {}
        if stage is not None:
            patch["stage"] = stage
        if progress_pct is not None:
            patch["progress_pct"] = max(0, min(100, int(progress_pct)))
        if cases_done is not None:
            patch["cases_done"] = int(cases_done)
        if cases_total is not None:
            patch["cases_total"] = int(cases_total)
        if status == "failed" and stage is not None:
            patch["failed_stage"] = stage

        await self.pool.execute(
            """
            UPDATE documents
            SET parse_status = COALESCE($2, parse_status),
                parse_error = CASE
                    WHEN $2 IN ('parsing', 'pending', 'done') THEN NULL
                    WHEN $3::boolean THEN $4
                    ELSE parse_error
                END,
                parse_metadata = COALESCE(parse_metadata, '{}'::jsonb) || $5::jsonb,
                updated_at = NOW()
            WHERE file_id = $1
            """,
            file_id,
            status,
            error is not None,
            error,
            json.dumps(patch, ensure_ascii=False),
        )
