"""用 raw_text 增强重建 case_embeddings。

用法：python scripts/reindex_embeddings.py [--limit 50]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re

from core.config import get_settings
from core.db import close_pool, create_pool, to_pgvector
from engine.embedding.provider import create_embedding_provider

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

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts = [build_embed_text(r) for r in batch]
        vectors = embedder.encode_documents(texts)
        async with pool.acquire() as conn:
            async with conn.transaction():
                for row, vec in zip(batch, vectors, strict=True):
                    await conn.execute(
                        """
                        INSERT INTO case_embeddings (case_id, embedding, embedding_model)
                        VALUES ($1, $2::vector, $3)
                        ON CONFLICT (case_id) DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            embedding_model = EXCLUDED.embedding_model
                        """,
                        row["case_id"],
                        to_pgvector(vec),
                        embedder.model_name,
                    )
        print(f"  {min(i + batch_size, len(rows))}/{len(rows)}")

    await close_pool()
    print("Done.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Rebuild case embeddings with raw_text")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(reindex(limit=args.limit, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
