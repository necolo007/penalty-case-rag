"""BGE-M3 sparse 通道召回：内存倒排 + DB 回表补全案例字段。"""

from __future__ import annotations

import asyncpg

from engine.retrieval.base import BaseRetriever, SearchQuery, SearchResult, row_to_result
from engine.retrieval.filters import CASE_SELECT_FIELDS, build_filters
from engine.retrieval.sparse_index import SparseLexicalIndex


class SparseRetriever(BaseRetriever):
    channel = "sparse"

    def __init__(
        self,
        pool: asyncpg.Pool,
        index: SparseLexicalIndex,
        recall_size: int = 120,
    ):
        self.pool = pool
        self.index = index
        self.recall_size = recall_size

    async def retrieve(
        self,
        query: SearchQuery,
        *,
        query_sparse: dict[str, float] | None = None,
        **_,
    ) -> list[SearchResult]:
        if not query_sparse:
            return []

        hits = self.index.search(query_sparse, self.recall_size)
        if not hits:
            return []

        score_map = {cid: score for cid, score in hits}
        case_ids = list(score_map.keys())

        params: list = [case_ids]
        filter_sql = build_filters(query, params)
        sql = f"""
            SELECT {CASE_SELECT_FIELDS}
            FROM penalty_cases c
            JOIN documents d ON c.file_id = d.file_id
            WHERE c.is_insurance_related = TRUE
              AND c.case_id = ANY($1::text[])
              {filter_sql}
        """
        rows = await self.pool.fetch(sql, *params)
        results = [
            row_to_result(row, float(score_map[row["case_id"]]), self.channel)
            for row in rows
            if row["case_id"] in score_map
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        return results
