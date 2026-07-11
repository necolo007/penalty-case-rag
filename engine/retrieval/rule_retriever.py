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

        params: list = [standard_terms]
        filter_sql = build_filters(query, params)
        params.append(self.recall_size)

        sql = f"""
            SELECT {CASE_SELECT_FIELDS},
                ts_rank(c.search_vector, plainto_tsquery('zhparser_config', $1)) AS score
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
            r.match_reason = f"命中规则词典：{'、'.join(matched_terms)}"
            results.append(r)
        return results
