"""用文档文本重建 case_embeddings（dense + 可选 sparse）。

用法：python scripts/reindex_embeddings.py [--limit 50]
BGE-M3 路径会同时写入 sparse_weights；legacy dense-only 仅写向量。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re

from core.config import get_settings
from core.db import close_pool, create_pool, to_pgvector
from engine.embedding.provider import create_embedding_provider
from engine.embedding.store import UPSERT_EMBEDDING_SQL, encode_documents_maybe_dual, upsert_embedding_args
from engine.retrieval.assemble import get_sparse_index

logger = logging.getLogger(__name__)

_BOILERPLATE = re.compile(
    r"(账户名称|开户银行|开户账号|如不服本处罚|行政复议|行政诉讼|"
    r"手机扫一扫|缴纳罚款|加处罚款).{0,80}",
    re.S,
)


def _clean_raw(text: str, max_chars: int = 1200) -> str:
    if not text:
        return ""
    cleaned = _BOILERPLATE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_chars]


def build_embed_text(row) -> str:
    tags = " ".join(row["risk_tags"] or [])
    raw = _clean_raw(row["raw_text"] or "")
    parts = [
        row["violation_behavior"] or "",
        row["penalty_content"] or "",
        tags,
        row["case_summary"] or "",
        raw,
    ]
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return text[:2000] if text else "保险监管处罚案例"


async def reindex(*, limit: int | None, batch_size: int) -> None:
    settings = get_settings()
    pool = await create_pool()
    embedder = create_embedding_provider(settings)

    rows = await pool.fetch(
        """
        SELECT c.case_id, c.violation_behavior, c.penalty_content,
               c.risk_tags, c.case_summary, d.raw_text
        FROM penalty_cases c
        JOIN documents d ON c.file_id = d.file_id
        WHERE c.is_insurance_related = TRUE
        ORDER BY c.case_id
        LIMIT $1
        """,
        limit or 10_000,
    )
    print(f"Reindexing {len(rows)} cases with model={embedder.model_name}")

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
    parser = argparse.ArgumentParser(description="Rebuild case embeddings with raw_text")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    asyncio.run(reindex(limit=args.limit, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
