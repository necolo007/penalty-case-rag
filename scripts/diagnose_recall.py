"""诊断脚本：分通道统计"第一阶段召回"是否覆盖金标案例（不含精排，跑得快）。

用于定位 train/test 检索瓶颈到底出在"召回不够广"还是"精排排序不够好"，
以及四路召回（BM25/向量/标签/规则）中具体是哪一路对目标 split 覆盖不足。

用法：
  python scripts/diagnose_recall.py --split train --limit 100
  python scripts/diagnose_recall.py --split test --limit 100 --llm-rewrite
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
for p in (_ROOT, _SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from core.config import get_settings
from core.db import close_pool, create_pool
from core.redis_client import close_redis, get_redis
from engine.classification.competition_label_map import (
    cn_tags_to_competition_ids,
    predict_cn_tags_by_keywords,
)
from engine.embedding.cache import CachedQueryEncoder
from engine.embedding.provider import create_embedding_provider
from engine.llm.client import create_llm_client
from engine.retrieval.assemble import assemble_hybrid_retriever
from engine.retrieval.base import SearchQuery
from engine.retrieval.merger import reciprocal_rank_fusion
from engine.retrieval.query_rewriter import QueryRewriter
from engine.retrieval.reranker import NoopReranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.synonym_expander import SynonymExpander
from eval_retrieval_local import SynonymOnlyRewriter, _load_jsonl, _normalize_questions


def _gold_relevant(item: dict) -> set[str]:
    payload = item.get("gold_answer") if isinstance(item.get("gold_answer"), dict) else item
    return {c["case_id"] for c in payload.get("relevant_cases", [])}


async def main() -> None:
    parser = argparse.ArgumentParser(description="第一阶段召回诊断（分通道）")
    parser.add_argument("--split", choices=["train", "test"], default="test")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--llm-rewrite", action="store_true")
    parser.add_argument("--fusion-top", type=int, default=50, help="RRF 融合后检查的窗口")
    args = parser.parse_args()

    if args.split == "train":
        q_path = _ROOT / "data/eval/retrieval_train_queries.jsonl"
        g_path = q_path
    else:
        q_path = _ROOT / "data/eval/test_questions.jsonl"
        g_path = _ROOT / "data/eval/quarantine/test_gold_labels.jsonl"

    questions = _normalize_questions(_load_jsonl(q_path))[: args.limit]
    gold_raw = _load_jsonl(g_path)
    gold_map = {}
    for item in gold_raw:
        qid = item.get("question_id") or item.get("query_id")
        gold_map[qid] = _gold_relevant(item)

    settings = get_settings()
    pool = await create_pool()
    redis = await get_redis()
    embedder = create_embedding_provider(settings)
    expander = SynonymExpander(pool)
    llm_client = create_llm_client(settings) if args.llm_rewrite else None
    rewriter = QueryRewriter(llm_client, expander) if llm_client else SynonymOnlyRewriter(expander)
    risk_predictor = RiskPredictor(pool, llm_client=llm_client)

    retriever = assemble_hybrid_retriever(
        settings=settings,
        pool=pool,
        rewriter=rewriter,
        risk_predictor=risk_predictor,
        reranker=NoopReranker(),
        query_encoder=CachedQueryEncoder(embedder, redis, ttl=settings.EMBEDDING_CACHE_TTL),
    )

    n = 0
    channel_hit = {"bm25": 0, "vector": 0, "tag": 0, "rule": 0}
    channel_total_recall_pool = {"bm25": 0, "vector": 0, "tag": 0, "rule": 0}
    fused_hit = 0
    no_gold = 0
    empty_tag_channel = 0
    empty_rule_channel = 0

    for q in questions:
        qid = q["question_id"]
        relevant = gold_map.get(qid, set())
        if not relevant:
            no_gold += 1
            continue
        n += 1

        rewritten_query, predicted_risk_ids = await asyncio.gather(
            retriever.rewriter.rewrite(q["query_text"]),
            retriever.risk_predictor.predict(q["query_text"]),
        )
        predicted_cn_tags = predict_cn_tags_by_keywords(
            q["query_text"], max_tags=retriever.cn_tag_predict_max,
        )
        if predicted_cn_tags:
            for cid in cn_tags_to_competition_ids(predicted_cn_tags):
                if cid not in predicted_risk_ids:
                    predicted_risk_ids.append(cid)
        predicted_risk_ids = list(dict.fromkeys(predicted_risk_ids))[: retriever.risk_id_cap]

        bm25_text = rewritten_query
        if predicted_cn_tags:
            bm25_text = f"{rewritten_query} {' '.join(predicted_cn_tags[: retriever.cn_tag_bm25_append])}"

        query_embedding = await retriever.query_encoder.encode_query(rewritten_query)
        search_q = SearchQuery(query_text=q["query_text"], question_id=qid, top_k=10)

        channel_results = {
            "bm25": await retriever.bm25.retrieve(search_q, search_text=bm25_text),
            "vector": await retriever.vector.retrieve(search_q, query_embedding=query_embedding),
            "tag": await retriever.tag.retrieve(
                search_q, predicted_risk_ids=predicted_risk_ids, predicted_cn_tags=predicted_cn_tags,
            ),
            "rule": await retriever.rule.retrieve(search_q),
        }

        if not predicted_cn_tags and not predicted_risk_ids:
            empty_tag_channel += 1
        if not channel_results["rule"]:
            empty_rule_channel += 1

        for ch, results in channel_results.items():
            ids = {r.case_id for r in results}
            if ids:
                channel_total_recall_pool[ch] += 1
            if ids & relevant:
                channel_hit[ch] += 1

        fused = reciprocal_rank_fusion(
            channel_results, k=retriever.rrf_k, top_k=args.fusion_top,
            weights=retriever.channel_weights, multi_channel_bonus=retriever.multi_channel_bonus,
        )
        fused_ids = {r.case_id for r in fused}
        if fused_ids & relevant:
            fused_hit += 1

        if n % 20 == 0:
            print(f"  progress {n}")

    print(f"\n=== split={args.split} n={n}（跳过无金标 {no_gold} 条）llm_rewrite={args.llm_rewrite} ===")
    print(f"RRF Top-{args.fusion_top} 命中金标比例: {fused_hit / n:.2%}")
    print("\n各通道自身候选中包含金标案例的比例（该通道单独能否捞到正确答案）：")
    for ch in ("bm25", "vector", "tag", "rule"):
        print(f"  {ch:8s}: hit={channel_hit[ch] / n:.2%}  非空候选比例={channel_total_recall_pool[ch] / n:.2%}")
    print(f"\n标签通道无预测标签（tag/risk_id 均为空）比例: {empty_tag_channel / n:.2%}")
    print(f"规则通道空召回比例: {empty_rule_channel / n:.2%}")

    await close_pool()
    await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
