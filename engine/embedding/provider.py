"""Embedding Provider：入库与检索须同一模型；切换后需全量 reindex。"""

import logging
import time
from abc import ABC, abstractmethod

from openai import OpenAI

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10
_MAX_RETRIES = 3


class BaseEmbeddingProvider(ABC):
    @abstractmethod
    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        """入库：文档侧编码，不加 instruct"""

    @abstractmethod
    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        """检索：查询侧编码，加 instruct 提升非对称匹配"""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int:
        return 1024


class CloudEmbeddingProvider(BaseEmbeddingProvider):
    """云端 embedding（OpenAI 兼容网关）。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str | None = None,
        instruct: str | None = None,
        dimensions: int | None = None,
    ):
        settings = get_settings()
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model or settings.EMBEDDING_MODEL or "qwen-text-embedding-v4"
        self.instruct = instruct or settings.EMBEDDING_INSTRUCT
        self.dimensions = dimensions if dimensions is not None else settings.EMBEDDING_DIMENSIONS

    def _batch_encode(self, texts: list[str], *, extra_body: dict | None = None) -> list[list[float]]:
        results: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            kwargs: dict = {"model": self.model, "input": batch, "dimensions": self.dimensions}
            if extra_body:
                kwargs["extra_body"] = extra_body
            resp = self._create_with_retry(kwargs)
            results.extend([d.embedding for d in resp.data])
        return results

    def _create_with_retry(self, kwargs: dict):
        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return self.client.embeddings.create(**kwargs)
            except Exception as e:  # noqa: BLE001
                last_err = e
                wait = 2 ** attempt
                logger.warning("Embedding API failed (attempt %d/%d): %s, retry in %ds",
                               attempt + 1, _MAX_RETRIES, e, wait)
                time.sleep(wait)
        raise RuntimeError("Embedding API failed after retries") from last_err

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self._batch_encode(texts)

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        return self._batch_encode(texts, extra_body={"instruct": self.instruct})

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def dimension(self) -> int:
        return self.dimensions


class LocalEmbeddingProvider(BaseEmbeddingProvider):
    """本地 BGE-large；与云端不在同一向量空间，切换后需 reindex。"""

    _QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

    def __init__(self, model: str | None = None, device: str | None = None):
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        self._model_name = model or settings.EMBEDDING_MODEL_LOCAL
        self.model = SentenceTransformer(
            self._model_name,
            device=device or settings.EMBEDDING_DEVICE,
        )

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        prefixed = [self._QUERY_INSTRUCTION + t for t in texts]
        return self.model.encode(prefixed, normalize_embeddings=True).tolist()

    @property
    def model_name(self) -> str:
        return self._model_name


class FallbackEmbeddingProvider(BaseEmbeddingProvider):
    """云端优先，失败降级本地（懒加载），并记录告警提示 reindex。"""

    def __init__(self, primary: CloudEmbeddingProvider, settings: Settings):
        self.primary = primary
        self.settings = settings
        self._local: LocalEmbeddingProvider | None = None
        self._degraded = False

    def _get_local(self) -> LocalEmbeddingProvider:
        if self._local is None:
            self._local = LocalEmbeddingProvider(
                model=self.settings.EMBEDDING_MODEL_LOCAL,
                device=self.settings.EMBEDDING_DEVICE,
            )
        return self._local

    def _run(self, method: str, texts: list[str]) -> list[list[float]]:
        try:
            result = getattr(self.primary, method)(texts)
            self._degraded = False
            return result
        except Exception:
            if self.settings.EMBEDDING_FALLBACK != "local":
                raise
            if not self._degraded:
                logger.error(
                    "Cloud embedding degraded to local BGE. "
                    "Vector space mismatch: full reindex required before serving!"
                )
                self._degraded = True
            return getattr(self._get_local(), method)(texts)

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self._run("encode_documents", texts)

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        return self._run("encode_queries", texts)

    @property
    def model_name(self) -> str:
        if self._degraded:
            return self.settings.EMBEDDING_MODEL_LOCAL
        return self.primary.model_name


def create_embedding_provider(settings: Settings | None = None) -> BaseEmbeddingProvider:
    settings = settings or get_settings()
    provider = (settings.EMBEDDING_PROVIDER or "local_bge_m3").strip().lower()

    if provider in ("local_bge_m3", "bge_m3", "bge-m3"):
        from engine.embedding.bge_m3_provider import BgeM3EmbeddingProvider

        return BgeM3EmbeddingProvider(
            model=settings.BGE_M3_MODEL,
            device=settings.BGE_M3_DEVICE or settings.EMBEDDING_DEVICE,
            batch_size=settings.BGE_M3_BATCH_SIZE,
            max_length=settings.BGE_M3_MAX_LENGTH,
        )

    if provider == "cloud":
        cloud = CloudEmbeddingProvider(
            api_key=settings.EMBEDDING_API_KEY,
            base_url=settings.EMBEDDING_BASE_URL,
            model=settings.EMBEDDING_MODEL,
            instruct=settings.EMBEDDING_INSTRUCT,
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
        if settings.EMBEDDING_FALLBACK == "local":
            return FallbackEmbeddingProvider(cloud, settings)
        return cloud

    return LocalEmbeddingProvider(
        model=settings.EMBEDDING_MODEL_LOCAL,
        device=settings.EMBEDDING_DEVICE,
    )
