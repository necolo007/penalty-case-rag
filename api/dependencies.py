"""FastAPI 依赖注入：单例引擎组件在应用启动时装配。"""

import logging

from core.config import get_settings
from core.db import create_pool
from core.redis_client import get_redis
from engine.embedding.cache import CachedQueryEncoder
from engine.embedding.provider import create_embedding_provider
from engine.llm.client import create_llm_client
from engine.retrieval.bm25_retriever import BM25Retriever
from engine.retrieval.hybrid_retriever import HybridRetriever
from engine.retrieval.query_rewriter import QueryRewriter
from engine.retrieval.reranker import NoopReranker, Reranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.rule_retriever import RuleRetriever
from engine.retrieval.synonym_expander import SynonymExpander
from engine.retrieval.tag_retriever import TagRetriever
from engine.retrieval.vector_retriever import VectorRetriever
from engine.review.generator import ReviewGenerator
from engine.review.material_reviewer import MaterialReviewer
from engine.review.risk_locator import RiskSentenceLocator

logger = logging.getLogger(__name__)


class AppState:
    """应用级单例容器（在 lifespan 中初始化）"""

    pool = None
    retriever: HybridRetriever | None = None
    generator: ReviewGenerator | None = None
    material_reviewer: MaterialReviewer | None = None
    risk_predictor: RiskPredictor | None = None


state = AppState()


async def init_app_state() -> None:
    settings = get_settings()
    pool = await create_pool()
    redis = await get_redis()

    llm = create_llm_client(settings) if settings.LLM_API_KEY else None
    embedder = create_embedding_provider(settings)
    query_encoder = CachedQueryEncoder(embedder, redis, ttl=settings.EMBEDDING_CACHE_TTL)

    synonym_expander = SynonymExpander(pool)
    rewriter = QueryRewriter(llm, synonym_expander) if llm else _NoLLMRewriter(synonym_expander)
    risk_predictor = RiskPredictor(pool, llm_client=llm)

    reranker = (
        Reranker(settings.RERANKER_MODEL, settings.RERANKER_DEVICE)
        if settings.RERANKER_ENABLED else NoopReranker()
    )

    retriever = HybridRetriever(
        bm25=BM25Retriever(pool),
        vector=VectorRetriever(pool),
        tag=TagRetriever(pool),
        rule=RuleRetriever(pool),
        rewriter=rewriter,
        risk_predictor=risk_predictor,
        query_encoder=query_encoder,
        reranker=reranker,
    )

    generator = ReviewGenerator(llm) if llm else None
    locator = RiskSentenceLocator(pool, llm_client=llm, llm_enabled=llm is not None)

    state.pool = pool
    state.retriever = retriever
    state.generator = generator
    state.risk_predictor = risk_predictor
    if generator is not None:
        state.material_reviewer = MaterialReviewer(
            pool=pool, locator=locator, retriever=retriever, generator=generator,
        )
    logger.info("App state initialized (llm=%s, embedding=%s)",
                bool(llm), embedder.model_name)


class _NoLLMRewriter:
    """无 LLM Key 场景（本地开发）：仅同义词词典改写"""

    def __init__(self, synonym_expander: SynonymExpander):
        self.synonym_expander = synonym_expander

    async def rewrite(self, query_text: str) -> str:
        expanded = await self.synonym_expander.expand(query_text)
        return expanded or query_text


def get_pool():
    return state.pool


def get_retriever() -> HybridRetriever:
    return state.retriever


def get_generator() -> ReviewGenerator | None:
    return state.generator


def get_material_reviewer() -> MaterialReviewer | None:
    return state.material_reviewer


def get_risk_predictor() -> RiskPredictor:
    return state.risk_predictor
