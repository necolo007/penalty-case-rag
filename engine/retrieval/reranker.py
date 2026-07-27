"""Cross-Encoder 精排：BAAI/bge-reranker-v2-m3（本地，GPU 优先 CPU 降级）。

模型加载采用懒加载 + 线程池执行，避免阻塞事件循环。
"""

import asyncio
import logging

from engine.retrieval.base import SearchResult

logger = logging.getLogger(__name__)


class Reranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None

    def _get_model(self):
        if self._model is None:
            from FlagEmbedding import FlagReranker  # 延迟导入：local-models 可选依赖

            device = self.device
            try:
                import torch

                if device == "cuda" and not torch.cuda.is_available():
                    logger.warning("CUDA unavailable, reranker falling back to cpu")
                    device = "cpu"
            except ImportError:
                device = "cpu"

            logger.info("Loading reranker %s on %s", self.model_name, device)
            self._model = FlagReranker(
                self.model_name,
                use_fp16=(device == "cuda"),
                device=device,
            )
            self.device = device
        return self._model

    def _score_pairs(self, pairs: list[list[str]]) -> list[float]:
        # batch_size 控制 CPU 峰值；normalize 便于与 RRF 分数语义区分
        scores = self._get_model().compute_score(pairs, normalize=True, batch_size=16)
        if isinstance(scores, float):
            return [scores]
        return list(scores)

    @staticmethod
    def _case_text(result: SearchResult) -> str:
        parts = [
            result.party_name,
            result.violation_behavior,
            result.penalty_content,
            " ".join(result.risk_tags or []),
        ]
        text = " ".join(p for p in parts if p)
        return text[:1200]

    async def rerank(self, query_text: str, candidates: list[SearchResult],
                     top_k: int = 10) -> list[SearchResult]:
        if not candidates:
            return []
        pairs = [[query_text, self._case_text(c)] for c in candidates]
        try:
            scores = await asyncio.to_thread(self._score_pairs, pairs)
        except Exception as e:  # noqa: BLE001 - 精排失败降级为 RRF 排序
            logger.warning("Reranker failed, fallback to RRF order: %s", e)
            return candidates[:top_k]

        for c, s in zip(candidates, scores):
            c.score = float(s)
        return sorted(candidates, key=lambda c: c.score, reverse=True)[:top_k]


class NoopReranker(Reranker):
    """RERANKER_ENABLED=false 时使用：直接按 RRF 顺序截断。"""

    def __init__(self):  # noqa: D107
        pass

    async def rerank(self, query_text: str, candidates: list[SearchResult],
                     top_k: int = 10) -> list[SearchResult]:
        return candidates[:top_k]
