"""匹配理由生成：模板化组装（不走 LLM，保证检索延迟可控）。

对齐训练样本文风：指出待审语句与案例违规行为的近似点 + 标签 + 通道。
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
        prefix = result.match_reason + "；"
    else:
        prefix = ""

    behavior = result.violation_behavior or ""
    if len(behavior) > 80:
        behavior = behavior[:80] + "…"

    channels = "、".join(_CHANNEL_LABELS.get(c, c) for c in result.channels)
    tags = "、".join(result.risk_tags[:3]) if result.risk_tags else ""

    # 抽取查询侧短线索（前 24 字）便于人工复核
    clue = (query_text or rewritten_query or "").strip().replace("\n", "")
    if len(clue) > 24:
        clue = clue[:24] + "…"

    parts = [
        f"{prefix}查询表述「{clue}」与案例{result.case_id}违法行为「{behavior}」高度近似",
    ]
    if tags:
        parts.append(f"同属风险类型「{tags}」")
    if channels:
        parts.append(f"经{channels}通道命中")
    return "，".join(parts) + "。"
