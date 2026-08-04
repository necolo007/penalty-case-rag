"""匹配理由生成：基于真实重叠证据组装（不走 LLM，保证检索延迟可控）。

禁止输出「行为目的一致 / 业务场景一致 / 高度近似」等万能模板话术；
优先给出可核对的重叠词、共有风险标签、处罚结果摘要与召回通道事实。
"""

from __future__ import annotations

import re

from engine.retrieval.base import SearchResult

_CHANNEL_LABELS = {
    "bm25": "关键词",
    "vector": "语义",
    "tag": "风险标签",
    "rule": "规则词典",
}

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,8}|[A-Za-z0-9]{2,}")


def _tokens(text: str, limit: int = 40) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in _TOKEN_RE.findall(text or ""):
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= limit:
            break
    return out


def _overlap_terms(query: str, case_text: str, max_terms: int = 4) -> list[str]:
    q = set(_tokens(query))
    if not q:
        return []
    hits: list[str] = []
    for t in _tokens(case_text, limit=80):
        if t in q and t not in hits:
            hits.append(t)
        if len(hits) >= max_terms:
            break
    return hits


def build_match_reason(query_text: str, rewritten_query: str, result: SearchResult) -> str:
    """生成可解释命中理由：重叠证据 + 标签 + 处罚结果 + 通道（无套话）。"""
    parts: list[str] = []

    # 规则通道自带的词典命中前缀保留（已是具体事实）
    if result.match_reason and result.match_reason.startswith("命中规则词典"):
        parts.append(result.match_reason.rstrip("；;。"))

    query = (query_text or rewritten_query or "").strip()
    behavior = (result.violation_behavior or "").strip()
    penalty = (result.penalty_content or "").strip()
    corpus = f"{behavior} {penalty}"

    overlaps = _overlap_terms(query, corpus)
    if overlaps:
        parts.append(f"共同线索：{'、'.join(overlaps)}")
    elif behavior:
        short = behavior if len(behavior) <= 48 else behavior[:48] + "…"
        parts.append(f"对照违法事实：{short}")

    if result.risk_tags:
        parts.append(f"共有风险标签：{'、'.join(result.risk_tags[:3])}")

    if penalty:
        short_p = penalty if len(penalty) <= 36 else penalty[:36] + "…"
        parts.append(f"处罚结果：{short_p}")
    elif result.penalty_doc_no:
        parts.append(f"处罚文号：{result.penalty_doc_no}")

    if result.channels:
        ch = "、".join(_CHANNEL_LABELS.get(c, c) for c in result.channels[:3])
        parts.append(f"召回通道：{ch}")

    if not parts:
        return f"案例 {result.case_id} 进入候选集（相关分 {result.score:.3f}）。"

    return "；".join(parts) + "。"
