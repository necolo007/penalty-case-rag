"""asyncpg 连接池管理。pgvector 向量以 '[0.1,0.2,...]' 文本形式绑定 ::vector。"""

import logging

import asyncpg

from core.config import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_migrated: bool = False


async def create_pool() -> asyncpg.Pool:
    global _pool, _migrated
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=2, max_size=10)
        if settings.AUTO_MIGRATE and not _migrated:
            from db.automigrate import auto_migrate

            async with _pool.acquire() as conn:
                await auto_migrate(conn)
            _migrated = True
            logger.info("Database auto-migration completed")
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        return await create_pool()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def to_pgvector(embedding: list[float]) -> str:
    """list[float] → pgvector 文本字面量"""
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
