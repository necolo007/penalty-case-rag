"""Query 向量 Redis 缓存（TTL 默认 1h）。

改写后文本 → embedding 缓存；BGE-M3 路径额外缓存 sparse lexical_weights。
"""

from __future__ import annotations

import hashlib
import json

import redis.asyncio as aioredis

from engine.embedding.provider import BaseEmbeddingProvider


class CachedQueryEncoder:
    def __init__(self, provider: BaseEmbeddingProvider, redis: aioredis.Redis, ttl: int = 3600):
        self.provider = provider
        self.redis = redis
        self.ttl = ttl

    def _key(self, text: str, *, kind: str = "dense") -> str:
        # instruct 纳入 key：EMBEDDING_INSTRUCT 调整后避免静默命中旧向量
        instruct = getattr(self.provider, "instruct", "")
        digest = hashlib.sha256(
            f"{self.provider.model_name}:{instruct}:{kind}:{text}".encode()
        ).hexdigest()
        return f"qemb:{digest}"

    async def encode_query(self, text: str) -> list[float]:
        key = self._key(text, kind="dense")
        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached)

        embedding = self.provider.encode_queries([text])[0]
        await self.redis.set(key, json.dumps(embedding), ex=self.ttl)
        return embedding

    async def encode_query_dual(self, text: str) -> tuple[list[float], dict[str, float]]:
        """返回 (dense, sparse)；无 dual 能力时 sparse 为空 dict。"""
        if not hasattr(self.provider, "encode_queries_dual"):
            dense = await self.encode_query(text)
            return dense, {}

        key = self._key(text, kind="dual")
        cached = await self.redis.get(key)
        if cached:
            data = json.loads(cached)
            return data["dense"], data.get("sparse") or {}

        dense_list, sparse_list = self.provider.encode_queries_dual([text])
        dense, sparse = dense_list[0], sparse_list[0]
        await self.redis.set(
            key,
            json.dumps({"dense": dense, "sparse": sparse}, ensure_ascii=False),
            ex=self.ttl,
        )
        return dense, sparse
