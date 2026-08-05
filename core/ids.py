"""稳健发号：基于 id_sequences 表的原子递增。

官方金标使用 C001 / F000289 等不规则编号；自增路径从 MAX 数字水位续号，
避免与导入金标撞号（例如金标 C000503 与自增 C000503）。
"""

from __future__ import annotations

# 进程内互斥用的 advisory lock key（与具体 DB 对象无关，稳定即可）
_CASE_ID_LOCK = 874_203_501
_FILE_ID_LOCK = 874_203_502


async def sync_id_sequences(pool) -> dict[str, int]:
    """将 id_sequences 水位抬到表内数字后缀 MAX（幂等，启动时调用）。"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            file_v = await conn.fetchval(
                """
                INSERT INTO id_sequences (name, value)
                SELECT 'file_id',
                       COALESCE((
                           SELECT MAX(CAST(SUBSTRING(file_id FROM 2) AS BIGINT))
                           FROM documents WHERE file_id ~ '^F[0-9]+$'
                       ), 0)
                ON CONFLICT (name) DO UPDATE
                SET value = GREATEST(
                    id_sequences.value,
                    EXCLUDED.value
                )
                RETURNING value
                """
            )
            case_v = await conn.fetchval(
                """
                INSERT INTO id_sequences (name, value)
                SELECT 'case_id',
                       COALESCE((
                           SELECT MAX(CAST(SUBSTRING(case_id FROM 2) AS BIGINT))
                           FROM penalty_cases WHERE case_id ~ '^C[0-9]+$'
                       ), 0)
                ON CONFLICT (name) DO UPDATE
                SET value = GREATEST(
                    id_sequences.value,
                    EXCLUDED.value
                )
                RETURNING value
                """
            )
    return {"file_id": int(file_v or 0), "case_id": int(case_v or 0)}


async def next_file_id(pool) -> str:
    """返回下一个 F######；水位取现有 documents 最大数字部分。"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _FILE_ID_LOCK)
            n = await conn.fetchval(
                """
                WITH table_max AS (
                    SELECT COALESCE(MAX(CAST(SUBSTRING(file_id FROM 2) AS BIGINT)), 0) AS m
                    FROM documents
                    WHERE file_id ~ '^F[0-9]+$'
                )
                INSERT INTO id_sequences (name, value)
                SELECT 'file_id', m + 1 FROM table_max
                ON CONFLICT (name) DO UPDATE
                SET value = GREATEST(id_sequences.value, (SELECT m FROM table_max)) + 1
                RETURNING value
                """
            )
    if n is None:
        raise RuntimeError("failed to allocate file_id from id_sequences")
    return f"F{int(n):06d}"


async def next_case_id(pool) -> str:
    """返回下一个 C######（6 位），避开已有 C001 / C000503 等数字冲突。

    在同一事务内：advisory lock → 对齐表 MAX → 序列 +1。
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _CASE_ID_LOCK)
            n = await conn.fetchval(
                """
                WITH table_max AS (
                    SELECT COALESCE(MAX(CAST(SUBSTRING(case_id FROM 2) AS BIGINT)), 0) AS m
                    FROM penalty_cases
                    WHERE case_id ~ '^C[0-9]+$'
                )
                INSERT INTO id_sequences (name, value)
                SELECT 'case_id', m + 1 FROM table_max
                ON CONFLICT (name) DO UPDATE
                SET value = GREATEST(id_sequences.value, (SELECT m FROM table_max)) + 1
                RETURNING value
                """
            )
    if n is None:
        raise RuntimeError("failed to allocate case_id from id_sequences")
    return f"C{int(n):06d}"


async def allocate_unique_case_id(pool, *, max_attempts: int = 32) -> str:
    """发号并在 advisory lock 下跳过已占用编号，杜绝 TOCTOU 撞号。"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _CASE_ID_LOCK)
            last: str | None = None
            for _ in range(max_attempts):
                n = await conn.fetchval(
                    """
                    WITH table_max AS (
                        SELECT COALESCE(
                            MAX(CAST(SUBSTRING(case_id FROM 2) AS BIGINT)), 0
                        ) AS m
                        FROM penalty_cases
                        WHERE case_id ~ '^C[0-9]+$'
                    )
                    INSERT INTO id_sequences (name, value)
                    SELECT 'case_id', m + 1 FROM table_max
                    ON CONFLICT (name) DO UPDATE
                    SET value = GREATEST(
                        id_sequences.value, (SELECT m FROM table_max)
                    ) + 1
                    RETURNING value
                    """
                )
                if n is None:
                    raise RuntimeError("failed to allocate case_id from id_sequences")
                case_id = f"C{int(n):06d}"
                last = case_id
                exists = await conn.fetchval(
                    "SELECT 1 FROM penalty_cases WHERE case_id = $1",
                    case_id,
                )
                if not exists:
                    return case_id
            raise RuntimeError(
                f"unable to allocate unique case_id after retries (last={last})"
            )
