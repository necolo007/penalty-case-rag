"""从 Settings 装配检索引擎：bge_m3（默认）或 legacy_four_way。"""

from __future__ import annotations

import logging
from typing import Union

import asyncpg

from core.config import Settings
from engine.embedding.cache import CachedQueryEncoder
from engine.embedding.provider import create_embedding_provider
from engine.retrieval.bm25_retriever import BM25Retriever
from engine.retrieval.hybrid_retriever import HybridRetriever
from engine.retrieval.m3_retriever import M3HybridRetriever
from engine.retrieval.reranker import Reranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.rule_retriever import RuleRetriever
from engine.retrieval.sparse_index import SparseLexicalIndex
from engine.retrieval.sparse_retriever import SparseRetriever
from engine.retrieval.tag_retriever import TagRetriever
from engine.retrieval.vector_retriever import VectorRetriever

logger = logging.getLogger(__name__)

AnyRetriever = Union[M3HybridRetriever, HybridRetriever]

# 进程内单例稀疏倒排（API / 评测共享）
_sparse_index: SparseLexicalIndex | None = None


def get_sparse_index() -> SparseLexicalIndex:
    global _sparse_index
    if _sparse_index is None:
        _sparse_index = SparseLexicalIndex()
    return _sparse_index


async def ensure_sparse_index_loaded(pool: asyncpg.Pool) -> SparseLexicalIndex:
    index = get_sparse_index()
    if not index.loaded:
        await index.load_from_db(pool)
    return index


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
    sparse_index: SparseLexicalIndex | None = None,
) -> AnyRetriever:
    """按 RETRIEVAL_BACKEND 装配；默认 bge_m3。"""
    if query_encoder is None:
        embedder = create_embedding_provider(settings)
        query_encoder = CachedQueryEncoder(
            embedder, redis, ttl=settings.EMBEDDING_CACHE_TTL,
        )

    backend = (settings.RETRIEVAL_BACKEND or "bge_m3").strip().lower()
    rerank_n = (
        settings.RETRIEVAL_RERANK_CANDIDATES
        if rerank_candidates is None else rerank_candidates
    )

    if backend in ("legacy_four_way", "legacy", "four_way"):
        logger.info("Assembling legacy_four_way retriever")
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
            rerank_candidates=rerank_n,
            channel_weights=settings.rrf_channel_weights(),
            rrf_k=settings.RRF_K,
            multi_channel_bonus=settings.RRF_MULTI_CHANNEL_BONUS,
            cn_tag_predict_max=settings.CN_TAG_PREDICT_MAX,
            cn_tag_final_max=settings.CN_TAG_FINAL_MAX,
            cn_tag_bm25_append=settings.CN_TAG_BM25_APPEND,
            risk_id_cap=settings.RISK_ID_CAP,
            tag_backfill_top_cases=settings.TAG_BACKFILL_TOP_CASES,
        )

    logger.info("Assembling bge_m3 retriever")
    index = sparse_index or get_sparse_index()
    return M3HybridRetriever(
        dense=VectorRetriever(
            pool, recall_size=settings.RECALL_DENSE, channel="dense",
        ),
        sparse=SparseRetriever(pool, index, recall_size=settings.RECALL_SPARSE),
        rewriter=rewriter,
        risk_predictor=risk_predictor,
        query_encoder=query_encoder,
        reranker=reranker,
        fusion_size=settings.RETRIEVAL_FUSION_SIZE,
        rerank_candidates=rerank_n,
        channel_weights=settings.m3_rrf_channel_weights(),
        rrf_k=settings.RRF_K,
        multi_channel_bonus=settings.RRF_MULTI_CHANNEL_BONUS,
        cn_tag_predict_max=settings.CN_TAG_PREDICT_MAX,
        cn_tag_final_max=settings.CN_TAG_FINAL_MAX,
        risk_id_cap=settings.RISK_ID_CAP,
        tag_backfill_top_cases=settings.TAG_BACKFILL_TOP_CASES,
        enable_hyde=bool(settings.RETRIEVAL_HYDE_ENABLED),
        hyde_rerank=bool(settings.RETRIEVAL_HYDE_RERANK),
    )
