"""本地四路检索评测（无 HTTP；可选精排）。

用法：
  python scripts/eval_retrieval_local.py --split train --limit 50
  python scripts/eval_retrieval_local.py --split test --limit 50 --rerank
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
from engine.retrieval.assemble import (
    AnyRetriever,
    assemble_hybrid_retriever,
    ensure_sparse_index_loaded,
)
from engine.retrieval.base import SearchQuery
from engine.retrieval.query_rewriter import QueryRewriter
from engine.retrieval.reranker import NoopReranker, Reranker
from engine.retrieval.risk_predictor import RiskPredictor
from engine.retrieval.synonym_expander import SynonymExpander
from eval_metrics import compute_retrieval_metrics


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _qid(item: dict) -> str:
    return item.get("question_id") or item.get("query_id") or ""


def _normalize_questions(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({
            "question_id": _qid(r),
            "query_text": r.get("query_text") or "",
            "scene": r.get("scene") or "",
        })
    return out


class SynonymOnlyRewriter:
    def __init__(self, expander: SynonymExpander):
        self.expander = expander

    async def rewrite(self, query_text: str) -> str:
        return (await self.expander.expand(query_text)) or query_text


async def build_retriever(
    *, use_rerank: bool, use_llm_rewrite: bool = False,
    rerank_candidates: int | None = None,
    backend: str | None = None,
    enable_hyde: bool | None = None,
) -> AnyRetriever:
    settings = get_settings()
    if backend:
        settings.RETRIEVAL_BACKEND = backend
    if enable_hyde is not None:
        settings.RETRIEVAL_HYDE_ENABLED = enable_hyde
    pool = await create_pool()
    redis = await get_redis()
    embedder = create_embedding_provider(settings)
    expander = SynonymExpander(pool)
    if use_rerank and settings.RERANKER_ENABLED:
        try:
            reranker = Reranker(
                settings.RERANKER_MODEL,
                settings.RERANKER_DEVICE,
                batch_size=settings.RERANKER_BATCH_SIZE,
                doc_max_chars=settings.RERANKER_DOC_MAX_CHARS,
            )
        except Exception as e:  # noqa: BLE001
            print(f"Reranker unavailable ({e}), fallback Noop")
            reranker = NoopReranker()
    else:
        reranker = NoopReranker()

    # HyDE 与 llm-rewrite 可独立：仅开 HyDE 时改写仍走同义词，只多一路 dense_hyde。
    need_llm = bool(use_llm_rewrite or settings.RETRIEVAL_HYDE_ENABLED)
    llm_client = None
    if need_llm:
        try:
            llm_client = create_llm_client(settings)
        except Exception as e:  # noqa: BLE001
            print(f"LLM unavailable ({e}); HyDE/llm-rewrite disabled for this run")
            if settings.RETRIEVAL_HYDE_ENABLED:
                settings.RETRIEVAL_HYDE_ENABLED = False
    if settings.RETRIEVAL_HYDE_ENABLED and llm_client is None:
        print("HyDE enabled but no LLM client; dense_hyde channel will be skipped")
        settings.RETRIEVAL_HYDE_ENABLED = False

    if llm_client is not None:
        rewriter = QueryRewriter(
            llm_client, expander, use_llm_rewrite=bool(use_llm_rewrite),
        )
    else:
        rewriter = SynonymOnlyRewriter(expander)
    risk_predictor = RiskPredictor(pool, llm_client=llm_client)

    sparse_index = None
    be = (settings.RETRIEVAL_BACKEND or "bge_m3").strip().lower()
    if be not in ("legacy_four_way", "legacy", "four_way"):
        sparse_index = await ensure_sparse_index_loaded(pool)

    return assemble_hybrid_retriever(
        settings=settings,
        pool=pool,
        rewriter=rewriter,
        risk_predictor=risk_predictor,
        reranker=reranker,
        query_encoder=CachedQueryEncoder(embedder, redis, ttl=settings.EMBEDDING_CACHE_TTL),
        rerank_candidates=rerank_candidates,
        sparse_index=sparse_index,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="本地检索评测")
    parser.add_argument("--split", choices=["train", "test"], default="test")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--llm-rewrite", action="store_true",
                        help="使用生产同款 LLM 查询改写（否则用同义词词典降级改写）")
    parser.add_argument(
        "--hyde", action="store_true",
        help="强制开启 HyDE dense 通道（需 LLM；覆盖 Settings.RETRIEVAL_HYDE_ENABLED）",
    )
    parser.add_argument(
        "--no-hyde", action="store_true",
        help="关闭 HyDE（对比基线时用）",
    )
    parser.add_argument("--rerank-candidates", type=int, default=None,
                        help="精排候选数（默认读 Settings.RETRIEVAL_RERANK_CANDIDATES）")
    parser.add_argument("--backend", default=None,
                        help="检索后端：bge_m3 | legacy_four_way（默认读 Settings）")
    parser.add_argument("--questions", default=None)
    parser.add_argument("--gold", default=None)
    parser.add_argument("--submission-out", default=None)
    parser.add_argument("--report-out", default=None)
    args = parser.parse_args()

    if args.split == "train":
        q_path = args.questions or "data/eval/retrieval_train_queries.jsonl"
        g_path = args.gold or "data/eval/retrieval_train_queries.jsonl"
        tag = "train"
    else:
        q_path = args.questions or "data/eval/test_questions.jsonl"
        g_path = args.gold or "data/eval/quarantine/test_gold_labels.jsonl"
        tag = "test"

    q_file = _ROOT / q_path if not Path(q_path).is_absolute() else Path(q_path)
    g_file = _ROOT / g_path if not Path(g_path).is_absolute() else Path(g_path)
    # 兼容旧路径：若 quarantine 不存在则回退根目录（并警告）
    if tag == "test" and not g_file.exists():
        legacy = _ROOT / "data/eval/test_gold_labels.jsonl"
        if legacy.exists():
            print("WARNING: using leaked data/eval/test_gold_labels.jsonl; "
                  "prefer quarantine/ and avoid tuning against it.")
            g_file = legacy
    questions = _normalize_questions(_load_jsonl(q_file))
    gold = _load_jsonl(g_file)
    if args.limit:
        questions = questions[: args.limit]

    if args.hyde and args.no_hyde:
        raise SystemExit("--hyde 与 --no-hyde 不能同时使用")
    enable_hyde: bool | None = None
    if args.hyde:
        enable_hyde = True
    elif args.no_hyde:
        enable_hyde = False

    suffix = "rerank" if args.rerank else "norerank"
    if args.llm_rewrite:
        suffix += "_llm"
    if enable_hyde is True or (
        enable_hyde is None and get_settings().RETRIEVAL_HYDE_ENABLED
    ):
        suffix += "_hyde"
    backend = args.backend or get_settings().RETRIEVAL_BACKEND
    suffix += f"_{backend.replace('-', '_')}"
    sub_out = Path(args.submission_out or f"data/eval/submission_{tag}_{suffix}.jsonl")
    rep_out = Path(args.report_out or f"data/eval/eval_report_{tag}_{suffix}.json")
    if not sub_out.is_absolute():
        sub_out = _ROOT / sub_out
    if not rep_out.is_absolute():
        rep_out = _ROOT / rep_out

    hyde_flag = (
        enable_hyde
        if enable_hyde is not None
        else get_settings().RETRIEVAL_HYDE_ENABLED
    )
    print(
        f"split={tag} n={len(questions)} backend={backend} "
        f"rerank={args.rerank} llm_rewrite={args.llm_rewrite} "
        f"hyde={hyde_flag} top_k={args.top_k}"
    )
    retriever = await build_retriever(
        use_rerank=args.rerank, use_llm_rewrite=args.llm_rewrite,
        rerank_candidates=args.rerank_candidates, backend=args.backend,
        enable_hyde=enable_hyde,
    )

    submission = []
    for i, q in enumerate(questions, 1):
        resp = await retriever.retrieve(SearchQuery(
            query_text=q["query_text"],
            question_id=q["question_id"],
            scene=q.get("scene") or "",
            top_k=args.top_k,
            use_reranker=args.rerank,
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
            print(f"  progress {i}/{len(questions)}")

    sub_out.parent.mkdir(parents=True, exist_ok=True)
    with sub_out.open("w", encoding="utf-8") as f:
        for row in submission:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    metrics = compute_retrieval_metrics(submission, gold, k_values=[5, 10])
    rep_out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evaluated: {metrics.get('evaluated')}")
    for k, v in metrics.items():
        if k not in ("evaluated", "per_query"):
            print(f"  {k}: {v}")
    print(f"Submission → {sub_out}")
    print(f"Report → {rep_out}")

    await close_pool()
    await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
