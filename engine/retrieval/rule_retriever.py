"""规则词典召回：业务口语 → 标准违规表述的确定性映射。

流程：query 分词/子串匹配 synonym_dictionary.business_term
      → 得到 standard_term 集合 → 对标准表述做全文精确匹配召回。
"""

import asyncpg

from engine.retrieval.base import BaseRetriever, SearchQuery, SearchResult, row_to_result
from engine.retrieval.filters import CASE_FROM, CASE_SELECT_FIELDS, build_filters


class RuleRetriever(BaseRetriever):
    channel = "rule"

    def __init__(self, pool: asyncpg.Pool, recall_size: int = 30):
        self.pool = pool
        self.recall_size = recall_size

    async def _match_synonyms(self, query_text: str) -> list[dict]:
        """business_term 出现在 query 中即命中（子串匹配，词典条目为短语级）"""
        rows = await self.pool.fetch(
            """
            SELECT business_term, standard_term, risk_type_id, weight
            FROM synonym_dictionary
            WHERE $1 LIKE '%' || business_term || '%'
            ORDER BY weight DESC
            LIMIT 20
            """,
            query_text,
        )
        return [dict(r) for r in rows]

    async def retrieve(self, query: SearchQuery, **_) -> list[SearchResult]:
        synonyms = await self._match_synonyms(query.query_text)
        if not synonyms:
            return []

        # 合并所有标准表述作为检索词
        standard_terms = " ".join(dict.fromkeys(s["standard_term"] for s in synonyms))
        matched_terms = [s["business_term"] for s in synonyms]
        risk_ids = list(dict.fromkeys(
            s["risk_type_id"] for s in synonyms if s.get("risk_type_id")
        ))

        params: list = [standard_terms]
        filter_sql = build_filters(query, params)
        params.append(self.recall_size)

        # 命中多个同义词时 standard_terms 会拼接多个不同标准表述，plainto_tsquery
        # 的 AND 语义要求全部同时出现在同一文档，几乎必然为空；与 BM25 通道同样
        # 先尝试 AND 精确匹配，为空再退化为 OR。
        def _sql(tsquery_expr: str) -> str:
            return f"""
                SELECT {CASE_SELECT_FIELDS},
                    ts_rank(c.search_vector, {tsquery_expr}) AS score
                FROM {CASE_FROM}
                WHERE c.is_insurance_related = TRUE
                  AND c.search_vector @@ {tsquery_expr}
                  {filter_sql}
                ORDER BY score DESC
                LIMIT ${len(params)}
            """

        rows = await self.pool.fetch(_sql("plainto_tsquery('zhparser_config', $1)"), *params)
        if not rows:
            rows = await self.pool.fetch(
                _sql("replace(plainto_tsquery('zhparser_config', $1)::text, ' & ', ' | ')::tsquery"),
                *params,
            )

        # 全文未命中时，回退到同义词映射的风险类型过滤（保证规则通道有召回）
        if not rows and risk_ids:
            params2: list = [risk_ids]
            filter_sql2 = build_filters(query, params2)
            params2.append(self.recall_size)
            sql2 = f"""
                SELECT {CASE_SELECT_FIELDS},
                    COALESCE(cardinality(
                        ARRAY(SELECT UNNEST(c.risk_type_ids) INTERSECT SELECT UNNEST($1::text[]))
                    ), 0)::float AS score
                FROM {CASE_FROM}
                WHERE c.is_insurance_related = TRUE
                  AND c.risk_type_ids && $1::text[]
                  {filter_sql2}
                ORDER BY score DESC, c.overall_confidence DESC
                LIMIT ${len(params2)}
            """
            rows = await self.pool.fetch(sql2, *params2)

        results = []
        for row in rows:
            r = row_to_result(row, float(row["score"]), self.channel)
            r.match_reason = f"命中规则词典：{'、'.join(matched_terms)}"
            results.append(r)
        return results
