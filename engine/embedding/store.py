"""Embedding 写入辅助：dense + 可选 sparse JSONB。"""

from __future__ import annotations

import json
from typing import Any

from engine.embedding.bge_m3_provider import BgeM3EmbeddingProvider, normalize_lexical_weights
from engine.embedding.provider import BaseEmbeddingProvider


def encode_documents_maybe_dual(
    provider: BaseEmbeddingProvider,
    texts: list[str],
) -> tuple[list[list[float]], list[dict[str, float]] | None]:
    """有 dual 接口则返回 sparse；否则仅 dense。"""
    if isinstance(provider, BgeM3EmbeddingProvider) or hasattr(provider, "encode_documents_dual"):
        dense, sparse = provider.encode_documents_dual(texts)  # type: ignore[attr-defined]
        return dense, sparse
    return provider.encode_documents(texts), None


UPSERT_EMBEDDING_SQL = """
INSERT INTO case_embeddings (
    case_id, embedding, embedding_model, sparse_weights, sparse_model
)
VALUES ($1, $2::vector, $3, $4::jsonb, $5)
ON CONFLICT (case_id) DO UPDATE SET
    embedding = EXCLUDED.embedding,
    embedding_model = EXCLUDED.embedding_model,
    sparse_weights = COALESCE(EXCLUDED.sparse_weights, case_embeddings.sparse_weights),
    sparse_model = COALESCE(EXCLUDED.sparse_model, case_embeddings.sparse_model)
"""


def upsert_embedding_args(
    case_id: str,
    dense: list[float],
    model_name: str,
    *,
    sparse: dict[str, float] | None = None,
    to_pgvector,
) -> tuple[Any, ...]:
    # asyncpg jsonb 编解码在本环境要求 str（配合 ::jsonb），不能直接传 dict
    sparse_payload = (
        json.dumps(normalize_lexical_weights(sparse), ensure_ascii=False)
        if sparse is not None
        else None
    )
    sparse_model = model_name if sparse is not None else None
    return (
        case_id,
        to_pgvector(dense),
        model_name,
        sparse_payload,
        sparse_model,
    )
