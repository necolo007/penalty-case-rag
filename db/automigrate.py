"""启动时自动建库（GORM AutoMigrate 风格，幂等可重复执行）。

API / Worker 首次连接 PostgreSQL 时自动执行 db/migrations/00N_*.sql：
  - 001 schema、003 去重/发号 等 DDL 每次幂等执行
  - 002 主种子仅空库写入；004 扩展词典每次幂等追加

无需手动 run scripts/setup_db.py；该脚本保留为可选调试入口。
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

from core.config import get_settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _sorted_sql(pattern: str) -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob(pattern))


async def _has_zhparser_extension(conn: asyncpg.Connection) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'zhparser')"
    )


async def _ts_config_parser(conn: asyncpg.Connection, cfgname: str) -> str | None:
    return await conn.fetchval(
        """
        SELECT p.prsname
        FROM pg_ts_config c
        JOIN pg_ts_parser p ON c.cfgparser = p.oid
        WHERE c.cfgname = $1
        """,
        cfgname,
    )


async def _create_zhparser_config(conn: asyncpg.Connection) -> None:
    await conn.execute("CREATE EXTENSION IF NOT EXISTS zhparser;")
    await conn.execute(
        """
        CREATE TEXT SEARCH CONFIGURATION zhparser_config (PARSER = zhparser);
        ALTER TEXT SEARCH CONFIGURATION zhparser_config
            ADD MAPPING FOR n,v,a,i,e,l WITH SIMPLE;
        """
    )
    logger.info("Text search config: zhparser_config (zhparser)")


async def _recreate_search_trigger(conn: asyncpg.Connection) -> None:
    """切换分词配置后重建触发器，并刷新已有案例 search_vector。"""
    await conn.execute(
        """
        CREATE OR REPLACE FUNCTION cases_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                to_tsvector('zhparser_config',
                    coalesce(NEW.violation_behavior, '') || ' ' ||
                    coalesce(NEW.penalty_content, '') || ' ' ||
                    coalesce(NEW.party_name, '') || ' ' ||
                    coalesce(NEW.case_summary, '') || ' ' ||
                    coalesce(array_to_string(NEW.risk_tags, ' '), ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS trg_cases_search_vector ON penalty_cases;
        CREATE TRIGGER trg_cases_search_vector
            BEFORE INSERT OR UPDATE OF violation_behavior, penalty_content, party_name,
                                       case_summary, risk_tags
            ON penalty_cases
            FOR EACH ROW EXECUTE FUNCTION cases_search_vector_update();
        """
    )
    has_cases = await conn.fetchval("SELECT to_regclass('public.penalty_cases') IS NOT NULL")
    if has_cases:
        await conn.execute("UPDATE penalty_cases SET violation_behavior = violation_behavior")


async def _ensure_text_search_config(conn: asyncpg.Connection) -> None:
    """创建 zhparser_config；有 zhparser 用中文分词，否则按 REQUIRE_ZHPARSER 决定降级或失败。"""
    settings = get_settings()
    has_zhparser = await _has_zhparser_extension(conn)
    parser = await _ts_config_parser(conn, "zhparser_config")

    if has_zhparser:
        if parser == "zhparser":
            await conn.execute("CREATE EXTENSION IF NOT EXISTS zhparser;")
            return

        if parser is not None:
            logger.info("Upgrading zhparser_config from %s to zhparser", parser)
            await conn.execute("DROP TEXT SEARCH CONFIGURATION IF EXISTS zhparser_config CASCADE;")

        await _create_zhparser_config(conn)
        await _recreate_search_trigger(conn)
        return

    if settings.REQUIRE_ZHPARSER:
        raise RuntimeError(
            "REQUIRE_ZHPARSER=true but extension zhparser is not available. "
            "Default bge_m3 does not need zhparser; set REQUIRE_ZHPARSER=false "
            "or use a Postgres image that includes zhparser."
        )

    if parser is not None:
        return

    await conn.execute(
        "CREATE TEXT SEARCH CONFIGURATION zhparser_config (COPY = pg_catalog.simple);"
    )
    logger.warning(
        "zhparser not available; legacy BM25 falls back to simple. "
        "Default bge_m3 retrieval does not depend on zhparser."
    )


async def auto_migrate(conn: asyncpg.Connection) -> None:
    """对单连接执行 schema + 条件种子。可安全重复调用。"""
    await _ensure_text_search_config(conn)

    for path in _sorted_sql("[0-9][0-9][0-9]_*.sql"):
        name = path.name
        # 002 主种子：仅空库写入；004 等扩展种子每次幂等追加
        if name.startswith("002_"):
            if not await _needs_seed(conn):
                logger.debug("AutoMigrate: seed data present, skip %s", name)
                continue
        logger.info("AutoMigrate: applying %s", name)
        await conn.execute(path.read_text(encoding="utf-8"))

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
