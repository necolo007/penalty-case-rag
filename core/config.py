"""全局配置：全部从环境变量 / .env 读取，API Key 禁止写入代码仓库。"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 国内常用 HF 镜像；加载 BGE/Reranker 前必须写入环境变量
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"


def apply_huggingface_mirror(endpoint: str | None = None) -> str:
    """把 HF_ENDPOINT 写入进程环境，供 huggingface_hub / transformers 使用。

    仍使用 Hub id（如 BAAI/bge-m3）拉取权重，但流量走镜像站而非 huggingface.co。
    """
    value = (endpoint or os.environ.get("HF_ENDPOINT") or DEFAULT_HF_ENDPOINT).strip()
    if value:
        os.environ["HF_ENDPOINT"] = value
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 基础设施 ----
    DATABASE_URL: str = "postgresql://kb_admin:change-me@localhost:5432/penalty_kb"
    REDIS_URL: str = "redis://localhost:6379"
    AUTO_MIGRATE: bool = True  # 启动时自动建表/种子（GORM AutoMigrate 风格）
    REQUIRE_ZHPARSER: bool = False  # true 时无 zhparser 扩展则启动失败（不降级 simple）

    # ---- LLM（DeepSeek-V4-Flash） ----
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-v4-flash"
    LLM_THINKING_DEFAULT: str = "disabled"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_RETRIES: int = 3

    # ---- Hugging Face 镜像（BGE-M3 / Reranker 等 Hub 拉取） ----
    HF_ENDPOINT: str = DEFAULT_HF_ENDPOINT

    # ---- Embedding ----
    # local_bge_m3=任务3默认（FlagEmbedding BGE-M3）；cloud / local 仅供 legacy 回滚
    EMBEDDING_PROVIDER: str = "local_bge_m3"  # local_bge_m3 | cloud | local
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_MODEL: str = ""
    EMBEDDING_DIMENSIONS: int = 1024
    EMBEDDING_INSTRUCT: str = (
        "Given an insurance marketing claim, retrieve similar regulatory penalty cases"
    )
    EMBEDDING_FALLBACK: str = "local"  # local | none（仅 cloud 模式）
    EMBEDDING_CACHE_TTL: int = 3600
    EMBEDDING_MODEL_LOCAL: str = "BAAI/bge-large-zh-v1.5"
    EMBEDDING_DEVICE: str = "cpu"

    # ---- BGE-M3（FlagEmbedding；Hub id，经 HF_ENDPOINT 镜像拉取） ----
    BGE_M3_MODEL: str = "BAAI/bge-m3"
    BGE_M3_DEVICE: str = "cpu"  # cuda | cpu
    BGE_M3_BATCH_SIZE: int = 8
    BGE_M3_MAX_LENGTH: int = 8192

    # ---- Reranker ----
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANKER_DEVICE: str = "cpu"
    RERANKER_ENABLED: bool = True
    RERANKER_BATCH_SIZE: int = 16
    RERANKER_DOC_MAX_CHARS: int = 1200

    # ---- 检索后端：bge_m3（默认）| legacy_four_way ----
    RETRIEVAL_BACKEND: str = "bge_m3"
    # HyDE：LLM 生成假想违法事实再 dense 召回（需可用 LLM；无 Key 时自动跳过）
    RETRIEVAL_HYDE_ENABLED: bool = True
    # HyDE 文本参与 CE：与口语 query 双路打分取 max（test n15 上劣化，默认关）
    RETRIEVAL_HYDE_RERANK: bool = False
    # dense_raw：原文口语 dense 通道；关闭则仅用改写（+可选 HyDE）做消融
    RETRIEVAL_DENSE_RAW_ENABLED: bool = True
    # 融合：max_merge=dense 族余弦取 max（默认）；weighted_rrf=多路加权 RRF
    RETRIEVAL_FUSION_MODE: str = "max_merge"
    # CE 后对 Top-K 做 LLM 列表重排+减枝（抬 Judge 精确率；默认关）
    RETRIEVAL_LLM_LISTWISE: bool = False
    RETRIEVAL_LLM_LISTWISE_KEEP_MIN: int = 3
    RETRIEVAL_LLM_LISTWISE_KEEP_MAX: int = 10

    # ---- 检索召回量 / 融合 / 精排 ----
    # legacy 四路
    RECALL_BM25: int = 80
    RECALL_VECTOR: int = 100
    RECALL_TAG: int = 80
    RECALL_RULE: int = 30
    # BGE-M3 dense + sparse
    RECALL_DENSE: int = 200
    RECALL_SPARSE: int = 100
    RETRIEVAL_FUSION_SIZE: int = 200
    RETRIEVAL_RERANK_CANDIDATES: int = 200
    RRF_K: int = 60
    RRF_W_BM25: float = 1.15
    RRF_W_VECTOR: float = 1.45
    RRF_W_TAG: float = 1.0
    RRF_W_RULE: float = 1.2
    # weighted_rrf 下建议 dense_raw + dense = 1（如 0.4/0.6）；max_merge 时权重不生效
    RRF_W_DENSE: float = 0.6
    RRF_W_DENSE_RAW: float = 0.4
    RRF_W_DENSE_HYDE: float = 0.35
    RRF_W_SPARSE: float = 0.2
    RRF_MULTI_CHANNEL_BONUS: float = 0.05
    CN_TAG_PREDICT_MAX: int = 3
    CN_TAG_FINAL_MAX: int = 5
    CN_TAG_CASE_MAX: int = 12
    CN_TAG_BM25_APPEND: int = 2
    RISK_ID_CAP: int = 3
    TAG_BACKFILL_TOP_CASES: int = 5

    # ---- 抽取 / 解析 ----
    # llm_first：长文决定书/OCR 用提示词主抽，正则仅作无 LLM/失败兜底
    # regex_first：正则主抽，低置信度再 LLM 纠错（旧路径）
    EXTRACTION_MODE: str = "llm_first"
    EXTRACTION_LLM_MAX_CHARS: int = 8000
    LLM_REFINE_THRESHOLD: float = 0.6
    PARSE_CONFIDENCE_THRESHOLD: float = 0.5

    # ---- 解析 ----
    MINERU_ENGINE: str = "hybrid"

    # ---- 存储 ----
    UPLOAD_DIR: str = "./uploads"
    DATA_DIR: str = "./data"
    MAX_UPLOAD_SIZE_MB: int = 50

    COMP_DATA_DIR: str = ""
    COMP_RAW_TEXT_DIR: str = ""
    EXAMPLE_CORPUS_DIR: str = ""
    SUBMISSION_RISK_STYLE: str = "cn"  # cn=中文标签；competition=R00x

    def rrf_channel_weights(self) -> dict[str, float]:
        """legacy_four_way 通道权重。"""
        return {
            "bm25": self.RRF_W_BM25,
            "vector": self.RRF_W_VECTOR,
            "tag": self.RRF_W_TAG,
            "rule": self.RRF_W_RULE,
        }

    def m3_rrf_channel_weights(self) -> dict[str, float]:
        """bge_m3：原文 dense / 改写 dense / HyDE dense / sparse。"""
        return {
            "dense_raw": self.RRF_W_DENSE_RAW,
            "dense": self.RRF_W_DENSE,
            "dense_hyde": self.RRF_W_DENSE_HYDE,
            "sparse": self.RRF_W_SPARSE,
        }

    def with_raw_rewrite_rrf_pair(self, w_raw: float) -> dict[str, float]:
        """原文/改写权重和为 1；HyDE/sparse 沿用配置（扫参时常用）。"""
        w = max(0.0, min(1.0, float(w_raw)))
        weights = self.m3_rrf_channel_weights()
        weights["dense_raw"] = w
        weights["dense"] = 1.0 - w
        return weights


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    endpoint = apply_huggingface_mirror(settings.HF_ENDPOINT)
    logger.debug("HF_ENDPOINT=%s", endpoint)
    return settings


# 导入即应用镜像，避免脚本/API 在 get_settings 前加载模型
apply_huggingface_mirror()
