"""向量语义召回：pgvector cosine 相似度。

解决：跨越表述差异（「送体检卡」↔「合同外利益」）。
向量必须来自改写后文本 + encode_queries(+instruct)，由 HybridRetriever 传入。
"""

import asyncpg

from core.db import to_pgvector
from engine.retrieval.base import BaseRetriever, SearchQuery, SearchResult, row_to_result
from engine.retrieval.filters import CASE_SELECT_FIELDS, build_filters


class VectorRetriever(BaseRetriever):
    channel = "vector"

    def __init__(self, pool: asyncpg.Pool, recall_size: int = 100, *, channel: str | None = None):
        self.pool = pool
        self.recall_size = recall_size
        if channel:
            self.channel = channel

    async def retrieve(self, query: SearchQuery, *, query_embedding: list[float] | None = None,
                       **_) -> list[SearchResult]:
        if query_embedding is None:
            raise ValueError("VectorRetriever requires query_embedding")

        params: list = [to_pgvector(query_embedding)]
        filter_sql = build_filters(query, params)
        params.append(self.recall_size)

        sql = f"""
            SELECT {CASE_SELECT_FIELDS},
                1 - (e.embedding <=> $1::vector) AS score
            FROM case_embeddings e
            JOIN penalty_cases c ON e.case_id = c.case_id
            JOIN documents d ON c.file_id = d.file_id
            WHERE c.is_insurance_related = TRUE
              {filter_sql}
            ORDER BY e.embedding <=> $1::vector
            LIMIT ${len(params)}
        """
        rows = await self.pool.fetch(sql, *params)
        return [row_to_result(row, float(row["score"]), self.channel) for row in rows]
