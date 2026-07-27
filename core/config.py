"""全局配置：全部从环境变量 / .env 读取，API Key 禁止写入代码仓库。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # ---- Embedding（云端 Qwen 主 + 本地 BGE 兜底） ----
    EMBEDDING_PROVIDER: str = "cloud"  # cloud | local
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = "https://tokendance.space/gateway/v1"
    EMBEDDING_MODEL: str = "qwen-text-embedding-v4"
    EMBEDDING_DIMENSIONS: int = 1024
    EMBEDDING_INSTRUCT: str = (
        "Given an insurance marketing claim, retrieve similar regulatory penalty cases"
    )
    EMBEDDING_FALLBACK: str = "local"  # local | none
    EMBEDDING_CACHE_TTL: int = 3600
    EMBEDDING_MODEL_LOCAL: str = "BAAI/bge-large-zh-v1.5"
    EMBEDDING_DEVICE: str = "cpu"

    # ---- Reranker ----
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANKER_DEVICE: str = "cpu"
    RERANKER_ENABLED: bool = True
    RERANKER_BATCH_SIZE: int = 16
    RERANKER_DOC_MAX_CHARS: int = 1200

    # ---- 检索召回量 / 融合 / 精排 ----
    RECALL_BM25: int = 80
    RECALL_VECTOR: int = 100
    RECALL_TAG: int = 80
    RECALL_RULE: int = 30
    RETRIEVAL_FUSION_SIZE: int = 100
    RETRIEVAL_RERANK_CANDIDATES: int = 40
    RRF_K: int = 60
    RRF_W_BM25: float = 1.15
    RRF_W_VECTOR: float = 1.45
    RRF_W_TAG: float = 1.0
    RRF_W_RULE: float = 1.2
    RRF_MULTI_CHANNEL_BONUS: float = 0.08
    CN_TAG_PREDICT_MAX: int = 3
    CN_TAG_FINAL_MAX: int = 5
    CN_TAG_BM25_APPEND: int = 2
    RISK_ID_CAP: int = 3
    TAG_BACKFILL_TOP_CASES: int = 5

    # ---- 抽取 / 解析 ----
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
        return {
            "bm25": self.RRF_W_BM25,
            "vector": self.RRF_W_VECTOR,
            "tag": self.RRF_W_TAG,
            "rule": self.RRF_W_RULE,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
