"""字段抽取评测 CLI：对比 gold_extraction_cases.jsonl 计算字段级 P/R/F1。

用法：
  python scripts/eval_extraction.py \\
    --extracted data/eval/extracted_cases.jsonl \\
    --gold data/eval/gold_extraction_cases.jsonl

  # 长字段默认 BERTScore（中文）；仅字符重叠：
  python scripts/eval_extraction.py ... --no-bert-score

评测口径修正（六次优化，对齐《最新评测结果问题.md》#1/#2）：

1. 多案例匹配：按 file_id 二分图最大权匹配后再计算 P/R/F1。
2. 长字段评分：默认对 violation_behavior / penalty_content 使用 **BERTScore F1**
   （bert-base-chinese），更贴近语义是否抽对；字符重叠 F1 仍写入
   char_overlap_* 作对照。短字段保持精确匹配。
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EVAL_FIELDS = [
    "party_name", "penalty_doc_no", "violation_behavior",
    "penalty_content", "regulator", "institution_type",
]

EXACT_MATCH_FIELDS = {"party_name", "penalty_doc_no", "regulator", "institution_type"}
OVERLAP_FIELDS = {"violation_behavior", "penalty_content"}

TRUNCATION_LEN_RATIO = 0.7
DEFAULT_BERT_MODEL = "bert-base-chinese"

_BRACKET_MAP = str.maketrans({"[": "〔", "]": "〕", "(": "（", ")": "）"})


def load_jsonl(path: str) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def normalize(value) -> str:
    """去空格 + 半角/全角括号归一。"""
    return str(value or "").replace(" ", "").strip().translate(_BRACKET_MAP)


def _norm_for_bert(value) -> str:
    """BERTScore 用：保留用字与标点，仅轻量空白/括号归一。"""
    return str(value or "").strip().translate(_BRACKET_MAP)


def _char_overlap_f1(pred: str, truth: str) -> tuple[float, float, float]:
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


def _bert_score_batch(
    candidates: list[str],
    references: list[str],
    *,
    model_type: str = DEFAULT_BERT_MODEL,
    device: str | None = None,
    batch_size: int = 32,
) -> list[tuple[float, float, float]]:
    if not candidates:
        return []
    try:
        from bert_score import score as bert_score_fn
    except ImportError as e:  # noqa: BLE001
        raise SystemExit(
            "长字段 BERTScore 需要：pip install -e \".[eval]\" "
            "（或 pip install bert-score）。也可用 --no-bert-score 回退字符重叠。"
            "若下载 bert-base-chinese 超时，可设置环境变量 "
            "HF_ENDPOINT=https://hf-mirror.com 后重试。"
        ) from e

    kwargs: dict[str, Any] = {
        "model_type": model_type,
        "lang": "zh",
        "verbose": False,
        "batch_size": batch_size,
        "rescale_with_baseline": False,
    }
    if device:
        kwargs["device"] = device

    P, R, F = bert_score_fn(candidates, references, **kwargs)
    return [
        (float(P[i].item()), float(R[i].item()), float(F[i].item()))
        for i in range(len(candidates))
    ]


def _score_long_field_pairs(
    pairs: list[tuple[dict | None, dict | None]],
    field_name: str,
    *,
    use_bert_score: bool,
    bert_model: str,
    bert_device: str | None,
    bert_batch_size: int,
) -> dict[str, Any]:
    """长字段：主指标默认 BERT-F1，并附带字符重叠对照与截断率。"""
    char_p = char_r = char_f = 0.0
    n = 0
    truncated = 0
    both_preds: list[str] = []
    both_refs: list[str] = []
    # 与 n 对齐：True 表示该条进入 BERT 批次
    bert_has_both: list[bool] = []

    for g, e in pairs:
        pred_raw = _norm_for_bert((e or {}).get(field_name))
        truth_raw = _norm_for_bert((g or {}).get(field_name))
        pred_c = normalize((e or {}).get(field_name))
        truth_c = normalize((g or {}).get(field_name))

        if pred_c and truth_c:
            p, r, f = _char_overlap_f1(pred_c, truth_c)
            char_p += p
            char_r += r
            char_f += f
            n += 1
            if _is_truncation(pred_c, truth_c):
                truncated += 1
            if use_bert_score and pred_raw and truth_raw:
                both_preds.append(pred_raw)
                both_refs.append(truth_raw)
                bert_has_both.append(True)
            elif use_bert_score:
                bert_has_both.append(False)
        elif pred_c and not truth_c:
            n += 1
            if use_bert_score:
                bert_has_both.append(False)
        elif truth_c and not pred_c:
            n += 1
            if use_bert_score:
                bert_has_both.append(False)

    char_metrics = {
        "precision": round(char_p / n, 4) if n else 0.0,
        "recall": round(char_r / n, 4) if n else 0.0,
        "f1": round(char_f / n, 4) if n else 0.0,
    }
    out: dict[str, Any] = {
        "truncation_rate": round(truncated / n, 4) if n else 0.0,
        "char_overlap_precision": char_metrics["precision"],
        "char_overlap_recall": char_metrics["recall"],
        "char_overlap_f1": char_metrics["f1"],
        "n_scored": n,
    }

    if not use_bert_score:
        out.update({
            "precision": char_metrics["precision"],
            "recall": char_metrics["recall"],
            "f1": char_metrics["f1"],
            "scoring": "char_overlap_strict",
        })
        return out

    scored = _bert_score_batch(
        both_preds,
        both_refs,
        model_type=bert_model,
        device=bert_device,
        batch_size=bert_batch_size,
    )
    bp = br = bf = 0.0
    bi = 0
    for has_both in bert_has_both:
        if has_both:
            p, r, f = scored[bi]
            bi += 1
        else:
            p = r = f = 0.0
        bp += p
        br += r
        bf += f

    out.update({
        "precision": round(bp / n, 4) if n else 0.0,
        "recall": round(br / n, 4) if n else 0.0,
        "f1": round(bf / n, 4) if n else 0.0,
        "scoring": "bertscore",
        "bert_model": bert_model,
    })
    return out


def _pair_score(pred: dict, gold: dict) -> float:
    """预测/金标相似度（匹配用，保持廉价字符重叠）。"""
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
    n, m = len(golds), len(preds)
    if n == 0:
        return [(None, p) for p in preds]
    if m == 0:
        return [(g, None) for g in golds]

    scores = [[_pair_score(preds[j], golds[i]) for j in range(m)] for i in range(n)]
    best_total = -1.0
    best_assign: list[tuple[int, int]] = []
    k = min(n, m)
    for combo in itertools.permutations(range(m), k):
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
    result: list[tuple[dict | None, dict | None]] = [
        (golds[i], preds[j]) for i, j in best_assign
    ]
    result += [(golds[i], None) for i in range(n) if i not in matched_g]
    result += [(None, preds[j]) for j in range(m) if j not in matched_p]
    return result


def build_matched_pairs(
    extracted: list[dict], gold: list[dict],
) -> list[tuple[dict | None, dict | None]]:
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


def compute_field_metrics(
    extracted: list[dict],
    gold: list[dict],
    *,
    use_bert_score: bool = True,
    bert_model: str = DEFAULT_BERT_MODEL,
    bert_device: str | None = None,
    bert_batch_size: int = 32,
) -> dict:
    pairs = build_matched_pairs(extracted, gold)
    metrics: dict = {}

    for field_name in EVAL_FIELDS:
        if field_name in OVERLAP_FIELDS:
            metrics[field_name] = _score_long_field_pairs(
                pairs,
                field_name,
                use_bert_score=use_bert_score,
                bert_model=bert_model,
                bert_device=bert_device,
                bert_batch_size=bert_batch_size,
            )
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

    correct = total = 0
    for g, e in pairs:
        if g is not None and e is not None and "is_insurance_related" in g:
            total += 1
            if bool(e.get("is_insurance_related")) == bool(g["is_insurance_related"]):
                correct += 1
    metrics["insurance_classification_accuracy"] = (
        round(correct / total, 4) if total else None
    )

    unmatched_gold = sum(1 for g, e in pairs if g is not None and e is None)
    unmatched_pred = sum(1 for g, e in pairs if g is None and e is not None)
    metrics["case_matching"] = {
        "gold_cases": sum(1 for g, _ in pairs if g is not None),
        "pred_cases": sum(1 for _, e in pairs if e is not None),
        "matched_pairs": sum(1 for g, e in pairs if g is not None and e is not None),
        "unmatched_gold_fn_cases": unmatched_gold,
        "unmatched_pred_fp_cases": unmatched_pred,
    }

    macro_f1 = sum(
        m["f1"] for f, m in metrics.items() if isinstance(m, dict) and "f1" in m
    ) / len(EVAL_FIELDS)
    metrics["macro_f1"] = round(macro_f1, 4)
    return metrics


# ---------- 金标噪声诊断 ----------

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
        truth = (
            _strip_label_prefix(truth_raw, _PARTY_LABEL_PREFIXES)
            if field_name == "party_name"
            else truth_raw
        )

        if truth_raw == "保险机构" or (
            truth and any(m in truth_raw for m in _PARTY_PROCEDURAL_MARKERS)
        ):
            excluded += 1
            continue
        if pred and truth:
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
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "excluded_noise_rows": excluded,
    }


def _penalty_content_dump_noise(truth: str) -> bool:
    if truth in ("见原文", ""):
        return True
    return "当事人" in truth and len(truth) > 80


def _adjusted_penalty_content_f1(
    pairs,
    *,
    use_bert_score: bool = False,
    bert_model: str = DEFAULT_BERT_MODEL,
    bert_device: str | None = None,
    bert_batch_size: int = 32,
) -> dict:
    """噪声调整版：默认仍用字符重叠；若开启 BERT 则对非噪声对改用 BERT-F1。"""
    filtered: list[tuple[dict | None, dict | None]] = []
    excluded = 0
    for g, e in pairs:
        truth = normalize((g or {}).get("penalty_content"))
        if _penalty_content_dump_noise(truth):
            excluded += 1
            continue
        filtered.append((g, e))

    scored = _score_long_field_pairs(
        filtered,
        "penalty_content",
        use_bert_score=use_bert_score,
        bert_model=bert_model,
        bert_device=bert_device,
        bert_batch_size=bert_batch_size,
    )
    scored["excluded_noise_rows"] = excluded
    return scored


def compute_gold_noise_adjusted(
    extracted: list[dict],
    gold: list[dict],
    *,
    use_bert_score: bool = True,
    bert_model: str = DEFAULT_BERT_MODEL,
    bert_device: str | None = None,
    bert_batch_size: int = 32,
) -> dict:
    pairs = build_matched_pairs(extracted, gold)
    return {
        "party_name": _adjusted_exact_match_f1(pairs, "party_name"),
        "penalty_doc_no": _adjusted_exact_match_f1(pairs, "penalty_doc_no"),
        "penalty_content": _adjusted_penalty_content_f1(
            pairs,
            use_bert_score=use_bert_score,
            bert_model=bert_model,
            bert_device=bert_device,
            bert_batch_size=bert_batch_size,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="字段抽取评测")
    parser.add_argument("--extracted", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--output", default="data/eval/extraction_eval_report.json")
    parser.add_argument(
        "--no-bert-score",
        action="store_true",
        help="长字段回退为字符重叠 F1（默认启用 BERTScore）",
    )
    parser.add_argument(
        "--bert-model",
        default=DEFAULT_BERT_MODEL,
        help=f"BERTScore 模型（默认 {DEFAULT_BERT_MODEL}）",
    )
    parser.add_argument("--bert-device", default=None, help="cpu / cuda，默认自动")
    parser.add_argument("--bert-batch-size", type=int, default=32)
    args = parser.parse_args()

    use_bert = not args.no_bert_score
    extracted_rows = load_jsonl(args.extracted)
    gold_rows = load_jsonl(args.gold)
    metrics = compute_field_metrics(
        extracted_rows,
        gold_rows,
        use_bert_score=use_bert,
        bert_model=args.bert_model,
        bert_device=args.bert_device,
        bert_batch_size=args.bert_batch_size,
    )
    metrics["gold_noise_adjusted"] = compute_gold_noise_adjusted(
        extracted_rows,
        gold_rows,
        use_bert_score=use_bert,
        bert_model=args.bert_model,
        bert_device=args.bert_device,
        bert_batch_size=args.bert_batch_size,
    )
    metrics["long_field_scoring"] = "bertscore" if use_bert else "char_overlap_strict"

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    for field_name, m in metrics.items():
        print(f"{field_name}: {m}")
    print(f"Report saved to {output}")


if __name__ == "__main__":
    main()
