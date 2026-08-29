"""检索评测指标：Recall@K / MRR / NDCG@K / Top-1 命中率。

gold 格式（对齐 retrieval_train_queries / test_gold_labels）：
  {"question_id": "...", "relevant_cases": [{"case_id": "C001", "relevance": "strong"}]}
submission 格式：
  {"question_id": "...", "retrieved_cases": [{"case_id": "C001", "rank": 1}]}
"""

import math

RELEVANCE_GAIN = {"strong": 2.0, "medium": 1.0, "weak": 0.5}

DEFAULT_K_VALUES = [3, 5, 10]


def _gold_map(gold: list[dict]) -> dict[str, dict[str, float]]:
    result = {}
    for item in gold:
        qid = item.get("question_id") or item.get("query_id")
        # 兼容扁平格式与官方 test_gold_labels 的 gold_answer 嵌套
        payload = item.get("gold_answer") if isinstance(item.get("gold_answer"), dict) else item
        cases = {}
        for c in payload.get("relevant_cases", []):
            cases[c["case_id"]] = RELEVANCE_GAIN.get(c.get("relevance", "medium"), 1.0)
        result[qid] = cases
    return result


def _ranked_ids(entry: dict) -> list[str]:
    cases = sorted(entry.get("retrieved_cases", []), key=lambda c: c.get("rank", 999))
    return [c["case_id"] for c in cases]


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def mrr(ranked: list[str], relevant: set[str]) -> float:
    for i, cid in enumerate(ranked, start=1):
        if cid in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[str], gains: dict[str, float], k: int) -> float:
    dcg = sum(
        gains.get(cid, 0.0) / math.log2(i + 1)
        for i, cid in enumerate(ranked[:k], start=1)
    )
    ideal = sorted(gains.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 1) for i, g in enumerate(ideal, start=1))
    return dcg / idcg if idcg > 0 else 0.0


def _aggregate_metric_rows(per_query: list[dict], k_values: list[int]) -> dict:
    if not per_query:
        return {"evaluated": 0, "k_values": k_values}
    n = len(per_query)
    summary: dict = {
        "evaluated": n,
        "k_values": k_values,
        "mrr": round(sum(r["mrr"] for r in per_query) / n, 4),
        "top1_hit": round(sum(r["top1_hit"] for r in per_query) / n, 4),
    }
    for k in k_values:
        summary[f"recall@{k}"] = round(
            sum(r[f"recall@{k}"] for r in per_query) / n, 4
        )
        summary[f"ndcg@{k}"] = round(
            sum(r[f"ndcg@{k}"] for r in per_query) / n, 4
        )
    summary["per_query"] = per_query
    return summary


def _metric_row_from_ranked(
    qid: str,
    ranked: list[str],
    gains: dict[str, float],
    k_values: list[int],
) -> dict:
    relevant = {cid for cid, g in gains.items() if g > 0}
    row: dict = {
        "question_id": qid,
        "mrr": mrr(ranked, relevant),
        "top1_hit": 1.0 if ranked and ranked[0] in relevant else 0.0,
        "judge_relevant_count": len(relevant),
    }
    for k in k_values:
        row[f"recall@{k}"] = recall_at_k(ranked, relevant, k)
        row[f"ndcg@{k}"] = ndcg_at_k(ranked, gains, k)
    return row


def judge_scores_to_gains(judgements: list[dict], *, graded: bool = False) -> dict[str, float]:
    """将 Judge 输出转为 gains。graded=False 时 score≥1 视为相关(gain=1)。"""
    gains: dict[str, float] = {}
    for j in judgements:
        cid = str(j.get("case_id") or "").strip()
        if not cid:
            continue
        try:
            score = int(j.get("score"))
        except (TypeError, ValueError):
            score = 0
        if graded:
            gains[cid] = float(max(0, min(2, score)))
        else:
            gains[cid] = 1.0 if score >= 1 else 0.0
    return gains


