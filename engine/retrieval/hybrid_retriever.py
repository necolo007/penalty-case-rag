"""四路混合检索引擎（任务3核心）。

管线（对齐设计文档 §2.6.5 / §4.3，顺序不可变更）：
  原始 query → LLM 改写（强制） → encode_queries(+instruct)
             → BM25 / 向量 / 标签 / 规则 四路并行召回
             → 候选合并去重 + RRF 融合 → Reranker 精排 → Top-K + 相似理由
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from engine.classification.competition_label_map import (
    cn_tags_to_competition_ids,
    predict_cn_tags_by_keywords,
    resolve_final_cn_tags,
)
from engine.embedding.cache import CachedQueryEncoder
from engine.retrieval.base import SearchQuery, SearchResult
from engine.retrieval.bm25_retriever import BM25Retriever
from engine.retrieval.match_reason import build_match_reason
from engine.retrieval.merger import DEFAULT_CHANNEL_WEIGHTS, reciprocal_rank_fusion
from engine.retrieval.query_rewriter import QueryRewriter
from engine.retrieval.reranker import Reranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.rule_retriever import RuleRetriever
from engine.retrieval.tag_retriever import TagRetriever
from engine.retrieval.vector_retriever import VectorRetriever

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResponse:
    query: str
    rewritten_query: str
    predicted_risk_ids: list[str]
    results: list[SearchResult]
    took_ms: int
    channel_stats: dict[str, int] = field(default_factory=dict)
    predicted_cn_tags: list[str] = field(default_factory=list)


class HybridRetriever:
    def __init__(
        self,
        *,
        bm25: BM25Retriever,
        vector: VectorRetriever,
        tag: TagRetriever,
        rule: RuleRetriever,
        rewriter: QueryRewriter,
        risk_predictor: RiskPredictor,
        query_encoder: CachedQueryEncoder,
        reranker: Reranker,
        fusion_size: int = 100,
        rerank_candidates: int = 60,
        channel_weights: dict[str, float] | None = None,
        rrf_k: int = 60,
        multi_channel_bonus: float = 0.08,
        cn_tag_predict_max: int = 3,
        cn_tag_final_max: int = 5,
        cn_tag_bm25_append: int = 2,
        risk_id_cap: int = 3,
        tag_backfill_top_cases: int = 5,
    ):
        self.bm25 = bm25
        self.vector = vector
        self.tag = tag
        self.rule = rule
        self.rewriter = rewriter
        self.risk_predictor = risk_predictor
        self.query_encoder = query_encoder
        self.reranker = reranker
        self.fusion_size = fusion_size
        self.rerank_candidates = rerank_candidates
        self.channel_weights = channel_weights or dict(DEFAULT_CHANNEL_WEIGHTS)
        self.rrf_k = rrf_k
        self.multi_channel_bonus = multi_channel_bonus
        self.cn_tag_predict_max = cn_tag_predict_max
        self.cn_tag_final_max = cn_tag_final_max
        self.cn_tag_bm25_append = cn_tag_bm25_append
        self.risk_id_cap = risk_id_cap
        self.tag_backfill_top_cases = tag_backfill_top_cases

    async def retrieve(self, query: SearchQuery) -> RetrievalResponse:
        started = time.perf_counter()

        # 1. 查询理解：改写 + 风险类型初判（可并行）
        rewritten_query, predicted_risk_ids = await asyncio.gather(
            self.rewriter.rewrite(query.query_text),
            self.risk_predictor.predict(query.query_text),
        )
        # 中文标签：控制数量，避免标签/BM25 通道被噪声淹没
        predicted_cn_tags = predict_cn_tags_by_keywords(
            query.query_text, max_tags=self.cn_tag_predict_max,
        )
        if predicted_cn_tags:
            for cid in cn_tags_to_competition_ids(predicted_cn_tags):
                if cid not in predicted_risk_ids:
                    predicted_risk_ids.append(cid)
        predicted_risk_ids = list(dict.fromkeys(predicted_risk_ids))[: self.risk_id_cap]

        # BM25：改写文本 + 少量中文标签（口语词→标签词桥接）
        bm25_text = rewritten_query
        if predicted_cn_tags and self.cn_tag_bm25_append > 0:
            bm25_text = f"{rewritten_query} {' '.join(predicted_cn_tags[: self.cn_tag_bm25_append])}"

        # 2. 改写文本向量化（instruct 非对称编码 + Redis 缓存）
        query_embedding = await self.query_encoder.encode_query(rewritten_query)

        # 3. 四路并行召回
        channel_tasks = {
            "bm25": self.bm25.retrieve(query, search_text=bm25_text),
            "vector": self.vector.retrieve(query, query_embedding=query_embedding),
            "tag": self.tag.retrieve(
                query,
                predicted_risk_ids=predicted_risk_ids,
                predicted_cn_tags=predicted_cn_tags,
            ),
            "rule": self.rule.retrieve(query),
        }
        channel_outputs = await asyncio.gather(*channel_tasks.values(), return_exceptions=True)

        channel_results: dict[str, list[SearchResult]] = {}
        for channel, output in zip(channel_tasks.keys(), channel_outputs):
            if isinstance(output, BaseException):
                logger.warning("Channel %s failed: %s", channel, output)
                channel_results[channel] = []
            else:
                channel_results[channel] = output

        # 4. RRF 融合
        fused = reciprocal_rank_fusion(
            channel_results,
            k=self.rrf_k,
            top_k=self.fusion_size,
            weights=self.channel_weights,
            multi_channel_bonus=self.multi_channel_bonus,
        )

        # 5. 精排：用原始口语 query（比法言法语改写更贴近营销话术）
        if query.use_reranker:
            candidates = fused[: self.rerank_candidates]
            top = await self.reranker.rerank(query.query_text, candidates, top_k=query.top_k)
        else:
            top = fused[: query.top_k]

        # 6. 生成匹配理由
        for r in top:
            r.match_reason = build_match_reason(query.query_text, rewritten_query, r)

        # 7. 用 Top 案例标签回填最终中文分类信号（仍保留 R00x 作内部召回）
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
        return RetrievalResponse(
            query=query.query_text,
            rewritten_query=rewritten_query,
            predicted_risk_ids=predicted_risk_ids,
            predicted_cn_tags=predicted_cn_tags,
            results=top,
            took_ms=took_ms,
            channel_stats={ch: len(rs) for ch, rs in channel_results.items()},
        )
