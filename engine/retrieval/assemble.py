"""从 Settings 装配混合检索引擎，避免 API / 评测脚本各自硬编码默认值。"""

from __future__ import annotations

import asyncpg

from core.config import Settings
from engine.embedding.cache import CachedQueryEncoder
from engine.embedding.provider import create_embedding_provider
from engine.retrieval.bm25_retriever import BM25Retriever
from engine.retrieval.hybrid_retriever import HybridRetriever
from engine.retrieval.reranker import Reranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.rule_retriever import RuleRetriever
from engine.retrieval.tag_retriever import TagRetriever
from engine.retrieval.vector_retriever import VectorRetriever


def assemble_hybrid_retriever(
    *,
    settings: Settings,
    pool: asyncpg.Pool,
    rewriter,
    risk_predictor: RiskPredictor,
    reranker: Reranker,
    query_encoder: CachedQueryEncoder | None = None,
    redis=None,
    rerank_candidates: int | None = None,
) -> HybridRetriever:
    """按 Settings 注入召回量 / RRF 权重 / 标签上限 / 精排候选数。"""
    if query_encoder is None:
        embedder = create_embedding_provider(settings)
        # redis 由调用方保证已初始化；评测脚本通常先 get_redis()
        query_encoder = CachedQueryEncoder(
            embedder, redis, ttl=settings.EMBEDDING_CACHE_TTL,
        )

    return HybridRetriever(
        bm25=BM25Retriever(pool, recall_size=settings.RECALL_BM25),
        vector=VectorRetriever(pool, recall_size=settings.RECALL_VECTOR),
        tag=TagRetriever(pool, recall_size=settings.RECALL_TAG),
        rule=RuleRetriever(pool, recall_size=settings.RECALL_RULE),
        rewriter=rewriter,
        risk_predictor=risk_predictor,
        query_encoder=query_encoder,
        reranker=reranker,
        fusion_size=settings.RETRIEVAL_FUSION_SIZE,
        rerank_candidates=(
            settings.RETRIEVAL_RERANK_CANDIDATES
            if rerank_candidates is None else rerank_candidates
        ),
        channel_weights=settings.rrf_channel_weights(),
        rrf_k=settings.RRF_K,
        multi_channel_bonus=settings.RRF_MULTI_CHANNEL_BONUS,
        cn_tag_predict_max=settings.CN_TAG_PREDICT_MAX,
        cn_tag_final_max=settings.CN_TAG_FINAL_MAX,
        cn_tag_bm25_append=settings.CN_TAG_BM25_APPEND,
        risk_id_cap=settings.RISK_ID_CAP,
        tag_backfill_top_cases=settings.TAG_BACKFILL_TOP_CASES,
    )
