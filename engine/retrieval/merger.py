"""多路候选合并去重 + RRF (Reciprocal Rank Fusion) 融合。

RRF_score(d) = Σ_i weight_i / (k + rank_i(d))
多通道命中额外加成，抑制单路噪声。
"""

from engine.retrieval.base import SearchResult

DEFAULT_CHANNEL_WEIGHTS = {
    "bm25": 1.15,
    "vector": 1.45,  # 口语↔法言法语主要靠语义
    "tag": 1.0,      # 标签收紧后恢复中等权重
    "rule": 1.2,
}


def reciprocal_rank_fusion(
    channel_results: dict[str, list[SearchResult]],
    *,
    k: int = 60,
    top_k: int = 50,
    weights: dict[str, float] | None = None,
    multi_channel_bonus: float = 0.08,
) -> list[SearchResult]:
    """融合多路召回结果，保留各通道命中记录用于生成匹配理由。"""
    weights = weights or DEFAULT_CHANNEL_WEIGHTS
    scores: dict[str, float] = {}
    case_map: dict[str, SearchResult] = {}

    for channel, results in channel_results.items():
        w = weights.get(channel, 1.0)
        for rank, result in enumerate(results, start=1):
            scores[result.case_id] = scores.get(result.case_id, 0.0) + w / (k + rank)
            if result.case_id in case_map:
                existing = case_map[result.case_id]
                existing.channels = list(dict.fromkeys(existing.channels + result.channels))
                existing.highlight_fields.update(result.highlight_fields)
                if result.match_reason and not existing.match_reason:
                    existing.match_reason = result.match_reason
            else:
                case_map[result.case_id] = result

    # 多通道共识加成（系数可经 Settings.RRF_MULTI_CHANNEL_BONUS 覆盖）
    for case_id, result in case_map.items():
        n_ch = len(result.channels or [])
        if n_ch >= 2 and multi_channel_bonus:
            scores[case_id] = scores.get(case_id, 0.0) + multi_channel_bonus * (n_ch - 1)

    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_k]

    merged = []
    for case_id in sorted_ids:
        r = case_map[case_id]
        r.score = scores[case_id]
        merged.append(r)
    return merged
