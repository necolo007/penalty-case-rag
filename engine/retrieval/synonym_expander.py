"""同义词扩展：基于 synonym_dictionary 的确定性改写（LLM 降级方案 / 查询扩展）。"""

import asyncpg


class SynonymExpander:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def expand(self, query_text: str) -> str:
        """返回 query 中命中词条对应的标准表述拼接；无命中返回空串。"""
        rows = await self.pool.fetch(
            """
            SELECT DISTINCT standard_term
            FROM synonym_dictionary
            WHERE $1 LIKE '%' || business_term || '%'
            ORDER BY standard_term
            LIMIT 10
            """,
            query_text,
        )
        if not rows:
            return ""
        terms = " ".join(r["standard_term"] for r in rows)
        return f"{query_text} {terms}"
