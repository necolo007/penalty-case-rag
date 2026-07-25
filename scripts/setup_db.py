"""手动触发数据库 AutoMigrate。

用法：python scripts/setup_db.py
"""

import asyncio

import asyncpg

from core.config import get_settings
from db.automigrate import auto_migrate


async def main():
    settings = get_settings()
    conn = await asyncpg.connect(settings.DATABASE_URL)
    try:
        await auto_migrate(conn)
        print("AutoMigrate done")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
