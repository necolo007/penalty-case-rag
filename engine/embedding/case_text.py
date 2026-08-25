"""案例嵌入文本：违规行为 + 案件总结。"""

from __future__ import annotations

EMBED_VB_PREFIX = "违规行为："
EMBED_SUMMARY_PREFIX = "案件总结："
EMBED_EMPTY_FALLBACK = "保险监管处罚案例"


def build_case_embed_text(
    *,
    violation_behavior: str | None = None,
    case_summary: str | None = None,
    max_chars: int = 2000,
) -> str:
    """生成用于 BGE-M3 dense/sparse 的案例文档文本。"""
    vb = (violation_behavior or "").strip()
    summary = (case_summary or "").strip()

    parts: list[str] = []
    if vb:
        parts.append(f"{EMBED_VB_PREFIX}{vb}")
    if summary and summary != vb:
        parts.append(f"{EMBED_SUMMARY_PREFIX}{summary}")

    text = "\n".join(parts).strip()
    if not text:
        return EMBED_EMPTY_FALLBACK
    return text[:max_chars]
