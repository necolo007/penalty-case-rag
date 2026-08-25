"""端到端精排 A/B：legacy_four_way vs bge_m3（同一 split/limit/n）。

用法：
  python scripts/compare_retrieval_backends.py --split test --limit 30 --rerank

注意：两边共用当前 case_embeddings；请先用 BGE-M3 全量 reindex。
legacy 路径仍会走 BM25/标签/规则 + 同一 dense 向量。
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

from core.db import close_pool
from core.redis_client import close_redis
from engine.retrieval.base import SearchQuery
from eval_metrics import DEFAULT_K_VALUES, compute_retrieval_metrics
from eval_retrieval_local import (
    _load_jsonl,
    _normalize_questions,
    build_retriever,
)


async def _eval_backend(
    *,
    backend: str,
    questions: list[dict],
    gold: list[dict],
    top_k: int,
    use_rerank: bool,
    use_llm_rewrite: bool,
) -> dict:
    print(f"\n--- backend={backend} ---")
    retriever = await build_retriever(
        use_rerank=use_rerank,
        use_llm_rewrite=use_llm_rewrite,
        backend=backend,
    )
    submission = []
    for i, q in enumerate(questions, 1):
        resp = await retriever.retrieve(SearchQuery(
            query_text=q["query_text"],
            question_id=q["question_id"],
            scene=q.get("scene") or "",
            top_k=top_k,
            use_reranker=use_rerank,
        ))
        submission.append({
            "question_id": q["question_id"],
            "risk_type": "；".join(getattr(resp, "predicted_cn_tags", None) or []) or "",
            "retrieved_cases": [
                {"case_id": r.case_id, "rank": idx + 1, "reason": r.match_reason or ""}
                for idx, r in enumerate(resp.results)
            ],
            "suggestion": "",
        })
        if i % 10 == 0 or i == len(questions):
            print(f"  {backend} progress {i}/{len(questions)}")

    metrics = compute_retrieval_metrics(submission, gold, k_values=DEFAULT_K_VALUES)
    out = {
        "backend": backend,
        "metrics": {k: v for k, v in metrics.items() if k != "per_query"},
    }
    for k, v in out["metrics"].items():
        if k != "evaluated":
            print(f"  {k}: {v}")
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description="legacy vs bge_m3 端到端对比")
    parser.add_argument("--split", choices=["train", "test"], default="test")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--rerank", action="store_true", default=True)
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--llm-rewrite", action="store_true")
    parser.add_argument("--report-out", default=None)
    args = parser.parse_args()
    use_rerank = not args.no_rerank

    if args.split == "train":
        q_path = _ROOT / "data/eval/retrieval_train_queries.jsonl"
        g_path = q_path
    else:
        q_path = _ROOT / "data/eval/test_questions.jsonl"
        g_path = _ROOT / "data/eval/quarantine/test_gold_labels.jsonl"

    questions = _normalize_questions(_load_jsonl(q_path))[: args.limit]
    gold = _load_jsonl(g_path)

    results = []
    for backend in ("legacy_four_way", "bge_m3"):
        results.append(await _eval_backend(
            backend=backend,
            questions=questions,
            gold=gold,
            top_k=args.top_k,
            use_rerank=use_rerank,
            use_llm_rewrite=args.llm_rewrite,
        ))

    report = {
        "split": args.split,
        "n": len(questions),
        "rerank": use_rerank,
        "llm_rewrite": args.llm_rewrite,
        "results": results,
    }
    out = Path(args.report_out or f"data/eval/ab_backends_{args.split}_n{len(questions)}.json")
    if not out.is_absolute():
        out = _ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nA/B report → {out}")

    await close_pool()
    await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
