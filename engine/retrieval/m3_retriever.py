"""BGE-M3 dense + sparse 混合检索引擎（任务3默认后端）。

管线：
  原始 query → LLM/同义词改写（+ 可选 HyDE）→ BGE-M3 encode
             → dense(原文) / dense(改写) / dense(HyDE) / sparse 并行召回
             → dense 余弦 max 合并 + sparse 补位 → Reranker 精排 → Top-K

HyDE：用 LLM 生成「假想违法事实」（决定书语体）再 embed，缩小口语↔文书鸿沟。
"""

from __future__ import annotations

import asyncio
import logging
import time

from engine.classification.competition_label_map import (
    cn_tags_to_competition_ids,
    predict_cn_tags_by_keywords,
    resolve_final_cn_tags,
)
from engine.embedding.cache import CachedQueryEncoder
from engine.retrieval.base import RetrievalResponse, SearchQuery, SearchResult
from engine.retrieval.match_reason import build_match_reason
from engine.retrieval.query_rewriter import QueryRewriter
from engine.retrieval.reranker import Reranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.sparse_retriever import SparseRetriever
from engine.retrieval.vector_retriever import VectorRetriever

logger = logging.getLogger(__name__)

DEFAULT_M3_WEIGHTS = {
    "dense_raw": 1.6,
    "dense": 1.5,
    "dense_hyde": 1.55,
    "sparse": 0.55,
}

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
    ):
        self.dense = dense
        self.sparse = sparse
        self.rewriter = rewriter
        self.risk_predictor = risk_predictor
        self.query_encoder = query_encoder
        self.reranker = reranker
        self.fusion_size = fusion_size
        self.rerank_candidates = rerank_candidates
        self.channel_weights = channel_weights or dict(DEFAULT_M3_WEIGHTS)
        self.rrf_k = rrf_k
        self.multi_channel_bonus = multi_channel_bonus
        self.cn_tag_predict_max = cn_tag_predict_max
        self.cn_tag_final_max = cn_tag_final_max
        self.risk_id_cap = risk_id_cap
        self.tag_backfill_top_cases = tag_backfill_top_cases
        self.enable_hyde = enable_hyde
        self.hyde_rerank = hyde_rerank

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

        raw_dense, _ = await self.query_encoder.encode_query_dual(query.query_text)
        rw_dense, rw_sparse = await self.query_encoder.encode_query_dual(rewritten_query)

        channel_tasks: dict[str, object] = {
            "dense_raw": self.dense.retrieve(query, query_embedding=raw_dense),
            "dense": self.dense.retrieve(query, query_embedding=rw_dense),
            "sparse": self.sparse.retrieve(query, query_sparse=rw_sparse),
        }
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

        # dense 族按余弦分 max 合并，避免 RRF 截断挤出金标
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
        fused = fused[: self.fusion_size]

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
