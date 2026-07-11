"""匹配理由生成：模板化组装（不走 LLM，保证检索延迟可控）。

理由结构：查询要素 + 案例违法行为引用 + 命中通道说明。
"""

from engine.retrieval.base import SearchResult

_CHANNEL_LABELS = {
    "bm25": "关键词匹配",
    "vector": "语义相似",
    "tag": "同类风险标签",
    "rule": "规则词典映射",
}


def build_match_reason(query_text: str, rewritten_query: str, result: SearchResult) -> str:
    if result.match_reason:
        # 规则召回已生成词典命中理由，前置保留
        prefix = result.match_reason + "；"
    else:
        prefix = ""

    behavior = result.violation_behavior
    if len(behavior) > 60:
        behavior = behavior[:60] + "…"

    channels = "、".join(_CHANNEL_LABELS.get(c, c) for c in result.channels)
    tags = "、".join(result.risk_tags[:3]) if result.risk_tags else ""

    parts = [f"{prefix}该案例违法行为为「{behavior}」"]
    if tags:
        parts.append(f"风险标签：{tags}")
    parts.append(f"与待审语句经{channels}通道判定相似")
    return "，".join(parts) + "。"
