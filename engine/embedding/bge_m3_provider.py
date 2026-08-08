"""FlagEmbedding BGEM3FlagModel：dense + sparse 双表征。

任务3主路径：入库与检索必须使用同一 BGE-M3 模型（embedding_model=bge-m3）。
不依赖 Qwen instruct；query/document 均走 BGEM3FlagModel.encode。
"""

from __future__ import annotations

import logging
from typing import Any

from engine.embedding.provider import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


def _to_float_list(vec: Any) -> list[float]:
    if hasattr(vec, "tolist"):
        return vec.tolist()
    return [float(x) for x in vec]


def normalize_lexical_weights(weights: Any) -> dict[str, float]:
    """FlagEmbedding lexical_weights → JSON 可序列化的 {token: weight}。"""
    if not weights:
        return {}
    if isinstance(weights, dict):
        return {str(k): float(v) for k, v in weights.items() if float(v) != 0.0}
    return {}


class BgeM3EmbeddingProvider(BaseEmbeddingProvider):
    """BAAI/bge-m3 via FlagEmbedding.BGEM3FlagModel。"""

    def __init__(
        self,
        model: str = "BAAI/bge-m3",
        device: str = "cpu",
        *,
        batch_size: int = 8,
        max_length: int = 8192,
    ):
        self._model_name = model
        self.device = device
        self.batch_size = batch_size
        self.max_length = max_length
        self._model = None

    def _get_model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel  # 延迟导入：local-models 可选依赖

            device = self.device
            try:
                import torch

                if device == "cuda" and not torch.cuda.is_available():
                    logger.warning("CUDA unavailable, BGE-M3 falling back to cpu")
                    device = "cpu"
            except ImportError:
                device = "cpu"

            logger.info("Loading BGE-M3 %s on %s", self._model_name, device)
            self._model = BGEM3FlagModel(
                self._model_name,
                use_fp16=(device == "cuda"),
                device=device,
            )
            self.device = device
        return self._model

    def _encode_dual(
        self, texts: list[str],
    ) -> tuple[list[list[float]], list[dict[str, float]]]:
        if not texts:
            return [], []
        model = self._get_model()
        out = model.encode(
            texts,
            batch_size=self.batch_size,
            max_length=self.max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense_raw = out["dense_vecs"]
        sparse_raw = out["lexical_weights"]
        dense = [_to_float_list(v) for v in dense_raw]
        sparse = [normalize_lexical_weights(w) for w in sparse_raw]
        return dense, sparse

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        dense, _ = self._encode_dual(texts)
        return dense

    def encode_queries(self, texts: list[str]) -> list[list[float]]:
        dense, _ = self._encode_dual(texts)
        return dense

    def encode_documents_dual(
        self, texts: list[str],
    ) -> tuple[list[list[float]], list[dict[str, float]]]:
        return self._encode_dual(texts)

    def encode_queries_dual(
        self, texts: list[str],
    ) -> tuple[list[list[float]], list[dict[str, float]]]:
        return self._encode_dual(texts)

    @property
    def model_name(self) -> str:
        # 短名写入 case_embeddings.embedding_model，便于过滤/对比
        return "bge-m3"

    @property
    def dimension(self) -> int:
        return 1024
