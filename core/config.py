"""全局配置：环境变量 / .env；API Key 勿写入仓库。

部署包约定（对照附件2）：
- Embedding / Reranker 默认从相对路径 ../models/ 本地加载
- 默认 HF_HUB_OFFLINE=1，禁止现场从 huggingface.co 拉权重
- 不写本机绝对路径；相对路径相对 penalty-case-rag 工作目录
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# 仅打包机/开发机拉权重时使用；部署现场应保持 OFFLINE，勿依赖镜像站
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"

# 随工程提交的相对路径（相对 cwd = penalty-case-rag）
DEFAULT_BGE_M3_DIR = "../models/bge-m3"
DEFAULT_RERANKER_DIR = "../models/bge-reranker-v2-m3"


def apply_huggingface_mirror(endpoint: str | None = None) -> str:
    """可选写入 HF_ENDPOINT（仅离线关闭且显式配置时）。"""
    value = (endpoint or os.environ.get("HF_ENDPOINT") or "").strip()
    if value:
        os.environ["HF_ENDPOINT"] = value
    return value


def apply_offline_hub_env(*, offline: bool) -> None:
    """把离线开关写入 os.environ，供 huggingface_hub / transformers 生效。"""
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
        os.environ.pop("HF_DATASETS_OFFLINE", None)


def looks_like_hub_id(name: str) -> bool:
    """Hub 仓库 id（如 BAAI/bge-m3），非本地相对/绝对路径。"""
    s = (name or "").strip()
    if not s or s.startswith((".", "/", "~")):
        return False
    if len(s) >= 2 and s[1] == ":":  # Windows drive
        return False
    if "\\" in s or s.startswith(".."):
        return False
    return "/" in s and not Path(s).exists()


def resolve_local_model_path(model: str, *, what: str, offline: bool = True) -> str:
    """解析为本地目录；离线模式下拒绝 Hub id，缺权重则明确报错。"""
    raw = (model or "").strip()
    if not raw:
        raise FileNotFoundError(f"{what} 未配置模型路径")

    if looks_like_hub_id(raw):
        if offline:
            raise FileNotFoundError(
                f"{what} 配置为 Hub id「{raw}」，但部署要求离线本地加载。"
                f"请改为随包权重目录（如 {DEFAULT_BGE_M3_DIR}），"
                "勿依赖测试环境访问 huggingface.co。"
            )
        return raw

    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()

    if path.is_dir() and (path / "config.json").is_file():
        return str(path)

    raise FileNotFoundError(
        f"{what} 本地权重未找到：配置={raw!r} → {path}。"
        "请确认 project/models/ 已随工程提交且含 config.json 与权重文件；"
        "部署现场不要执行 prepare_models.py / 不要从 Hub 下载。"
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 基础设施 ----
    DATABASE_URL: str = "postgresql://kb_admin:change-me@localhost:5432/penalty_kb"
    REDIS_URL: str = "redis://localhost:6379"
    AUTO_MIGRATE: bool = True
    REQUIRE_ZHPARSER: bool = False

    # ---- LLM（DeepSeek API，国内可达；非本地权重） ----
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com"
    LLM_MODEL: str = "deepseek-v4-flash"
    LLM_THINKING_DEFAULT: str = "disabled"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_RETRIES: int = 3

    # ---- Hugging Face：部署默认离线；镜像仅打包机使用 ----
    HF_HUB_OFFLINE: bool = True
    TRANSFORMERS_OFFLINE: bool = True
    HF_ENDPOINT: str = ""

    # ---- Embedding ----
    EMBEDDING_PROVIDER: str = "local_bge_m3"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_MODEL: str = ""
    EMBEDDING_DIMENSIONS: int = 1024
    EMBEDDING_INSTRUCT: str = (
        "Given an insurance marketing claim, retrieve similar regulatory penalty cases"
    )
    EMBEDDING_FALLBACK: str = "none"
    EMBEDDING_CACHE_TTL: int = 3600
    # legacy local 路径；默认勿指向 Hub（避免现场下载）
    EMBEDDING_MODEL_LOCAL: str = DEFAULT_BGE_M3_DIR
    EMBEDDING_DEVICE: str = "cpu"

    # ---- BGE-M3 / Reranker：默认相对路径本地权重 ----
    BGE_M3_MODEL: str = DEFAULT_BGE_M3_DIR
    BGE_M3_DEVICE: str = "cpu"
    BGE_M3_BATCH_SIZE: int = 8
    BGE_M3_MAX_LENGTH: int = 8192

    RERANKER_MODEL: str = DEFAULT_RERANKER_DIR
    RERANKER_DEVICE: str = "cpu"
    RERANKER_ENABLED: bool = True
    RERANKER_BATCH_SIZE: int = 16
    RERANKER_DOC_MAX_CHARS: int = 1200

    # ---- 检索后端 ----
    RETRIEVAL_BACKEND: str = "bge_m3"
    RETRIEVAL_HYDE_ENABLED: bool = True
    RETRIEVAL_DENSE_RAW_ENABLED: bool = True
    RETRIEVAL_LLM_LISTWISE: bool = True
    RETRIEVAL_LLM_LISTWISE_KEEP_MIN: int = 3
    RETRIEVAL_LLM_LISTWISE_KEEP_MAX: int = 10

    RECALL_BM25: int = 80
    RECALL_VECTOR: int = 100
    RECALL_TAG: int = 80
    RECALL_RULE: int = 30
    RECALL_DENSE: int = 200
    RECALL_SPARSE: int = 100
    RETRIEVAL_FUSION_SIZE: int = 200
    RETRIEVAL_RERANK_CANDIDATES: int = 200
    RRF_K: int = 60
    RRF_W_BM25: float = 1.15
    RRF_W_VECTOR: float = 1.45
    RRF_W_TAG: float = 1.0
    RRF_W_RULE: float = 1.2
    RRF_MULTI_CHANNEL_BONUS: float = 0.05
    CN_TAG_PREDICT_MAX: int = 3
    CN_TAG_FINAL_MAX: int = 5
    CN_TAG_CASE_MAX: int = 12
    CN_TAG_BM25_APPEND: int = 2
    RISK_ID_CAP: int = 3
    TAG_BACKFILL_TOP_CASES: int = 5

    EXTRACTION_MODE: str = "llm_first"
    EXTRACTION_LLM_MAX_CHARS: int = 8000
    LLM_REFINE_THRESHOLD: float = 0.6
    PARSE_CONFIDENCE_THRESHOLD: float = 0.5

    MINERU_ENGINE: str = "hybrid"

    UPLOAD_DIR: str = "./uploads"
    DATA_DIR: str = "./data"
    MAX_UPLOAD_SIZE_MB: int = 50

    COMP_DATA_DIR: str = ""
    COMP_RAW_TEXT_DIR: str = ""
    EXAMPLE_CORPUS_DIR: str = ""
    SUBMISSION_RISK_STYLE: str = "cn"

    def rrf_channel_weights(self) -> dict[str, float]:
        return {
            "bm25": self.RRF_W_BM25,
            "vector": self.RRF_W_VECTOR,
            "tag": self.RRF_W_TAG,
            "rule": self.RRF_W_RULE,
        }

    def resolved_bge_m3_path(self) -> str:
        return resolve_local_model_path(
            self.BGE_M3_MODEL, what="BGE-M3", offline=self.HF_HUB_OFFLINE,
        )

    def resolved_reranker_path(self) -> str:
        return resolve_local_model_path(
            self.RERANKER_MODEL, what="Reranker", offline=self.HF_HUB_OFFLINE,
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    offline = bool(settings.HF_HUB_OFFLINE or settings.TRANSFORMERS_OFFLINE)
    apply_offline_hub_env(offline=offline)
    if offline:
        logger.info(
            "Hub offline: BGE_M3_MODEL=%s RERANKER_MODEL=%s",
            settings.BGE_M3_MODEL,
            settings.RERANKER_MODEL,
        )
    else:
        endpoint = apply_huggingface_mirror(settings.HF_ENDPOINT or DEFAULT_HF_ENDPOINT)
        logger.debug("HF_ENDPOINT=%s (online allowed)", endpoint)
    return settings
