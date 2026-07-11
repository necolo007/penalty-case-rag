"""全局配置：全部从环境变量 / .env 读取，API Key 禁止写入代码仓库。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 基础设施 ----
    DATABASE_URL: str = "postgresql://kb_admin:change-me@localhost:5432/penalty_kb"
    REDIS_URL: str = "redis://localhost:6379"
    AUTO_MIGRATE: bool = True  # 启动时自动建表/种子（GORM AutoMigrate 风格）

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

    # ---- 解析 ----
    MINERU_ENGINE: str = "hybrid"

    # ---- 存储 ----
    UPLOAD_DIR: str = "./uploads"
    DATA_DIR: str = "./data"
    MAX_UPLOAD_SIZE_MB: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
