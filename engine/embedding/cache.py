"""Query 向量 Redis 缓存（TTL 默认 1h）。

改写后文本 → embedding 缓存，相同/相似 query 避免重复 API 调用（~206ms → ~1ms）。
"""

import hashlib
import json

import redis.asyncio as aioredis

from engine.embedding.provider import BaseEmbeddingProvider


class CachedQueryEncoder:
    def __init__(self, provider: BaseEmbeddingProvider, redis: aioredis.Redis, ttl: int = 3600):
        self.provider = provider
        self.redis = redis
        self.ttl = ttl

    def _key(self, text: str) -> str:
        # instruct 纳入 key：EMBEDDING_INSTRUCT 调整/重启后若沿用旧 key，会在 TTL
        # 内静默返回按旧 instruct 编码的向量（同一 query 文本命中同一 key），
        # 造成配置生效但检索结果未变的隐蔽 Bug。
        instruct = getattr(self.provider, "instruct", "")
        digest = hashlib.sha256(f"{self.provider.model_name}:{instruct}:{text}".encode()).hexdigest()
        return f"qemb:{digest}"

    async def encode_query(self, text: str) -> list[float]:
        key = self._key(text)
        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached)

        embedding = self.provider.encode_queries([text])[0]
        await self.redis.set(key, json.dumps(embedding), ex=self.ttl)
        return embedding
