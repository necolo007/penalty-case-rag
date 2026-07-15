"""稳健发号：基于 id_sequences 表的原子递增。

官方金标使用 C001 / F000289 等不规则编号；自增路径从 MAX 数字水位续号，
避免与导入金标撞号。
"""

from __future__ import annotations

import re


async def _ensure_seq_at_least(pool, name: str, floor: int) -> None:
    await pool.execute(
        """
        INSERT INTO id_sequences (name, value) VALUES ($1, $2)
        ON CONFLICT (name) DO UPDATE SET value = GREATEST(id_sequences.value, EXCLUDED.value)
        """,
        name, floor,
    )


async def next_file_id(pool) -> str:
    """返回下一个 F######；水位取现有 documents 最大数字部分。"""
    row = await pool.fetchrow(
        """
        SELECT COALESCE(MAX(CAST(SUBSTRING(file_id FROM 2) AS BIGINT)), 0) AS m
        FROM documents
        WHERE file_id ~ '^F[0-9]+$'
        """
    )
    floor = int(row["m"] or 0)
    await _ensure_seq_at_least(pool, "file_id", floor)
    n = await pool.fetchval(
        """
        UPDATE id_sequences SET value = value + 1
        WHERE name = 'file_id' RETURNING value
        """
    )
    return f"F{int(n):06d}"


async def next_case_id(pool) -> str:
    """返回下一个 C######（6 位），避开已有 C001 这类短编号的数字冲突。

    策略：只扫描 6 位及以上数字的 case_id 作水位；若官方用 C001–C500，
    自增从 C000501 起亦可——更稳妥是取所有数字后缀的全局 MAX。
    """
    rows = await pool.fetch(
        "SELECT case_id FROM penalty_cases WHERE case_id ~ '^C[0-9]+$'"
    )
    max_n = 0
    for r in rows:
        m = re.match(r"^C(\d+)$", r["case_id"])
        if m:
            max_n = max(max_n, int(m.group(1)))
    await _ensure_seq_at_least(pool, "case_id", max_n)
    n = await pool.fetchval(
        """
        UPDATE id_sequences SET value = value + 1
        WHERE name = 'case_id' RETURNING value
        """
    )
    # 官方金标约到 C500；自增统一 6 位便于区分新增
    return f"C{int(n):06d}"
