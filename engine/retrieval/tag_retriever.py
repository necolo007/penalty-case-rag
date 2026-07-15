"""风险标签召回：按风险类型初判结果过滤候选案例（GIN 索引）。

同时匹配 risk_type_ids（R00x）与 risk_tags（中文），对齐配套数据标签体系。
"""

import asyncpg

from engine.classification.competition_label_map import (
    cn_tags_to_competition_ids,
    competition_ids_to_cn_tags,
)
from engine.retrieval.base import BaseRetriever, SearchQuery, SearchResult, row_to_result
from engine.retrieval.filters import CASE_FROM, CASE_SELECT_FIELDS, build_filters


class TagRetriever(BaseRetriever):
    channel = "tag"

    def __init__(self, pool: asyncpg.Pool, recall_size: int = 50):
        self.pool = pool
        self.recall_size = recall_size

    async def retrieve(self, query: SearchQuery, *, predicted_risk_ids: list[str] | None = None,
                       predicted_cn_tags: list[str] | None = None,
                       **_) -> list[SearchResult]:
        risk_ids = list(predicted_risk_ids or [])
        cn_tags = list(predicted_cn_tags or [])

        if query.risk_type:
            # 兼容传入 R00x 或中文标签
            if query.risk_type.startswith("R0"):
                risk_ids.append(query.risk_type)
            else:
                cn_tags.append(query.risk_type)

        # 双向补全
        risk_ids = list(dict.fromkeys([*risk_ids, *cn_tags_to_competition_ids(cn_tags)]))
        cn_tags = list(dict.fromkeys([*cn_tags, *competition_ids_to_cn_tags(risk_ids)]))

        if not risk_ids and not cn_tags:
            return []

        params: list = [risk_ids, cn_tags]
        filter_sql = build_filters(query, params)
        params.append(self.recall_size)

        sql = f"""
            SELECT {CASE_SELECT_FIELDS},
                (
                    CASE WHEN cardinality($1::text[]) > 0 THEN
                        COALESCE(cardinality(
                            ARRAY(SELECT UNNEST(c.risk_type_ids) INTERSECT SELECT UNNEST($1::text[]))
                        ), 0)
                    ELSE 0 END
                    + CASE WHEN cardinality($2::text[]) > 0 THEN
                        COALESCE(cardinality(
                            ARRAY(SELECT UNNEST(c.risk_tags) INTERSECT SELECT UNNEST($2::text[]))
                        ), 0)
                    ELSE 0 END
                )::float AS score
            FROM {CASE_FROM}
            WHERE c.is_insurance_related = TRUE
              AND (
                (cardinality($1::text[]) > 0 AND c.risk_type_ids && $1::text[])
                OR (cardinality($2::text[]) > 0 AND c.risk_tags && $2::text[])
              )
              {filter_sql}
            ORDER BY score DESC, c.overall_confidence DESC
            LIMIT ${len(params)}
        """
        rows = await self.pool.fetch(sql, *params)
        return [row_to_result(row, float(row["score"]), self.channel) for row in rows]
