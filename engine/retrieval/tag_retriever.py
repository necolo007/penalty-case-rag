"""风险标签召回：按风险类型初判结果过滤候选案例（GIN 索引）。

解决：缩小搜索空间，提升同类违规命中率。
predicted_risk_ids 由 RiskPredictor 提供（规则优先 + LLM 补全）。
"""

import asyncpg

from engine.retrieval.base import BaseRetriever, SearchQuery, SearchResult, row_to_result
from engine.retrieval.filters import CASE_FROM, CASE_SELECT_FIELDS, build_filters


class TagRetriever(BaseRetriever):
    channel = "tag"

    def __init__(self, pool: asyncpg.Pool, recall_size: int = 50):
        self.pool = pool
        self.recall_size = recall_size

    async def retrieve(self, query: SearchQuery, *, predicted_risk_ids: list[str] | None = None,
                       **_) -> list[SearchResult]:
        risk_ids = predicted_risk_ids or ([query.risk_type] if query.risk_type else [])
        if not risk_ids:
            return []

        params: list = [risk_ids]
        filter_sql = build_filters(query, params)
        params.append(self.recall_size)

        # 命中标签越多分数越高；同分内按置信度排序
        sql = f"""
            SELECT {CASE_SELECT_FIELDS},
                cardinality(
                    ARRAY(SELECT UNNEST(c.risk_type_ids) INTERSECT SELECT UNNEST($1::text[]))
                )::float AS score
            FROM {CASE_FROM}
            WHERE c.is_insurance_related = TRUE
              AND c.risk_type_ids && $1::text[]
              {filter_sql}
            ORDER BY score DESC, c.overall_confidence DESC
            LIMIT ${len(params)}
        """
        rows = await self.pool.fetch(sql, *params)
        return [row_to_result(row, float(row["score"]), self.channel) for row in rows]
