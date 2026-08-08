"""BGE-M3 sparse lexical 倒排索引（进程内）。

案例量级约万级：启动从 DB 加载 sparse_weights，查询时对 query lexical_weights
做加权求和（FlagEmbedding 稀疏内积语义）。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

import asyncpg

logger = logging.getLogger(__name__)


def _parse_weights(raw) -> dict[str, float]:
    if raw is None:
        return {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, dict):
        return {str(k): float(v) for k, v in raw.items() if float(v) != 0.0}
    return {}


class SparseLexicalIndex:
    """token → [(case_id, weight)] 倒排 + case 权重表。"""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, float]] = {}
        self._inverted: dict[str, list[tuple[str, float]]] = defaultdict(list)
        self._loaded = False

    @property
    def size(self) -> int:
        return len(self._docs)

    @property
    def loaded(self) -> bool:
        return self._loaded

    def clear(self) -> None:
        self._docs.clear()
        self._inverted.clear()
        self._loaded = False

    def upsert(self, case_id: str, weights: dict[str, float] | None) -> None:
        weights = weights or {}
        old = self._docs.pop(case_id, None)
        if old:
            for tok in old:
                posting = self._inverted.get(tok)
                if not posting:
                    continue
                self._inverted[tok] = [(c, w) for c, w in posting if c != case_id]
                if not self._inverted[tok]:
                    del self._inverted[tok]

        if not weights:
            return
        self._docs[case_id] = dict(weights)
        for tok, w in weights.items():
            self._inverted[tok].append((case_id, w))

    def remove(self, case_id: str) -> None:
        self.upsert(case_id, None)

    async def load_from_db(self, pool: asyncpg.Pool) -> int:
        rows = await pool.fetch(
            """
            SELECT case_id, sparse_weights
            FROM case_embeddings
            WHERE sparse_weights IS NOT NULL
            """
        )
        self.clear()
        for row in rows:
            self.upsert(row["case_id"], _parse_weights(row["sparse_weights"]))
        self._loaded = True
        logger.info("SparseLexicalIndex loaded %d docs", len(self._docs))
        return len(self._docs)

    def search(self, query_weights: dict[str, float], top_k: int) -> list[tuple[str, float]]:
        """稀疏内积：score(d) = Σ_t q_t * d_t。"""
        if not query_weights or top_k <= 0:
            return []
        scores: dict[str, float] = defaultdict(float)
        for tok, qw in query_weights.items():
            posting = self._inverted.get(tok)
            if not posting:
                continue
            for case_id, dw in posting:
                scores[case_id] += qw * dw

        if not scores:
            return []
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
