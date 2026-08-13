"""用「违规行为 + 案件总结」重建 case_embeddings（dense + 可选 sparse）。

用法：python scripts/reindex_embeddings.py [--limit 50]
BGE-M3 路径会同时写入 sparse_weights；legacy dense-only 仅写向量。
不再拼 raw_text / risk_tags，避免文书通用套话稀释检索信号。
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from core.config import get_settings
from core.db import close_pool, create_pool, to_pgvector
from engine.embedding.case_text import build_case_embed_text
from engine.embedding.provider import create_embedding_provider
from engine.embedding.store import UPSERT_EMBEDDING_SQL, encode_documents_maybe_dual, upsert_embedding_args
from engine.retrieval.assemble import get_sparse_index

logger = logging.getLogger(__name__)


def build_embed_text(row) -> str:
    return build_case_embed_text(
        violation_behavior=row["violation_behavior"],
        case_summary=row["case_summary"],
    )


async def reindex(*, limit: int | None, batch_size: int) -> None:
    settings = get_settings()
    pool = await create_pool()
    embedder = create_embedding_provider(settings)

    rows = await pool.fetch(
        """
        SELECT c.case_id, c.violation_behavior, c.case_summary
        FROM penalty_cases c
        WHERE c.is_insurance_related = TRUE
        ORDER BY c.case_id
        LIMIT $1
        """,
        limit or 10_000,
    )
    print(
        f"Reindexing {len(rows)} cases with model={embedder.model_name} "
        f"(embed=violation_behavior+case_summary)"
    )

    sparse_index = get_sparse_index()
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts = [build_embed_text(r) for r in batch]
        dense_list, sparse_list = encode_documents_maybe_dual(embedder, texts)
        async with pool.acquire() as conn:
            async with conn.transaction():
                for idx, row in enumerate(batch):
                    sparse = sparse_list[idx] if sparse_list is not None else None
                    await conn.execute(
                        UPSERT_EMBEDDING_SQL,
                        *upsert_embedding_args(
                            row["case_id"],
                            dense_list[idx],
                            embedder.model_name,
                            sparse=sparse,
                            to_pgvector=to_pgvector,
                        ),
                    )
                    if sparse is not None:
                        sparse_index.upsert(row["case_id"], sparse)
        print(f"  {min(i + batch_size, len(rows))}/{len(rows)}")

    # 确保索引与 DB 一致
    await sparse_index.load_from_db(pool)
    await close_pool()
    print("Done.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Rebuild case embeddings (violation_behavior + case_summary)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    asyncio.run(reindex(limit=args.limit, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
