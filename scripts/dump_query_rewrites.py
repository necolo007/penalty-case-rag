"""导出 LLM 查询改写结果（对照原文），便于人工查看。

用法：
  python scripts/dump_query_rewrites.py --split test --limit 30 \\
    --out data/eval/query_rewrites_test_n30.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import get_settings
from engine.llm.client import create_llm_client
from engine.retrieval.query_rewriter import QueryRewriter


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser(description="导出 query 改写对照")
    parser.add_argument("--split", choices=["train", "test"], default="test")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--out", default="data/eval/query_rewrites_test_n30.jsonl")
    args = parser.parse_args()

    settings = get_settings()
    if not (settings.LLM_API_KEY or "").strip():
        raise SystemExit("需要 LLM_API_KEY")

    q_path = (
        _ROOT / "data/eval/retrieval_train_queries.jsonl"
        if args.split == "train"
        else _ROOT / "data/eval/test_questions.jsonl"
    )
    rows = _load_jsonl(q_path)[: args.limit]
    llm = create_llm_client(settings)
    rewriter = QueryRewriter(llm, use_llm_rewrite=True)

    out = Path(args.out)
    if not out.is_absolute():
        out = _ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", encoding="utf-8") as f:
        for i, row in enumerate(rows, 1):
            qid = row.get("question_id") or row.get("query_id") or ""
            qtext = row.get("query_text") or ""
            rewritten = await rewriter.rewrite(qtext)
            rec = {
                "question_id": qid,
                "query_text": qtext,
                "rewritten_query": rewritten,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"--- {qid} ---")
            print(f"原文: {qtext}")
            print(f"改写: {rewritten}")
            print()
            if i % 10 == 0:
                print(f"  progress {i}/{len(rows)}", flush=True)

    print(f"Wrote {len(rows)} → {out}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
