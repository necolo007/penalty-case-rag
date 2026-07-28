"""BM25 关键词召回：PostgreSQL tsvector + zhparser。

解决：精确匹配法言法语、文号、机构名。

Bug 修复（诊断发现该通道此前 train/test 均 100% 空召回）：
`plainto_tsquery` 会把切分出的所有词用 `&`（AND）连接，要求文档同时包含全部词项。
真实查询多为几十字的营销话术长句，切出 20~40 个词后 AND 语义几乎不可能被任何正式
处罚决定书文档同时命中，导致该通道形同虚设。现改为「先 AND 精确匹配，命中数为 0
再退化为 OR（词命中越多分数越高，由 ts_rank 自然排序）」，兼顾短查询的精确性与
长查询的召回率。
"""

import asyncpg

from engine.retrieval.base import BaseRetriever, SearchQuery, SearchResult, row_to_result
from engine.retrieval.filters import CASE_FROM, CASE_SELECT_FIELDS, build_filters


def _build_sql(tsquery_expr: str, filter_sql: str, limit_param: int) -> str:
    return f"""
        SELECT {CASE_SELECT_FIELDS},
            ts_rank(c.search_vector, {tsquery_expr}) AS score,
            ts_headline(
                'zhparser_config', c.violation_behavior,
                {tsquery_expr},
                'MaxWords=50, MinWords=20, StartSel=<mark>, StopSel=</mark>'
            ) AS violation_highlight
        FROM {CASE_FROM}
        WHERE c.is_insurance_related = TRUE
          AND c.search_vector @@ {tsquery_expr}
          {filter_sql}
        ORDER BY score DESC
        LIMIT ${limit_param}
    """


_AND_TSQUERY = "plainto_tsquery('zhparser_config', $1)"
# plainto_tsquery 只会产出 AND 链（不含短语邻接操作符），把 ' & ' 替换为 ' | ' 即可
# 安全地转成「任意词命中即可、命中越多排名越靠前」的 OR 查询。
_OR_TSQUERY = "replace(plainto_tsquery('zhparser_config', $1)::text, ' & ', ' | ')::tsquery"


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

        rows = await self.pool.fetch(_build_sql(_AND_TSQUERY, filter_sql, len(params)), *params)
        if not rows:
            rows = await self.pool.fetch(_build_sql(_OR_TSQUERY, filter_sql, len(params)), *params)

        results = []
        for row in rows:
            r = row_to_result(row, float(row["score"]), self.channel)
            r.highlight_fields["violation_behavior"] = row["violation_highlight"] or ""
            results.append(r)
        return results
