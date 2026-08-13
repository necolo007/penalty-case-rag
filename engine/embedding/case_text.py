"""案例侧嵌入文本构造。

参赛优化：用「违规行为 + 案件总结」结构化拼接，避免 raw_text 通用套话稀释语义。
入库 / reindex / 人工确认补嵌共用本函数，保证 query-doc 编码一致。
"""

from __future__ import annotations


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
        parts.append(f"违规行为：{vb}")
    if summary and summary != vb:
        parts.append(f"案件总结：{summary}")

    text = "\n".join(parts).strip()
    if not text:
        return "保险监管处罚案例"
    return text[:max_chars]
