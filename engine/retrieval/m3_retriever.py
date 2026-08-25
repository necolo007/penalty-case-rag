"""BGE-M3 dense/sparse 混合检索（任务3 默认后端）。"""

from __future__ import annotations

import asyncio
import logging
import time

from core.config import get_settings
from engine.classification.competition_label_map import (
    cn_tags_to_competition_ids,
    predict_cn_tags_by_keywords,
    resolve_final_cn_tags,
)
from engine.embedding.cache import CachedQueryEncoder
from engine.retrieval.base import RetrievalResponse, SearchQuery, SearchResult
from engine.retrieval.match_reason import build_match_reason
from engine.retrieval.merger import reciprocal_rank_fusion
from engine.retrieval.query_rewriter import QueryRewriter
from engine.retrieval.reranker import Reranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.sparse_retriever import SparseRetriever
from engine.retrieval.vector_retriever import VectorRetriever

logger = logging.getLogger(__name__)

__all__ = ["M3HybridRetriever", "RetrievalResponse"]


class M3HybridRetriever:
    def __init__(
        self,
        *,
        dense: VectorRetriever,
        sparse: SparseRetriever,
        rewriter: QueryRewriter,
        risk_predictor: RiskPredictor,
        query_encoder: CachedQueryEncoder,
        reranker: Reranker,
        fusion_size: int = 120,
        rerank_candidates: int = 80,
        channel_weights: dict[str, float] | None = None,
        rrf_k: int = 60,
        multi_channel_bonus: float = 0.05,
        cn_tag_predict_max: int = 3,
        cn_tag_final_max: int = 5,
        risk_id_cap: int = 3,
        tag_backfill_top_cases: int = 5,
        enable_hyde: bool = False,
        hyde_rerank: bool = False,
        enable_dense_raw: bool = True,
        fusion_mode: str = "max_merge",
        llm_listwise=None,
    ):
        self.dense = dense
        self.sparse = sparse
        self.rewriter = rewriter
        self.risk_predictor = risk_predictor
        self.query_encoder = query_encoder
        self.reranker = reranker
        self.fusion_size = fusion_size
        self.rerank_candidates = rerank_candidates
        self.channel_weights = channel_weights or get_settings().m3_rrf_channel_weights()
        self.rrf_k = rrf_k
        self.multi_channel_bonus = multi_channel_bonus
        self.cn_tag_predict_max = cn_tag_predict_max
        self.cn_tag_final_max = cn_tag_final_max
        self.risk_id_cap = risk_id_cap
        self.tag_backfill_top_cases = tag_backfill_top_cases
        self.enable_hyde = enable_hyde
        self.hyde_rerank = hyde_rerank
        self.enable_dense_raw = enable_dense_raw
        self.fusion_mode = (fusion_mode or "max_merge").strip().lower()
        self.llm_listwise = llm_listwise

    def _fuse_max_merge(
        self, channel_results: dict[str, list[SearchResult]],
    ) -> list[SearchResult]:
        """dense 族按余弦分 max 合并，sparse 仅补位。"""
        best_score: dict[str, float] = {}
        best_row: dict[str, SearchResult] = {}
        for ch in ("dense_raw", "dense", "dense_hyde"):
            for r in channel_results.get(ch, []):
                prev = best_score.get(r.case_id)
                if prev is None or r.score > prev:
                    best_score[r.case_id] = r.score
                    if r.case_id in best_row:
                        r.channels = list(dict.fromkeys(
                            (best_row[r.case_id].channels or []) + (r.channels or [])
                        ))
                    best_row[r.case_id] = r
                elif r.case_id in best_row:
                    existing = best_row[r.case_id]
                    existing.channels = list(dict.fromkeys(
                        (existing.channels or []) + (r.channels or [])
                    ))

        fused = sorted(
            best_row.values(),
            key=lambda r: best_score[r.case_id],
            reverse=True,
        )
        for r in fused:
            r.score = best_score[r.case_id]

        seen = {r.case_id for r in fused}
        sparse_bonus = max(10, self.fusion_size // 10)
        for r in channel_results.get("sparse", []):
            if r.case_id in seen:
                existing = best_row.get(r.case_id)
                if existing is not None and "sparse" not in (existing.channels or []):
                    existing.channels.append("sparse")
                continue
            if sparse_bonus <= 0 or len(fused) >= self.fusion_size:
                break
            r.channels = list(dict.fromkeys((r.channels or []) + ["sparse"]))
            fused.append(r)
            seen.add(r.case_id)
            sparse_bonus -= 1
        return fused[: self.fusion_size]

    def _fuse_weighted_rrf(
        self, channel_results: dict[str, list[SearchResult]],
    ) -> list[SearchResult]:
        """多路加权 RRF（dense_raw / dense / dense_hyde / sparse）。"""
        # 恢复通道名便于权重查找（dense_raw 结果 channels 可能被标成 dense）
        named: dict[str, list[SearchResult]] = {}
        for ch, rows in channel_results.items():
            if not rows:
                continue
            # 复制 channels 标记，避免污染原对象展示
            copied: list[SearchResult] = []
            for r in rows:
                rr = SearchResult(
                    case_id=r.case_id,
                    party_name=r.party_name,
                    violation_behavior=r.violation_behavior,
                    penalty_content=r.penalty_content,
                    regulator=r.regulator,
                    risk_tags=list(r.risk_tags or []),
                    score=r.score,
                    penalty_doc_no=r.penalty_doc_no,
                    risk_type_ids=list(r.risk_type_ids or []),
                    match_reason=r.match_reason,
                    source_file=r.source_file,
                    channels=[ch],
                    highlight_fields=dict(r.highlight_fields or {}),
                )
                copied.append(rr)
            named[ch] = copied

        return reciprocal_rank_fusion(
            named,
            k=self.rrf_k,
            top_k=self.fusion_size,
            weights=self.channel_weights,
            multi_channel_bonus=self.multi_channel_bonus,
        )

    def fuse_channels(
        self, channel_results: dict[str, list[SearchResult]],
    ) -> list[SearchResult]:
        if self.fusion_mode in ("weighted_rrf", "rrf"):
            return self._fuse_weighted_rrf(channel_results)
        return self._fuse_max_merge(channel_results)

    async def retrieve(self, query: SearchQuery) -> RetrievalResponse:
        started = time.perf_counter()

        async def _no_hyde() -> str:
            return ""

        hyde_coro = (
            self.rewriter.hyde(query.query_text)
            if self.enable_hyde and hasattr(self.rewriter, "hyde")
            else _no_hyde()
        )
        rewritten_query, predicted_risk_ids, hyde_text = await asyncio.gather(
            self.rewriter.rewrite(query.query_text),
            self.risk_predictor.predict(query.query_text),
            hyde_coro,
        )
        predicted_cn_tags = predict_cn_tags_by_keywords(
            query.query_text, max_tags=self.cn_tag_predict_max,
        )
        if predicted_cn_tags:
            for cid in cn_tags_to_competition_ids(predicted_cn_tags):
                if cid not in predicted_risk_ids:
                    predicted_risk_ids.append(cid)
        predicted_risk_ids = list(dict.fromkeys(predicted_risk_ids))[: self.risk_id_cap]

        rw_dense, rw_sparse = await self.query_encoder.encode_query_dual(rewritten_query)

        channel_tasks: dict[str, object] = {
            "dense": self.dense.retrieve(query, query_embedding=rw_dense),
            "sparse": self.sparse.retrieve(query, query_sparse=rw_sparse),
        }
        if self.enable_dense_raw:
            raw_dense, _ = await self.query_encoder.encode_query_dual(query.query_text)
            channel_tasks["dense_raw"] = self.dense.retrieve(
                query, query_embedding=raw_dense,
            )
        hyde_text = (hyde_text or "").strip()
        if hyde_text:
            hyde_dense, _ = await self.query_encoder.encode_query_dual(hyde_text)
            channel_tasks["dense_hyde"] = self.dense.retrieve(
                query, query_embedding=hyde_dense,
            )

        channel_outputs = await asyncio.gather(*channel_tasks.values(), return_exceptions=True)

        channel_results: dict[str, list[SearchResult]] = {}
        for channel, output in zip(channel_tasks.keys(), channel_outputs):
            if isinstance(output, BaseException):
                logger.warning("Channel %s failed: %s", channel, output)
                channel_results[channel] = []
            else:
                results = output
                if channel in ("dense_raw", "dense_hyde"):
                    for r in results:
                        # 统一记入 dense 族，便于前端/诊断展示
                        r.channels = ["dense"] if channel == "dense_raw" else ["dense_hyde"]
                channel_results[channel] = results

        fused = self.fuse_channels(channel_results)

        if query.use_reranker:
            candidates = fused[: self.rerank_candidates]
            aux = hyde_text if (self.hyde_rerank and hyde_text) else None
            top = await self.reranker.rerank(
                query.query_text,
                candidates,
                top_k=query.top_k,
                aux_query_text=aux,
            )
        else:
            top = fused[: query.top_k]

        if self.llm_listwise is not None and top:
            top = await self.llm_listwise.rerank(
                query.query_text, top, top_k=query.top_k,
            )

        for r in top:
            r.match_reason = build_match_reason(query.query_text, rewritten_query, r)

        case_tags = [
            t for r in top[: self.tag_backfill_top_cases] for t in (r.risk_tags or [])
        ]
        predicted_cn_tags = resolve_final_cn_tags(
            query_text=query.query_text,
            keyword_tags=predicted_cn_tags,
            case_tags=case_tags,
            competition_ids=predicted_risk_ids,
            max_tags=self.cn_tag_final_max,
        )

        took_ms = int((time.perf_counter() - started) * 1000)
        # rewritten_query 对外仍以改写为主；HyDE 片段附加便于排查
        display_rw = rewritten_query
        if hyde_text:
            display_rw = f"{rewritten_query}\n[hyde] {hyde_text[:200]}"

        return RetrievalResponse(
            query=query.query_text,
            rewritten_query=display_rw,
            predicted_risk_ids=predicted_risk_ids,
            predicted_cn_tags=predicted_cn_tags,
            results=top,
            took_ms=took_ms,
            channel_stats={ch: len(rs) for ch, rs in channel_results.items()},
        )
