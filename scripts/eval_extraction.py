"""字段抽取评测 CLI：对比 gold_extraction_cases.jsonl 计算字段级 P/R/F1。

用法：
  python scripts/eval_extraction.py \
    --extracted data/eval/extracted_cases.jsonl \
    --gold data/eval/gold_extraction_cases.jsonl
"""

import argparse
import json
from pathlib import Path

EVAL_FIELDS = [
    "party_name", "penalty_doc_no", "violation_behavior",
    "penalty_content", "regulator", "institution_type",
]


def load_jsonl(path: str) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def normalize(value) -> str:
    return str(value or "").replace(" ", "").strip()


def compute_field_metrics(extracted: list[dict], gold: list[dict]) -> dict:
    gold_by_id = {g["case_id"]: g for g in gold}
    metrics: dict = {}

    for field_name in EVAL_FIELDS:
        tp = fp = fn = 0
        for e in extracted:
            g = gold_by_id.get(e.get("case_id"))
            if g is None:
                continue
            pred, truth = normalize(e.get(field_name)), normalize(g.get(field_name))
            if pred and truth:
                if pred == truth:
                    tp += 1
                else:
                    fp += 1
                    fn += 1
            elif pred and not truth:
                fp += 1
            elif truth and not pred:
                fn += 1

        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[field_name] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    # 保险识别二分类准确率
    correct = total = 0
    for e in extracted:
        g = gold_by_id.get(e.get("case_id"))
        if g is not None and "is_insurance_related" in g:
            total += 1
            if bool(e.get("is_insurance_related")) == bool(g["is_insurance_related"]):
                correct += 1
    metrics["insurance_classification_accuracy"] = round(correct / total, 4) if total else None

    macro_f1 = sum(m["f1"] for f, m in metrics.items() if isinstance(m, dict)) / len(EVAL_FIELDS)
    metrics["macro_f1"] = round(macro_f1, 4)
    return metrics


def main():
    parser = argparse.ArgumentParser(description="字段抽取评测")
    parser.add_argument("--extracted", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--output", default="data/eval/extraction_eval_report.json")
    args = parser.parse_args()

    metrics = compute_field_metrics(load_jsonl(args.extracted), load_jsonl(args.gold))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    for field_name, m in metrics.items():
        print(f"{field_name}: {m}")
    print(f"Report saved to {output}")


if __name__ == "__main__":
    main()
