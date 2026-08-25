"""FastAPI 依赖注入：单例引擎组件在应用启动时装配。"""

import logging

from core.config import get_settings
from core.db import create_pool
from core.redis_client import get_redis
from engine.classification.fewshot import FewShotBank, get_default_bank
from engine.embedding.cache import CachedQueryEncoder
from engine.embedding.provider import create_embedding_provider
from engine.llm.client import create_llm_client
from engine.retrieval.assemble import (
    AnyRetriever,
    assemble_hybrid_retriever,
    ensure_sparse_index_loaded,
)
from engine.retrieval.query_rewriter import QueryRewriter
from engine.retrieval.reranker import NoopReranker, Reranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.synonym_expander import SynonymExpander
from engine.review.generator import ReviewGenerator
from engine.review.material_reviewer import MaterialReviewer
from engine.review.risk_locator import RiskSentenceLocator

logger = logging.getLogger(__name__)


class AppState:
    """应用级单例容器（在 lifespan 中初始化）"""

    pool = None
    retriever: AnyRetriever | None = None
    generator: ReviewGenerator | None = None
    material_reviewer: MaterialReviewer | None = None
    risk_predictor: RiskPredictor | None = None
    fewshot_bank: FewShotBank | None = None


state = AppState()


async def init_app_state() -> None:
    settings = get_settings()
    pool = await create_pool()
    redis = await get_redis()

    llm = create_llm_client(settings) if settings.LLM_API_KEY else None
    embedder = create_embedding_provider(settings)
    query_encoder = CachedQueryEncoder(embedder, redis, ttl=settings.EMBEDDING_CACHE_TTL)

    # 任务2 示例库：启动时预热
    fewshot_bank = get_default_bank()

    synonym_expander = SynonymExpander(pool)
    rewriter = (
        QueryRewriter(llm, synonym_expander, use_llm_rewrite=True)
        if llm
        else _NoLLMRewriter(synonym_expander)
    )
    risk_predictor = RiskPredictor(pool, llm_client=llm)

    reranker = (
        Reranker(
            settings.RERANKER_MODEL,
            settings.RERANKER_DEVICE,
            batch_size=settings.RERANKER_BATCH_SIZE,
            doc_max_chars=settings.RERANKER_DOC_MAX_CHARS,
        )
        if settings.RERANKER_ENABLED else NoopReranker()
    )

    sparse_index = None
    backend = (settings.RETRIEVAL_BACKEND or "bge_m3").strip().lower()
    if backend not in ("legacy_four_way", "legacy", "four_way"):
        sparse_index = await ensure_sparse_index_loaded(pool)

    retriever = assemble_hybrid_retriever(
        settings=settings,
        pool=pool,
        rewriter=rewriter,
        risk_predictor=risk_predictor,
        reranker=reranker,
        query_encoder=query_encoder,
        sparse_index=sparse_index,
        llm_client=llm,
    )

    generator = ReviewGenerator(llm) if llm else None
    locator = RiskSentenceLocator(pool, llm_client=llm, llm_enabled=llm is not None)

    state.pool = pool
    state.retriever = retriever
    state.generator = generator
    state.risk_predictor = risk_predictor
    state.fewshot_bank = fewshot_bank
    if generator is not None:
        state.material_reviewer = MaterialReviewer(
            pool=pool, locator=locator, retriever=retriever, generator=generator,
        )
    logger.info(
        "App state initialized (backend=%s, llm=%s, embedding=%s, rerank_cand=%s, fusion=%s, "
        "fewshot=%s)",
        settings.RETRIEVAL_BACKEND, bool(llm), embedder.model_name,
        settings.RETRIEVAL_RERANK_CANDIDATES, settings.RETRIEVAL_FUSION_SIZE,
        len(fewshot_bank) if fewshot_bank is not None else "off",
    )


class _NoLLMRewriter:
    """无 LLM 时仅同义词改写。"""

    def __init__(self, synonym_expander: SynonymExpander):
        self.synonym_expander = synonym_expander

    async def rewrite(self, query_text: str) -> str:
        expanded = await self.synonym_expander.expand(query_text)
        return expanded or query_text


def get_pool():
    return state.pool


def get_retriever() -> AnyRetriever:
    return state.retriever


def get_generator() -> ReviewGenerator | None:
    return state.generator


def get_material_reviewer() -> MaterialReviewer | None:
    return state.material_reviewer


def get_risk_predictor() -> RiskPredictor:
    return state.risk_predictor


def get_fewshot_bank() -> FewShotBank | None:
    return state.fewshot_bank
