"""字段抽取评测 CLI：对比 gold_extraction_cases.jsonl 计算字段级 P/R/F1。

用法：
  python scripts/eval_extraction.py \
    --extracted data/eval/extracted_cases.jsonl \
    --gold data/eval/gold_extraction_cases.jsonl

评测口径修正（六次优化，对齐《最新评测结果问题.md》#1/#2）：

1. 多案例匹配：`extracted_cases.jsonl` 现在按 file_id 携带该文档抽出的**全部**
   候选案例（不再是「金标一行 = 预测一行」）。本脚本按 file_id 分组后，用
   二分图最大权匹配（候选案例较少，穷举即可保证最优）把预测案例与金标案例
   一一配对；未匹配的预测记为该文档的 FP，未匹配的金标记为 FN。不再把金标
   case_id 强行套到某条预测上。
2. 长字段评分收紧：不再对"预测是金标子串（或反之）"直接记满分——这会把
   截断、多抓/少抓都当作完美命中，掩盖真实质量。改为纯字符级重叠 P/R/F1，
   并单独统计截断率（预测显著短于金标且为其子串）供人工判断。
"""

import argparse
import itertools
from collections import defaultdict
from pathlib import Path

import json


EVAL_FIELDS = [
    "party_name", "penalty_doc_no", "violation_behavior",
    "penalty_content", "regulator", "institution_type",
]

# 短结构化字段：要求逐字精确匹配（当事人/文号/机关/机构类型本身就应唯一确定）。
EXACT_MATCH_FIELDS = {"party_name", "penalty_doc_no", "regulator", "institution_type"}
# 长自由文本字段：原文常见 OCR 逐行换行，金标与规则抽取的取词边界很难逐字对齐，
# 用字符级重叠 F1（近似 SQuAD/ROUGE-1）评估，但不再对"子串包含"直接判满分。
OVERLAP_FIELDS = {"violation_behavior", "penalty_content"}

# 截断判定：预测是金标的严格子串，且长度不足金标的这个比例，视为"抽取被截断"
# 而非"抽取内容有误"，单独统计，不计入 F1 加分。
TRUNCATION_LEN_RATIO = 0.7


def load_jsonl(path: str) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


_BRACKET_MAP = str.maketrans({"[": "〔", "]": "〕", "(": "（", ")": "）"})


def normalize(value) -> str:
    """去空格 + 半角/全角括号归一，避免文号「[2010]」vs「〔2010〕」这类纯书写
    差异被误判为抽取错误（原文本身两种写法都存在，属于合法等价形式）。"""
    return str(value or "").replace(" ", "").strip().translate(_BRACKET_MAP)


def _char_overlap_f1(pred: str, truth: str) -> tuple[float, float, float]:
    """字符级重叠 P/R/F1：容忍取词边界差异，但不因"包含关系"直接给满分。"""
    if pred == truth:
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


def _is_truncation(pred: str, truth: str) -> bool:
    if not pred or not truth or pred == truth:
        return False
    return pred in truth and len(pred) < TRUNCATION_LEN_RATIO * len(truth)


# ---------- 多案例匹配（按 file_id 分组后的二分图最大权匹配） ----------

def _pair_score(pred: dict, gold: dict) -> float:
    """预测/金标两条案例的相似度，用于同一 file_id 内多候选时的最优配对。"""
    score = 0.0
    doc_p, doc_g = normalize(pred.get("penalty_doc_no")), normalize(gold.get("penalty_doc_no"))
    if doc_p and doc_g:
        score += 3.0 if doc_p == doc_g else 0.0

    pn_p, pn_g = normalize(pred.get("party_name")), normalize(gold.get("party_name"))
    if pn_p and pn_g:
        if pn_p == pn_g:
            score += 3.0
        elif pn_p in pn_g or pn_g in pn_p:
            score += 1.5

    reg_p, reg_g = normalize(pred.get("regulator")), normalize(gold.get("regulator"))
    if reg_p and reg_g and reg_p == reg_g:
        score += 1.0

    for field_name in OVERLAP_FIELDS:
        vp, vg = normalize(pred.get(field_name)), normalize(gold.get(field_name))
        if vp and vg:
            _, _, f1 = _char_overlap_f1(vp, vg)
            score += f1

    return score


