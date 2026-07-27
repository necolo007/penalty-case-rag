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

# 短结构化字段：要求逐字精确匹配（当事人/文号/机关/机构类型本身就应唯一确定）。
EXACT_MATCH_FIELDS = {"party_name", "penalty_doc_no", "regulator", "institution_type"}
# 长自由文本字段：原文常见 OCR 逐行换行，金标与规则抽取的取词边界很难逐字对齐，
# 用逐字相等来评估基本等价于恒为 0，不能反映真实抽取质量。
# 参照抽取式问答/摘要评测的通行做法（token-level overlap F1，近似 SQuAD/ROUGE-1），
# 改为字符级 n-gram（这里用单字 token，对中文更稳）重叠 F1 + 双向包含关系加分。
OVERLAP_FIELDS = {"violation_behavior", "penalty_content"}


def load_jsonl(path: str) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def normalize(value) -> str:
    return str(value or "").replace(" ", "").strip()


def _char_overlap_f1(pred: str, truth: str) -> tuple[float, float, float]:
    """字符级重叠 P/R/F1：容忍取词边界差异，仍能反映内容层面的抽取质量。

    完全包含关系（一个是另一个的子串，常见于「抽取截断/多切一点」）直接记为满分，
    因为此时抽取内容并未出错，只是边界比金标更短或更长。
    """
    if pred == truth:
        return 1.0, 1.0, 1.0
    if pred and truth and (pred in truth or truth in pred):
        return 1.0, 1.0, 1.0
    if not pred or not truth:
        return 0.0, 0.0, 0.0
    pred_counts: dict[str, int] = {}
    for ch in pred:
        pred_counts[ch] = pred_counts.get(ch, 0) + 1
    truth_counts: dict[str, int] = {}
    for ch in truth:
        truth_counts[ch] = truth_counts.get(ch, 0) + 1
    overlap = sum(min(c, truth_counts.get(ch, 0)) for ch, c in pred_counts.items())
    precision = overlap / len(pred) if pred else 0.0
    recall = overlap / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def compute_field_metrics(extracted: list[dict], gold: list[dict]) -> dict:
    gold_by_id = {g["case_id"]: g for g in gold}
    metrics: dict = {}

    for field_name in EVAL_FIELDS:
        use_overlap = field_name in OVERLAP_FIELDS
        if use_overlap:
            p_sum = r_sum = f_sum = 0.0
            n = 0
            fp = fn = 0
            for e in extracted:
                g = gold_by_id.get(e.get("case_id"))
                if g is None:
                    continue
                pred, truth = normalize(e.get(field_name)), normalize(g.get(field_name))
                if pred and truth:
                    p, r, f = _char_overlap_f1(pred, truth)
                    p_sum += p
                    r_sum += r
                    f_sum += f
                    n += 1
                elif pred and not truth:
                    fp += 1
                    n += 1
                elif truth and not pred:
                    fn += 1
                    n += 1
            precision = p_sum / n if n else 0.0
            recall = r_sum / n if n else 0.0
            f1 = f_sum / n if n else 0.0
            metrics[field_name] = {
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "scoring": "char_overlap",
            }
            continue

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
            "scoring": "exact_match",
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
