"""对已有 submission Top-K 做 LLM 列表重排+减枝（不重跑向量检索）。

用法：
  python scripts/llm_listwise_on_submission.py \\
    --submission data/eval/submission_test_vb_summary_n30.jsonl \\
    --top-k 10 --keep-min 3 --keep-max 8
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
from engine.llm.client import create_llm_client
from engine.retrieval.base import SearchResult
from engine.retrieval.llm_listwise import LlmListwiseReranker
from eval_metrics import compute_retrieval_metrics


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def _load_cases(pool, case_ids: list[str]) -> dict[str, dict]:
    if not case_ids:
        return {}
    rows = await pool.fetch(
        """
        SELECT case_id, party_name, violation_behavior, penalty_content,
               COALESCE(regulator, '') AS regulator, risk_tags
        FROM penalty_cases
        WHERE case_id = ANY($1::text[])
        """,
        case_ids,
    )
    return {r["case_id"]: dict(r) for r in rows}


def _to_results(case_ids: list[str], meta: dict[str, dict]) -> list[SearchResult]:
    out: list[SearchResult] = []
    for cid in case_ids:
        m = meta.get(cid) or {}
        out.append(SearchResult(
            case_id=cid,
            party_name=m.get("party_name") or "",
            violation_behavior=m.get("violation_behavior") or "",
            penalty_content=m.get("penalty_content") or "",
            regulator=m.get("regulator") or "",
            risk_tags=list(m.get("risk_tags") or []),
            score=0.0,
        ))
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description="LLM listwise rerank on submission")
    parser.add_argument("--submission", required=True)
    parser.add_argument("--questions", default="data/eval/test_questions.jsonl")
    parser.add_argument("--gold", default="data/eval/quarantine/test_gold_labels.jsonl")
    parser.add_argument("--top-k", type=int, default=10, help="从 submission 取前 K 做列表重排")
    parser.add_argument("--keep-min", type=int, default=3)
    parser.add_argument("--keep-max", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default=None)
    parser.add_argument("--report-out", default=None)
    args = parser.parse_args()

    sub_path = Path(args.submission)
    if not sub_path.is_absolute():
        sub_path = _ROOT / sub_path
    q_path = Path(args.questions)
    if not q_path.is_absolute():
        q_path = _ROOT / q_path
    g_path = Path(args.gold)
    if not g_path.is_absolute():
        g_path = _ROOT / g_path
    if not g_path.exists():
        legacy = _ROOT / "data/eval/test_gold_labels.jsonl"
        if legacy.exists():
            g_path = legacy

    submission = _load_jsonl(sub_path)
    questions = {r.get("question_id"): r for r in _load_jsonl(q_path)}
    gold = _load_jsonl(g_path)
    if args.limit:
        submission = submission[: args.limit]

    out_path = Path(args.out) if args.out else sub_path.with_name(
        sub_path.stem + f"_listwise_k{args.keep_max}.jsonl"
    )
    if not out_path.is_absolute():
        out_path = _ROOT / out_path
    rep_path = Path(args.report_out) if args.report_out else out_path.with_suffix(".metrics.json")
    if not rep_path.is_absolute():
        rep_path = _ROOT / rep_path

    settings = get_settings()
    llm = create_llm_client(settings)
    listwise = LlmListwiseReranker(
        llm, keep_min=args.keep_min, keep_max=args.keep_max,
    )
    pool = await create_pool()

    new_rows: list[dict] = []
    for i, row in enumerate(submission, 1):
        qid = row.get("question_id") or ""
        qtext = (questions.get(qid) or {}).get("query_text") or ""
        cases = (row.get("retrieved_cases") or [])[: args.top_k]
        ids = [c.get("case_id") for c in cases if c.get("case_id")]
        meta = await _load_cases(pool, ids)
        results = _to_results(ids, meta)
        ranked = await listwise.rerank(qtext, results, top_k=args.keep_max)
        reason_map = {c.get("case_id"): c.get("reason") or "" for c in cases}
        new_rows.append({
            "question_id": qid,
            "risk_type": row.get("risk_type") or "",
            "retrieved_cases": [
                {
                    "case_id": r.case_id,
                    "rank": idx + 1,
                    "reason": reason_map.get(r.case_id) or r.match_reason or "llm_listwise",
                }
                for idx, r in enumerate(ranked)
            ],
            "suggestion": row.get("suggestion") or "",
            "listwise_note": getattr(ranked[0], "match_reason", "") if ranked else "",
        })
        print(
            f"  [{i}/{len(submission)}] {qid}: "
            f"{len(ids)} → {len(ranked)} "
            f"({', '.join(r.case_id for r in ranked[:5])})"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in new_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    metrics = compute_retrieval_metrics(new_rows, gold, k_values=[5, 10])
    rep_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Submission → {out_path}")
    print(f"Metrics → {rep_path}")
    for k, v in metrics.items():
        if k not in ("evaluated", "per_query"):
            print(f"  {k}: {v}")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
