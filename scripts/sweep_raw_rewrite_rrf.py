"""扫参：dense_raw / dense 加权 RRF（两权重和为 1），基于一次通道缓存离线融合。

默认不做 CE（快速代理指标）；加 --with-ce 才对每组权重精排（很慢）。

用法：
  # 1) 缓存通道排序
  python scripts/sweep_raw_rewrite_rrf.py cache --limit 30 --llm-rewrite --hyde

  # 2) 扫 w_raw ∈ {0.0,0.1,...,1.0}，HyDE/sparse 权重沿用配置
  python scripts/sweep_raw_rewrite_rrf.py sweep --cache data/eval/rrf_channel_cache_test_n30.json

  # 3) 对最优权重跑完整评测（另开）
  python scripts/eval_retrieval_local.py --split test --limit 30 --rerank --llm-rewrite \\
    --fusion-mode weighted_rrf --rrf-w-raw 0.4 --submission-out data/eval/submission_test_rrf04.jsonl
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
from engine.embedding.cache import CachedQueryEncoder
from engine.embedding.provider import create_embedding_provider
from engine.llm.client import create_llm_client
from engine.retrieval.assemble import ensure_sparse_index_loaded
from engine.retrieval.base import SearchQuery, SearchResult
from engine.retrieval.merger import reciprocal_rank_fusion
from engine.retrieval.query_rewriter import QueryRewriter
from engine.retrieval.sparse_retriever import SparseRetriever
from engine.retrieval.synonym_expander import SynonymExpander
from engine.retrieval.vector_retriever import VectorRetriever
from eval_metrics import compute_retrieval_metrics


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _serialize_channel(rows: list[SearchResult]) -> list[dict]:
    return [
        {
            "case_id": r.case_id,
            "score": float(r.score),
            "party_name": r.party_name,
            "violation_behavior": (r.violation_behavior or "")[:500],
            "penalty_content": (r.penalty_content or "")[:200],
            "regulator": r.regulator or "",
            "risk_tags": list(r.risk_tags or []),
        }
        for r in rows
    ]


def _deserialize_channel(rows: list[dict], channel: str) -> list[SearchResult]:
    out: list[SearchResult] = []
    for r in rows:
        out.append(SearchResult(
            case_id=r["case_id"],
            party_name=r.get("party_name") or "",
            violation_behavior=r.get("violation_behavior") or "",
            penalty_content=r.get("penalty_content") or "",
            regulator=r.get("regulator") or "",
            risk_tags=list(r.get("risk_tags") or []),
            score=float(r.get("score") or 0.0),
            channels=[channel],
        ))
    return out


async def cmd_cache(args: argparse.Namespace) -> None:
    settings = get_settings()
    q_path = _ROOT / (args.questions or "data/eval/test_questions.jsonl")
    questions = _load_jsonl(q_path)[: args.limit or None]
    pool = await create_pool()
    redis = await get_redis()
    embedder = create_embedding_provider(settings)
    encoder = CachedQueryEncoder(embedder, redis, ttl=settings.EMBEDDING_CACHE_TTL)
    expander = SynonymExpander(pool)
    llm = create_llm_client(settings) if (args.llm_rewrite or settings.RETRIEVAL_HYDE_ENABLED) else None
    if llm is not None:
        rewriter = QueryRewriter(llm, expander, use_llm_rewrite=bool(args.llm_rewrite))
    else:
        class _SynOnly:
            def __init__(self, exp):
                self.expander = exp

            async def rewrite(self, q: str) -> str:
                return (await self.expander.expand(q)) or q

            async def hyde(self, q: str) -> str:
                return ""

        rewriter = _SynOnly(expander)
    sparse_index = await ensure_sparse_index_loaded(pool)
    dense = VectorRetriever(pool, recall_size=settings.RECALL_DENSE, channel="dense")
    sparse = SparseRetriever(pool, sparse_index, recall_size=settings.RECALL_SPARSE)

    cache_rows: list[dict] = []
    for i, q in enumerate(questions, 1):
        qtext = q.get("query_text") or ""
        qid = q.get("question_id") or ""
        sq = SearchQuery(query_text=qtext, question_id=qid, top_k=10, use_reranker=False)

        rewritten = await rewriter.rewrite(qtext) if hasattr(rewriter, "rewrite") else qtext
        hyde = ""
        if args.hyde or settings.RETRIEVAL_HYDE_ENABLED:
            if hasattr(rewriter, "hyde"):
                hyde = (await rewriter.hyde(qtext) or "").strip()

        rw_d, rw_s = await encoder.encode_query_dual(rewritten)
        channels: dict[str, list[SearchResult]] = {
            "dense": await dense.retrieve(sq, query_embedding=rw_d),
            "sparse": await sparse.retrieve(sq, query_sparse=rw_s),
        }
        if not args.no_dense_raw:
            raw_d, _ = await encoder.encode_query_dual(qtext)
            channels["dense_raw"] = await dense.retrieve(sq, query_embedding=raw_d)
        if hyde:
            hy_d, _ = await encoder.encode_query_dual(hyde)
            channels["dense_hyde"] = await dense.retrieve(sq, query_embedding=hy_d)

        cache_rows.append({
            "question_id": qid,
            "query_text": qtext,
            "rewritten_query": rewritten,
            "hyde": hyde[:300],
            "channels": {ch: _serialize_channel(rs) for ch, rs in channels.items()},
        })
        print(f"  cached {i}/{len(questions)} {qid} ch={list(channels)}")

    out = Path(args.out or f"data/eval/rrf_channel_cache_test_n{len(questions)}.json")
    if not out.is_absolute():
        out = _ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cache_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Cache → {out}")
    await close_pool()
    await close_redis()


def _submission_from_fused(
    qid: str, fused: list[SearchResult], top_k: int,
) -> dict:
    return {
        "question_id": qid,
        "risk_type": "",
        "retrieved_cases": [
            {"case_id": r.case_id, "rank": i + 1, "reason": "rrf"}
            for i, r in enumerate(fused[:top_k])
        ],
        "suggestion": "",
    }


def cmd_sweep(args: argparse.Namespace) -> None:
    settings = get_settings()
    cache_path = Path(args.cache)
    if not cache_path.is_absolute():
        cache_path = _ROOT / cache_path
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    g_path = _ROOT / (args.gold or "data/eval/quarantine/test_gold_labels.jsonl")
    if not g_path.exists():
        g_path = _ROOT / "data/eval/test_gold_labels.jsonl"
    gold = _load_jsonl(g_path)

    step = args.step
    weights = [round(i * step, 10) for i in range(int(1 / step) + 1)]
    if weights[-1] != 1.0:
        weights.append(1.0)

    base_w = settings.m3_rrf_channel_weights()
    if args.no_hyde_weight:
        base_w["dense_hyde"] = 0.0
    if args.no_sparse_weight:
        base_w["sparse"] = 0.0

    rows_out: list[dict] = []
    best = None
    for w_raw in weights:
        w_rw = round(1.0 - w_raw, 10)
        weights_map = dict(base_w)
        weights_map["dense_raw"] = w_raw
        weights_map["dense"] = w_rw

        submission = []
        for item in cache:
            channels = {
                ch: _deserialize_channel(rs, ch)
                for ch, rs in (item.get("channels") or {}).items()
            }
            # 无 raw 通道时跳过该权重贡献
            fused = reciprocal_rank_fusion(
                channels,
                k=settings.RRF_K,
                top_k=settings.RETRIEVAL_FUSION_SIZE,
                weights=weights_map,
                multi_channel_bonus=settings.RRF_MULTI_CHANNEL_BONUS,
            )
            submission.append(_submission_from_fused(
                item["question_id"], fused, args.top_k,
            ))

        metrics = compute_retrieval_metrics(submission, gold, k_values=[5, 10])
        row = {
            "w_raw": w_raw,
            "w_rewrite": w_rw,
            "w_hyde": weights_map.get("dense_hyde", 0),
            "w_sparse": weights_map.get("sparse", 0),
            "mrr": metrics.get("mrr"),
            "top1_hit": metrics.get("top1_hit"),
            "recall@5": metrics.get("recall@5"),
            "recall@10": metrics.get("recall@10"),
            "ndcg@10": metrics.get("ndcg@10"),
        }
        rows_out.append(row)
        score = (row["mrr"] or 0) + 0.5 * (row.get("recall@10") or 0)
        if best is None or score > best[0]:
            best = (score, row)
        print(
            f"w_raw={w_raw:.1f} w_rw={w_rw:.1f}  "
            f"MRR={row['mrr']:.4f} R@10={row['recall@10']:.4f} Top1={row['top1_hit']:.4f}"
        )

    out = Path(args.out or "data/eval/rrf_raw_rewrite_sweep.json")
    if not out.is_absolute():
        out = _ROOT / out
    payload = {
        "note": "无 CE 的 RRF 代理指标；采纳前请用 eval_retrieval_local --fusion-mode weighted_rrf 端到端复核",
        "best": best[1] if best else None,
        "rows": rows_out,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Best (proxy): {best[1] if best else None}")
    print(f"Sweep → {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="raw/rewrite RRF weight sweep")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cache = sub.add_parser("cache", help="缓存各通道召回排序")
    p_cache.add_argument("--limit", type=int, default=30)
    p_cache.add_argument("--questions", default=None)
    p_cache.add_argument("--llm-rewrite", action="store_true")
    p_cache.add_argument("--hyde", action="store_true")
    p_cache.add_argument("--no-dense-raw", action="store_true")
    p_cache.add_argument("--out", default=None)
    p_cache.set_defaults(func=lambda a: asyncio.run(cmd_cache(a)))

    p_sweep = sub.add_parser("sweep", help="离线扫 w_raw + (1-w_raw)")
    p_sweep.add_argument("--cache", required=True)
    p_sweep.add_argument("--gold", default=None)
    p_sweep.add_argument("--step", type=float, default=0.1)
    p_sweep.add_argument("--top-k", type=int, default=10)
    p_sweep.add_argument("--no-hyde-weight", action="store_true",
                         help="扫参时将 dense_hyde 权重置 0")
    p_sweep.add_argument("--no-sparse-weight", action="store_true")
    p_sweep.add_argument("--out", default=None)
    p_sweep.set_defaults(func=cmd_sweep)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
