"""BM25 关键词召回：PostgreSQL tsvector + zhparser。

解决：精确匹配法言法语、文号、机构名。
"""

import asyncpg

from engine.retrieval.base import BaseRetriever, SearchQuery, SearchResult, row_to_result
from engine.retrieval.filters import CASE_FROM, CASE_SELECT_FIELDS, build_filters


class BM25Retriever(BaseRetriever):
    channel = "bm25"

    def __init__(self, pool: asyncpg.Pool, recall_size: int = 80):
        self.pool = pool
        self.recall_size = recall_size

    async def retrieve(self, query: SearchQuery, *, search_text: str | None = None, **_) -> list[SearchResult]:
        """search_text 为改写后文本，缺省用原始 query"""
        text = search_text or query.query_text
        params: list = [text]
        filter_sql = build_filters(query, params)
        params.append(self.recall_size)

        sql = f"""
            SELECT {CASE_SELECT_FIELDS},
                ts_rank(c.search_vector, plainto_tsquery('zhparser_config', $1)) AS score,
                ts_headline(
                    'zhparser_config', c.violation_behavior,
                    plainto_tsquery('zhparser_config', $1),
                    'MaxWords=50, MinWords=20, StartSel=<mark>, StopSel=</mark>'
                ) AS violation_highlight
            FROM {CASE_FROM}
            WHERE c.is_insurance_related = TRUE
              AND c.search_vector @@ plainto_tsquery('zhparser_config', $1)
              {filter_sql}
            ORDER BY score DESC
            LIMIT ${len(params)}
        """
        rows = await self.pool.fetch(sql, *params)

        results = []
        for row in rows:
            r = row_to_result(row, float(row["score"]), self.channel)
            r.highlight_fields["violation_behavior"] = row["violation_highlight"] or ""
            results.append(r)
        return results