def _match_group(golds: list[dict], preds: list[dict]) -> list[tuple[dict | None, dict | None]]:
    """穷举最优二分图匹配（组内候选数极小，穷举即为最优解，无需近似算法）。"""
    n, m = len(golds), len(preds)
    if n == 0:
        return [(None, p) for p in preds]
    if m == 0:
        return [(g, None) for g in golds]

    scores = [[_pair_score(preds[j], golds[i]) for j in range(m)] for i in range(n)]

    best_total = -1.0
    best_assign: list[tuple[int, int]] = []
    k = min(n, m)
    pred_idx_pool = range(m)
    for combo in itertools.permutations(pred_idx_pool, k):
        if n <= m:
            assign = list(zip(range(n), combo))
        else:
            assign = list(zip(combo, range(m)))
        total = sum(scores[i][j] for i, j in assign)
        if total > best_total:
            best_total = total
            best_assign = assign

    matched_g = {i for i, _ in best_assign}
    matched_p = {j for _, j in best_assign}
    result: list[tuple[dict | None, dict | None]] = [(golds[i], preds[j]) for i, j in best_assign]
    result += [(golds[i], None) for i in range(n) if i not in matched_g]
    result += [(None, preds[j]) for j in range(m) if j not in matched_p]
    return result


def build_matched_pairs(extracted: list[dict], gold: list[dict]) -> list[tuple[dict | None, dict | None]]:
    gold_by_fid: dict[str, list[dict]] = defaultdict(list)
    for g in gold:
        gold_by_fid[g.get("file_id") or ""].append(g)
    pred_by_fid: dict[str, list[dict]] = defaultdict(list)
    for e in extracted:
        pred_by_fid[e.get("file_id") or ""].append(e)

    pairs: list[tuple[dict | None, dict | None]] = []
    for fid in set(gold_by_fid) | set(pred_by_fid):
        pairs.extend(_match_group(gold_by_fid.get(fid, []), pred_by_fid.get(fid, [])))
    return pairs


# ---------- 字段级 P/R/F1（基于已匹配好的 (gold, pred) 对） ----------

def compute_field_metrics(extracted: list[dict], gold: list[dict]) -> dict:
    pairs = build_matched_pairs(extracted, gold)
    metrics: dict = {}

    for field_name in EVAL_FIELDS:
        use_overlap = field_name in OVERLAP_FIELDS
        if use_overlap:
            p_sum = r_sum = f_sum = 0.0
            n = 0
            truncated = 0
            for g, e in pairs:
                pred = normalize((e or {}).get(field_name))
                truth = normalize((g or {}).get(field_name))
                if pred and truth:
                    p, r, f = _char_overlap_f1(pred, truth)
                    p_sum += p
                    r_sum += r
                    f_sum += f
                    n += 1
                    if _is_truncation(pred, truth):
                        truncated += 1
                elif pred and not truth:
                    n += 1
                elif truth and not pred:
                    n += 1
            precision = p_sum / n if n else 0.0
            recall = r_sum / n if n else 0.0
            f1 = f_sum / n if n else 0.0
            metrics[field_name] = {
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "scoring": "char_overlap_strict",
                "truncation_rate": round(truncated / n, 4) if n else 0.0,
            }
            continue

        tp = fp = fn = 0
        for g, e in pairs:
            pred = normalize((e or {}).get(field_name))
            truth = normalize((g or {}).get(field_name))
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

    # 保险识别二分类准确率（仅统计已匹配上的 pair，未匹配案例不计入分类准确率）
    correct = total = 0
    for g, e in pairs:
        if g is not None and e is not None and "is_insurance_related" in g:
            total += 1
            if bool(e.get("is_insurance_related")) == bool(g["is_insurance_related"]):
                correct += 1
    metrics["insurance_classification_accuracy"] = round(correct / total, 4) if total else None

    # 多案例匹配诊断：未匹配的金标/预测数量，反映拆分/漏检/多检情况
    unmatched_gold = sum(1 for g, e in pairs if g is not None and e is None)
    unmatched_pred = sum(1 for g, e in pairs if g is None and e is not None)
    metrics["case_matching"] = {
        "gold_cases": sum(1 for g, _ in pairs if g is not None),
        "pred_cases": sum(1 for _, e in pairs if e is not None),
        "matched_pairs": sum(1 for g, e in pairs if g is not None and e is not None),
        "unmatched_gold_fn_cases": unmatched_gold,
        "unmatched_pred_fp_cases": unmatched_pred,
    }

    macro_f1 = sum(m["f1"] for f, m in metrics.items() if isinstance(m, dict) and "f1" in m) / len(EVAL_FIELDS)
    metrics["macro_f1"] = round(macro_f1, 4)
    return metrics


