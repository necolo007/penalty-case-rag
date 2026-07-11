"""本地检索评测 CLI。

用法：
  python scripts/eval_retrieval.py \
    --submission data/eval/submission.jsonl \
    --gold data/eval/test_gold_labels.jsonl \
    --k 5 10
"""

import argparse
import json
from pathlib import Path

from scripts.eval_metrics import compute_retrieval_metrics


def load_jsonl(path: str) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main():
    parser = argparse.ArgumentParser(description="检索评测：Recall@K / MRR / NDCG@K / Top-1")
    parser.add_argument("--submission", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--k", nargs="+", type=int, default=[5, 10])
    parser.add_argument("--output", default="data/eval/eval_report.json")
    args = parser.parse_args()

    metrics = compute_retrieval_metrics(
        load_jsonl(args.submission), load_jsonl(args.gold), k_values=args.k,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Evaluated queries: {metrics.get('evaluated', 0)}")
    for key, value in metrics.items():
        if key not in ("evaluated", "per_query"):
            print(f"  {key}: {value}")
    print(f"Report saved to {output}")


if __name__ == "__main__":
    main()
