"""诊断脚本：分通道统计第一阶段召回是否覆盖金标（不含精排）。

默认后端 bge_m3（dense/sparse）；--backend legacy_four_way 走四路。

用法：
  python scripts/diagnose_recall.py --split train --limit 100
  python scripts/diagnose_recall.py --split test --limit 100 --backend bge_m3
  python scripts/diagnose_recall.py --split test --limit 100 --backend legacy_four_way
"""

from __future__ import annotations

import argparse
import asyncio
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
from engine.retrieval.assemble import assemble_hybrid_retriever, ensure_sparse_index_loaded
from engine.retrieval.base import SearchQuery
from engine.retrieval.hybrid_retriever import HybridRetriever
from engine.retrieval.m3_retriever import M3HybridRetriever
from engine.retrieval.merger import reciprocal_rank_fusion
from engine.retrieval.query_rewriter import QueryRewriter
from engine.retrieval.reranker import NoopReranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.synonym_expander import SynonymExpander
from eval_retrieval_local import SynonymOnlyRewriter, _load_jsonl, _normalize_questions


def _gold_relevant(item: dict) -> set[str]:
    payload = item.get("gold_answer") if isinstance(item.get("gold_answer"), dict) else item
    return {c["case_id"] for c in payload.get("relevant_cases", [])}


async def _channels_legacy(retriever: HybridRetriever, q: dict) -> dict:
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
    search_q = SearchQuery(query_text=q["query_text"], question_id=q["question_id"], top_k=10)
    return {
        "bm25": await retriever.bm25.retrieve(search_q, search_text=bm25_text),
        "vector": await retriever.vector.retrieve(search_q, query_embedding=query_embedding),
        "tag": await retriever.tag.retrieve(
            search_q, predicted_risk_ids=predicted_risk_ids, predicted_cn_tags=predicted_cn_tags,
        ),
        "rule": await retriever.rule.retrieve(search_q),
    }


async def _channels_m3(retriever: M3HybridRetriever, q: dict) -> dict:
    rewritten_query = await retriever.rewriter.rewrite(q["query_text"])
    raw_dense, _ = await retriever.query_encoder.encode_query_dual(q["query_text"])
    rw_dense, rw_sparse = await retriever.query_encoder.encode_query_dual(rewritten_query)
    search_q = SearchQuery(query_text=q["query_text"], question_id=q["question_id"], top_k=10)
    out = {
        "dense_raw": await retriever.dense.retrieve(search_q, query_embedding=raw_dense),
        "dense": await retriever.dense.retrieve(search_q, query_embedding=rw_dense),
        "sparse": await retriever.sparse.retrieve(search_q, query_sparse=rw_sparse),
    }
    if getattr(retriever, "enable_hyde", False) and hasattr(retriever.rewriter, "hyde"):
        hyde_text = (await retriever.rewriter.hyde(q["query_text"]) or "").strip()
        if hyde_text:
            hyde_dense, _ = await retriever.query_encoder.encode_query_dual(hyde_text)
            out["dense_hyde"] = await retriever.dense.retrieve(
                search_q, query_embedding=hyde_dense,
            )
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description="第一阶段召回诊断（分通道）")
    parser.add_argument("--split", choices=["train", "test"], default="test")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--llm-rewrite", action="store_true")
    parser.add_argument("--fusion-top", type=int, default=50, help="RRF 融合后检查的窗口")
    parser.add_argument("--backend", default=None, help="bge_m3 | legacy_four_way")
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
    if args.backend:
        settings.RETRIEVAL_BACKEND = args.backend
    backend = (settings.RETRIEVAL_BACKEND or "bge_m3").strip().lower()
    is_legacy = backend in ("legacy_four_way", "legacy", "four_way")

    pool = await create_pool()
    redis = await get_redis()
    embedder = create_embedding_provider(settings)
    expander = SynonymExpander(pool)
    need_llm = bool(args.llm_rewrite or settings.RETRIEVAL_HYDE_ENABLED)
    llm_client = create_llm_client(settings) if need_llm else None
    rewriter = (
        QueryRewriter(llm_client, expander, use_llm_rewrite=bool(args.llm_rewrite))
        if llm_client
        else SynonymOnlyRewriter(expander)
    )
    risk_predictor = RiskPredictor(pool, llm_client=llm_client)

    sparse_index = None if is_legacy else await ensure_sparse_index_loaded(pool)
    retriever = assemble_hybrid_retriever(
        settings=settings,
        pool=pool,
        rewriter=rewriter,
        risk_predictor=risk_predictor,
        reranker=NoopReranker(),
        query_encoder=CachedQueryEncoder(embedder, redis, ttl=settings.EMBEDDING_CACHE_TTL),
        sparse_index=sparse_index,
    )

    if is_legacy:
        channels = ("bm25", "vector", "tag", "rule")
    else:
        channels = ("dense_raw", "dense", "sparse")
        if getattr(settings, "RETRIEVAL_HYDE_ENABLED", False):
            channels = ("dense_raw", "dense", "dense_hyde", "sparse")
    n = 0
    channel_hit = {ch: 0 for ch in channels}
    channel_total_recall_pool = {ch: 0 for ch in channels}
    fused_hit = 0
    no_gold = 0

    for q in questions:
        qid = q["question_id"]
        relevant = gold_map.get(qid, set())
        if not relevant:
            no_gold += 1
            continue
        n += 1

        if is_legacy:
            channel_results = await _channels_legacy(retriever, q)  # type: ignore[arg-type]
        else:
            channel_results = await _channels_m3(retriever, q)  # type: ignore[arg-type]

        for ch, results in channel_results.items():
            ids = {r.case_id for r in results}
            if ids:
                channel_total_recall_pool[ch] += 1
            if ids & relevant:
                channel_hit[ch] += 1

        fused = reciprocal_rank_fusion(
            {
                k: v for k, v in channel_results.items()
                if k in ("dense_raw", "dense", "dense_hyde")
            }
            if not is_legacy else channel_results,
            k=retriever.rrf_k, top_k=args.fusion_top,
            weights=retriever.channel_weights, multi_channel_bonus=retriever.multi_channel_bonus,
        )
        # 与线上一致：sparse 仅补位
        if not is_legacy:
            seen = {r.case_id for r in fused}
            for r in channel_results.get("sparse", []):
                if r.case_id in seen:
                    continue
                if len(fused) >= args.fusion_top:
                    break
                fused.append(r)
                seen.add(r.case_id)
        if {r.case_id for r in fused} & relevant:
            fused_hit += 1

        if n % 20 == 0:
            print(f"  progress {n}")

    print(
        f"\n=== split={args.split} backend={backend} n={n}"
        f"（跳过无金标 {no_gold} 条）llm_rewrite={args.llm_rewrite} ==="
    )
    print(f"RRF Top-{args.fusion_top} 命中金标比例: {fused_hit / n:.2%}" if n else "n=0")
    print("\n各通道自身候选中包含金标案例的比例：")
    for ch in channels:
        if n:
            print(
                f"  {ch:8s}: hit={channel_hit[ch] / n:.2%}  "
                f"非空候选比例={channel_total_recall_pool[ch] / n:.2%}"
            )

    await close_pool()
    await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
