"""一次性抓取四路召回原始排名列表并落盘缓存，供 tune_rrf_grid.py 离线网格搜索。

避免每次调整 RRF_K / channel_weights 都重新触发 LLM 改写 + 风险判定 + 向量
编码等昂贵调用——这些调用与 RRF 融合参数无关，只需算一次。
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
from engine.retrieval.query_rewriter import QueryRewriter
from engine.retrieval.reranker import NoopReranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.synonym_expander import SynonymExpander
from eval_retrieval_local import _load_jsonl, _normalize_questions


def _gold_relevant(item: dict) -> set[str]:
    payload = item.get("gold_answer") if isinstance(item.get("gold_answer"), dict) else item
    return {c["case_id"] for c in payload.get("relevant_cases", [])}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["train", "test"], default="test")
    parser.add_argument("--limit", type=int, default=100)
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
    valid_qids = {q["question_id"] for q in questions}
    gold_map = {qid: sorted(rel) for qid, rel in gold_map.items() if qid in valid_qids and rel}

    settings = get_settings()
    pool = await create_pool()
    redis = await get_redis()
    embedder = create_embedding_provider(settings)
    expander = SynonymExpander(pool)
    llm_client = create_llm_client(settings)
    rewriter = QueryRewriter(llm_client, expander)
    risk_predictor = RiskPredictor(pool, llm_client=llm_client)
    query_encoder = CachedQueryEncoder(embedder, redis, ttl=settings.EMBEDDING_CACHE_TTL)

    retriever = assemble_hybrid_retriever(
        settings=settings, pool=pool, rewriter=rewriter, risk_predictor=risk_predictor,
        reranker=NoopReranker(), query_encoder=query_encoder,
    )

    dump: dict[str, dict] = {}
    n = 0
    for q in questions:
        qid = q["question_id"]
        if qid not in gold_map:
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
        dump[qid] = {
            "relevant": gold_map[qid],
            "channels": {ch: [r.case_id for r in results] for ch, results in channel_results.items()},
        }

        if n % 20 == 0:
            print(f"  progress {n}")

    out_path = _ROOT / f"data/eval/_channel_dump_{args.split}_{args.limit}.json"
    out_path.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Dumped {len(dump)} queries -> {out_path}")

    await close_pool()
    await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