def compute_judge_retrieval_metrics(
    per_query_judge: list[dict],
    k_values: list[int] | None = None,
    *,
    graded_ndcg: bool = False,
) -> dict:
    """从 LLM-as-Judge 逐案结果计算与金标口径一致的检索指标。

    per_query 每项需含 question_id 与 judgements（按检索顺序，含 case_id/score）。
    相关集合仅来自已 Judge 的 Top-M 召回；Recall@K 表示「Judge 判为相关的案例
    在 Top-K 中的覆盖率」，不是全库 recall。
    """
    k_values = sorted(set(k_values or DEFAULT_K_VALUES))
    rows: list[dict] = []
    for item in per_query_judge:
        qid = item.get("question_id") or item.get("query_id") or ""
        judgements = item.get("judgements") or []
        ranked = [str(j.get("case_id") or "").strip() for j in judgements]
        ranked = [c for c in ranked if c]
        gains = judge_scores_to_gains(judgements, graded=graded_ndcg)
        rows.append(_metric_row_from_ranked(qid, ranked, gains, k_values))
    return _aggregate_metric_rows(rows, k_values)


def compute_retrieval_metrics(
    submission: list[dict],
    gold: list[dict],
    k_values: list[int] | None = None,
) -> dict:
    k_values = sorted(set(k_values or DEFAULT_K_VALUES))
    gold_map = _gold_map(gold)

    per_query = []
    for entry in submission:
        qid = entry.get("question_id") or entry.get("query_id")
        if qid not in gold_map:
            continue
        gains = gold_map[qid]
        relevant = set(gains.keys())
        ranked = _ranked_ids(entry)

        row = {
            "question_id": qid,
            "mrr": mrr(ranked, relevant),
            "top1_hit": 1.0 if ranked and ranked[0] in relevant else 0.0,
        }
        for k in k_values:
            row[f"recall@{k}"] = recall_at_k(ranked, relevant, k)
            row[f"ndcg@{k}"] = ndcg_at_k(ranked, gains, k)
        per_query.append(row)

    return _aggregate_metric_rows(per_query, k_values)


def _harmonic_mean(a: float, b: float) -> float:
    if a + b <= 0:
        return 0.0
    return 2 * a * b / (a + b)


def _case_label_judge_row(
    case_id: str,
    pred_judgements: list[dict],
    gold_coverage: list[dict],
) -> dict:
    pred_scores = [int(j.get("score") or 0) for j in pred_judgements]
    gold_scores = [int(j.get("score") or 0) for j in gold_coverage]
    pred_precision = (
        sum(pred_scores) / len(pred_scores) if pred_scores else (1.0 if not gold_scores else 0.0)
    )
    gold_recall = (
        sum(gold_scores) / len(gold_scores) if gold_scores else (1.0 if not pred_scores else 0.0)
    )
    case_f1 = _harmonic_mean(pred_precision, gold_recall)
    full_accept = (
        bool(pred_scores)
        and bool(gold_scores)
        and all(s == 1 for s in pred_scores)
        and all(s == 1 for s in gold_scores)
    ) or (not pred_scores and not gold_scores)
    return {
        "case_id": case_id,
        "pred_tag_count": len(pred_scores),
        "gold_tag_count": len(gold_scores),
        "judge_pred_precision": round(pred_precision, 4),
        "judge_gold_recall": round(gold_recall, 4),
        "judge_f1": round(case_f1, 4),
        "judge_full_accept": full_accept,
        "pred_judgements": pred_judgements,
        "gold_coverage": gold_coverage,
    }


def compute_label_judge_metrics(per_case: list[dict]) -> dict:
    """从 LLM-as-Judge 逐案标签评审汇总任务五消融指标。"""
    if not per_case:
        return {"evaluated": 0, "scoring_mode": "label_judge_binary"}
    n = len(per_case)
    pred_prec = sum(c["judge_pred_precision"] for c in per_case) / n
    gold_rec = sum(c["judge_gold_recall"] for c in per_case) / n
    macro_f1 = sum(c["judge_f1"] for c in per_case) / n
    full_accept = sum(1 for c in per_case if c["judge_full_accept"]) / n
    return {
        "evaluated": n,
        "scoring_mode": "label_judge_binary",
        "judge_pred_precision": round(pred_prec, 4),
        "judge_gold_recall": round(gold_rec, 4),
        "judge_f1": round(macro_f1, 4),
        "judge_full_accept_rate": round(full_accept, 4),
        "metrics_note": (
            "pred_precision=预测标签被 Judge 判合理的比例；"
            "gold_recall=金标标签被 Judge 判已覆盖的比例；"
            "full_accept=两侧全部标签均判 1"
        ),
        "per_case": per_case,
    }
