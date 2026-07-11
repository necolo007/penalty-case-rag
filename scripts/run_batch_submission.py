"""批量生成比赛提交文件 CLI：test_questions.jsonl → submission.jsonl。

通过 HTTP API 调用（要求 API 服务已启动）：
  python scripts/run_batch_submission.py \
    --input data/eval/test_questions.jsonl \
    --output data/eval/submission.jsonl \
    --api http://localhost:8000
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description="批量生成 submission.jsonl")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="data/eval/submission.jsonl")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    questions = [
        json.loads(line)
        for line in Path(args.input).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"Loaded {len(questions)} test questions")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    ok = failed = 0
    with httpx.Client(base_url=args.api, timeout=120) as client, \
            output.open("w", encoding="utf-8") as f:
        for i, q in enumerate(questions, 1):
            payload = {
                "query_text": q["query_text"],
                "question_id": q.get("question_id"),
                "scene": q.get("scene"),
                "top_k": args.top_k,
            }
            try:
                resp = client.post("/api/v1/search/retrieve",
                                   params={"format": "submission"}, json=payload)
                resp.raise_for_status()
                f.write(json.dumps(resp.json(), ensure_ascii=False) + "\n")
                ok += 1
            except Exception as e:  # noqa: BLE001 - 单条失败不中断
                print(f"  [{q.get('question_id')}] FAILED: {e}", file=sys.stderr)
                f.write(json.dumps({
                    "question_id": q.get("question_id"),
                    "risk_type": "", "retrieved_cases": [], "suggestion": "",
                }, ensure_ascii=False) + "\n")
                failed += 1
            if i % 10 == 0:
                print(f"  progress: {i}/{len(questions)}")

    took = time.perf_counter() - started
    print(f"Done: {ok} ok, {failed} failed, {took:.1f}s → {output}")


if __name__ == "__main__":
    main()
