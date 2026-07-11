"""启动时自动建库（GORM AutoMigrate 风格，幂等可重复执行）。

API / Worker 首次连接 PostgreSQL 时自动执行：
  1. db/migrations/001_*.sql — 扩展、表、索引、触发器
  2. db/migrations/002_*.sql — 种子数据（仅库为空时写入）

无需手动运行 scripts/setup_db.py；该脚本保留为可选调试入口。
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _sorted_sql(pattern: str) -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob(pattern))


async def auto_migrate(conn: asyncpg.Connection) -> None:
    """对单连接执行 schema + 条件种子。可安全重复调用。"""
    for path in _sorted_sql("001_*.sql"):
        logger.info("AutoMigrate: applying schema %s", path.name)
        await conn.execute(path.read_text(encoding="utf-8"))

    if await _needs_seed(conn):
        for path in _sorted_sql("002_*.sql"):
            logger.info("AutoMigrate: applying seed %s", path.name)
            await conn.execute(path.read_text(encoding="utf-8"))
    else:
        logger.debug("AutoMigrate: seed data present, skip")

    logger.info("AutoMigrate: schema ready")


async def _needs_seed(conn: asyncpg.Connection) -> bool:
    """risk_type_dict 已有 R001 则视为已种子化。"""
    exists = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'risk_type_dict'
        )
        """
    )
    if not exists:
        return True
    return not await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM risk_type_dict WHERE risk_type_id = 'R001')"
    )
