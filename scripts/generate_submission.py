"""生成赛题提交文件 submission.jsonl（全量 test_questions）。

对齐生产管线：LLM 改写 + BGE-M3 + CE 精排 + listwise + ReviewGenerator（risk_type / suggestion）。

用法：
  python scripts/generate_submission.py
  python scripts/generate_submission.py --limit 5 --top-k 10
  python scripts/generate_submission.py --resume   # 跳过已写出的 question_id
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
for p in (_ROOT, _SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from core.config import get_settings
from core.db import close_pool
from core.redis_client import close_redis
from engine.classification.competition_label_map import (
    format_submission_risk_type,
    normalize_cn_tags,
    resolve_final_cn_tags,
)
from engine.llm.client import create_llm_client
from engine.retrieval.base import SearchQuery
from engine.review.generator import ReviewGenerator
from eval_retrieval_local import build_retriever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_submission")


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _qid(item: dict) -> str:
    return str(item.get("question_id") or item.get("query_id") or "").strip()


def _finalize_cn_tags(query_text: str, retrieval, llm_risk_names: list[str], settings) -> list[str]:
    case_tags = [
        t
        for r in retrieval.results[: settings.TAG_BACKFILL_TOP_CASES]
        for t in (r.risk_tags or [])
    ]
    return resolve_final_cn_tags(
        query_text=query_text,
        keyword_tags=getattr(retrieval, "predicted_cn_tags", None),
        case_tags=case_tags,
        llm_tags=llm_risk_names,
        competition_ids=retrieval.predicted_risk_ids,
        max_tags=settings.CN_TAG_FINAL_MAX,
    )


def _build_row(query_text: str, qid: str, retrieval, generator: ReviewGenerator | None, settings) -> dict:
    suggestion = ""
    reasons = {r.case_id: (r.match_reason or "") for r in retrieval.results}
    llm_risk_names: list[str] = []

    if generator is not None and retrieval.results:
        review = generator.generate(query_text, retrieval.results)
        if review.get("risk_types"):
            llm_risk_names = normalize_cn_tags(list(review["risk_types"]))
        suggestion = review.get("suggestion") or ""
        for a in review.get("case_analysis") or []:
            if a.get("case_id") and a.get("similarity_reason"):
                reasons[a["case_id"]] = a["similarity_reason"]

    cn_tags = _finalize_cn_tags(query_text, retrieval, llm_risk_names, settings)
    risk_type = format_submission_risk_type(
        cn_tags=cn_tags,
        competition_ids=retrieval.predicted_risk_ids,
    )
    if not (risk_type or "").strip():
        raise ValueError("empty risk_type")
    if not retrieval.results:
        raise ValueError("empty retrieved_cases")

    return {
        "question_id": qid,
        "risk_type": risk_type,
        "retrieved_cases": [
            {
                "case_id": r.case_id,
                "rank": i + 1,
                "reason": reasons.get(r.case_id, r.match_reason or ""),
            }
            for i, r in enumerate(retrieval.results)
        ],
        "suggestion": suggestion,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="生成赛题 submission.jsonl")
    parser.add_argument(
        "--questions",
        default="data/eval/test_questions.jsonl",
        help="测试题路径",
    )
    parser.add_argument(
        "--output",
        default="data/eval/submission.jsonl",
        help="提交文件输出路径",
    )
    parser.add_argument("--errors-out", default="data/eval/submission_errors.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--resume", action="store_true", help="跳过 output 中已有的 question_id")
    parser.add_argument("--no-listwise", action="store_true")
    parser.add_argument("--no-suggestion", action="store_true", help="跳过 ReviewGenerator（更快，suggestion 为空）")
    args = parser.parse_args()

    settings = get_settings()
    if not (settings.LLM_API_KEY or "").strip():
        raise SystemExit("需要配置 LLM_API_KEY")

    settings.RETRIEVAL_LLM_LISTWISE = not args.no_listwise

    q_path = Path(args.questions)
    if not q_path.is_absolute():
        q_path = _ROOT / q_path
    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = _ROOT / out_path
    err_path = Path(args.errors_out)
    if not err_path.is_absolute():
        err_path = _ROOT / err_path

    questions = _load_jsonl(q_path)
    if args.limit:
        questions = questions[: args.limit]
    if not questions:
        raise SystemExit(f"无题目: {q_path}")

    done_ids: set[str] = set()
    existing_rows: list[dict] = []
    if args.resume and out_path.is_file():
        existing_rows = _load_jsonl(out_path)
        done_ids = {_qid(r) for r in existing_rows if _qid(r)}
        print(f"resume: 已有 {len(done_ids)} 条，将跳过")

    pending = [q for q in questions if _qid(q) not in done_ids]
    print(
        f"total={len(questions)} pending={len(pending)} top_k={args.top_k} "
        f"listwise={settings.RETRIEVAL_LLM_LISTWISE} suggestion={not args.no_suggestion}"
    )

    retriever = await build_retriever(
        use_rerank=True,
        use_llm_rewrite=True,
        backend="bge_m3",
    )
    llm = create_llm_client(settings)
    generator = None if args.no_suggestion else ReviewGenerator(llm)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if (args.resume and existing_rows) else "w"
    # 非 resume 或空文件时重写；resume 时追加
    if mode == "w":
        existing_rows = []

    ok = len(existing_rows)
    failed = 0
    t0 = time.perf_counter()

    with out_path.open(mode, encoding="utf-8") as out_f, err_path.open(
        "a" if args.resume else "w", encoding="utf-8"
    ) as err_f:
        if mode == "w" and existing_rows:
            for row in existing_rows:
                out_f.write(json.dumps(row, ensure_ascii=False) + "\n")

        for i, q in enumerate(pending, 1):
            qid = _qid(q)
            qtext = (q.get("query_text") or "").strip()
            try:
                if not qid:
                    raise ValueError("missing question_id")
                if not qtext:
                    raise ValueError("missing query_text")
                retrieval = await retriever.retrieve(
                    SearchQuery(
                        query_text=qtext,
                        question_id=qid,
                        scene=q.get("scene") or "",
                        top_k=args.top_k,
                        use_reranker=True,
                    )
                )
                row = _build_row(qtext, qid, retrieval, generator, settings)
                out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                out_f.flush()
                ok += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                logger.exception("failed %s", qid)
                err_f.write(
                    json.dumps(
                        {
                            "question_id": qid,
                            "error": str(e),
                            "query_text": qtext[:200],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                err_f.flush()

            if i % 5 == 0 or i == len(pending):
                elapsed = time.perf_counter() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(pending) - i) / rate if rate > 0 else 0
                print(
                    f"  [{i}/{len(pending)}] ok={ok} fail={failed} "
                    f"elapsed={elapsed/60:.1f}m eta={eta/60:.1f}m",
                    flush=True,
                )

    await close_pool()
    await close_redis()

    # 最终校验：行数与题目数
    final_rows = _load_jsonl(out_path)
    final_ids = [_qid(r) for r in final_rows]
    print(f"Submission → {out_path}")
    print(f"  rows={len(final_rows)} unique={len(set(final_ids))} failed_this_run={failed}")
    print(f"Errors → {err_path}")
    if len(final_rows) != len(questions) or len(set(final_ids)) != len(questions):
        print("WARNING: 行数与题目数不一致，请检查 errors 后 --resume 重跑")
    else:
        print("schema_ok: 200 题齐全（或 --limit 子集齐全）")


if __name__ == "__main__":
    asyncio.run(main())