# ---------- 金标噪声诊断（自动化版本，替代此前人工统计） ----------
#
# 六次优化排查发现：除已知的 party_name 占位符「保险机构」外，金标至少还有
# 三类系统性噪声（均为金标自身的字段边界/标签残留问题，不是抽取算法错误）：
#   1. party_name：把标签本身（「当事人:」「被处罚当事人」「受处罚机构名称:」
#      等）与住所/程序性文字一并写入了金标值。
#   2. penalty_doc_no：约 1/5 的金标在文号后面直接拼接了下一字段的标签
#      「被处罚当事人」，而不是单纯的文号。
#   3. penalty_content：约 1/6 的金标整段落把「当事人:…经查…」的完整案情
#      转储进来，而非真正的处罚决定内容（另有「见原文」占位符/空值）。
# 下面对每个字段单独计算"剔除已知噪声后"的调整版 F1，用于判断算法真实质量，
# 但不作为对外汇报的主指标（主指标必须如实反映金标现状，见模块顶部说明）。

_PARTY_LABEL_PREFIXES = [
    "被处罚单位名称", "受处罚单位名称", "被处罚人名称", "受处罚人名称",
    "被处罚当事人", "受处罚当事人", "被处罚单位", "受处罚单位",
    "当事人单位名称", "当事人名称", "当事人单位", "受处罚机构名称",
    "当事人", "名称",
]
_PARTY_PROCEDURAL_MARKERS = (
    "依据《", "行政复议", "加处罚款", "根据《", "申请行政", "强制执行", "缴款",
)


def _strip_label_prefix(value: str, prefixes: list[str]) -> str:
    for p in prefixes:
        stripped = p.replace(" ", "")
        if value.startswith(stripped + ":") or value.startswith(stripped + "："):
            return value[len(stripped) + 1:]
        if value.startswith(stripped) and len(value) > len(stripped):
            return value[len(stripped):]
    return value


def _adjusted_exact_match_f1(pairs, field_name: str) -> dict:
    tp = fp = fn = excluded = 0
    for g, e in pairs:
        pred = normalize((e or {}).get(field_name))
        truth_raw = normalize((g or {}).get(field_name))
        truth = _strip_label_prefix(truth_raw, _PARTY_LABEL_PREFIXES) if field_name == "party_name" else truth_raw

        if truth_raw == "保险机构" or (truth and any(m in truth_raw for m in _PARTY_PROCEDURAL_MARKERS)):
            excluded += 1
            continue
        if pred and truth:
            # 文号金标常见"值+下一字段标签"拼接噪声，双向前缀包含也算命中。
            if truth == pred or truth.startswith(pred) or pred.startswith(truth):
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
    return {
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "excluded_noise_rows": excluded,
    }


def _penalty_content_dump_noise(truth: str) -> bool:
    if truth in ("见原文", ""):
        return True
    return "当事人" in truth and len(truth) > 80


def _adjusted_penalty_content_f1(pairs) -> dict:
    p_sum = r_sum = f_sum = 0.0
    n = 0
    excluded = 0
    for g, e in pairs:
        pred = normalize((e or {}).get("penalty_content"))
        truth = normalize((g or {}).get("penalty_content"))
        if _penalty_content_dump_noise(truth):
            excluded += 1
            continue
        if pred and truth:
            p, r, f = _char_overlap_f1(pred, truth)
            p_sum += p
            r_sum += r
            f_sum += f
            n += 1
    return {
        "precision": round(p_sum / n, 4) if n else 0.0,
        "recall": round(r_sum / n, 4) if n else 0.0,
        "f1": round(f_sum / n, 4) if n else 0.0,
        "excluded_noise_rows": excluded,
    }


def compute_gold_noise_adjusted(extracted: list[dict], gold: list[dict]) -> dict:
    pairs = build_matched_pairs(extracted, gold)
    return {
        "party_name": _adjusted_exact_match_f1(pairs, "party_name"),
        "penalty_doc_no": _adjusted_exact_match_f1(pairs, "penalty_doc_no"),
        "penalty_content": _adjusted_penalty_content_f1(pairs),
    }


def main():
    parser = argparse.ArgumentParser(description="字段抽取评测")
    parser.add_argument("--extracted", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--output", default="data/eval/extraction_eval_report.json")
    args = parser.parse_args()

    extracted_rows = load_jsonl(args.extracted)
    gold_rows = load_jsonl(args.gold)
    metrics = compute_field_metrics(extracted_rows, gold_rows)
    metrics["gold_noise_adjusted"] = compute_gold_noise_adjusted(extracted_rows, gold_rows)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    for field_name, m in metrics.items():
        print(f"{field_name}: {m}")
    print(f"Report saved to {output}")


if __name__ == "__main__":
    main()
