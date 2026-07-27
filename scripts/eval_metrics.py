"""检索评测指标：Recall@K / MRR / NDCG@K / Top-1 命中率。

gold 格式（对齐 retrieval_train_queries / test_gold_labels）：
  {"question_id": "...", "relevant_cases": [{"case_id": "C001", "relevance": "strong"}]}
submission 格式：
  {"question_id": "...", "retrieved_cases": [{"case_id": "C001", "rank": 1}]}
"""

import math

RELEVANCE_GAIN = {"strong": 2.0, "medium": 1.0, "weak": 0.5}


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


def compute_retrieval_metrics(submission: list[dict], gold: list[dict],
                              k_values: list[int] | None = None) -> dict:
    k_values = k_values or [5, 10]
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

    if not per_query:
        return {"evaluated": 0}

    n = len(per_query)
    summary: dict = {"evaluated": n}
    metric_keys = [k for k in per_query[0] if k != "question_id"]
    for key in metric_keys:
        summary[key] = round(sum(r[key] for r in per_query) / n, 4)
    summary["per_query"] = per_query
    return summary
