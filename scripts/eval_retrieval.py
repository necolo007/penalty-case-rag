"""本地检索评测 CLI。

用法：
  python scripts/eval_retrieval.py \
    --submission data/eval/submission.jsonl \
    --gold data/eval/test_gold_labels.jsonl \
    --k 5 10
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_metrics import DEFAULT_K_VALUES, compute_retrieval_metrics


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
    parser.add_argument("--k", nargs="+", type=int, default=DEFAULT_K_VALUES)
    parser.add_argument("--output", default="data/eval/eval_report.json")
    args = parser.parse_args()

    metrics = compute_retrieval_metrics(
        load_jsonl(args.submission), load_jsonl(args.gold), k_values=args.k,
    )

    sub_path = Path(args.submission)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "task": "task3_retrieval",
        "submission": str(sub_path.resolve()),
        "gold": str(Path(args.gold).resolve()),
        **{k: v for k, v in metrics.items() if k != "per_query"},
        "per_query": metrics.get("per_query", []),
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics_sidecar = sub_path.with_suffix(".metrics.json")
    metrics_sidecar.write_text(
        json.dumps({k: v for k, v in report.items() if k != "per_query"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Evaluated queries: {metrics.get('evaluated', 0)}")
    for key in ["mrr", "top1_hit"]:
        if key in report:
            print(f"  {key}: {report[key]}")
    for k in sorted(set(args.k)):
        for prefix in ("recall", "ndcg"):
            mk = f"{prefix}@{k}"
            if mk in report:
                print(f"  {mk}: {report[mk]}")
    print(f"Report saved to {output}")
    print(f"Metrics saved to {metrics_sidecar}")


if __name__ == "__main__":
    main()
