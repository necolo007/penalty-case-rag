"""DeepSeek-V4-Flash 统一客户端。

所有 LLM 任务（改写/抽取/分类/审查）共用本客户端，避免多 SDK 散落。
一期默认 thinking=disabled，保证检索链路 P99 延迟可控。
"""

import logging
import time
from enum import Enum

from openai import OpenAI

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ThinkingMode(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"


class DeepSeekClient:
    """DeepSeek-V4-Flash 统一客户端（OpenAI SDK 兼容）"""

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-v4-flash", max_retries: int = 3):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_retries = max_retries

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 800,
        temperature: float = 0.1,
        json_mode: bool = False,
        thinking: ThinkingMode = ThinkingMode.DISABLED,
    ) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "extra_body": {"thinking": {"type": thinking.value}},
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content or ""
            except Exception as e:  # noqa: BLE001 - 网关错误类型不可枚举，统一指数退避
                last_err = e
                wait = 2 ** attempt
                logger.warning("LLM call failed (attempt %d/%d): %s, retry in %ds",
                               attempt + 1, self.max_retries, e, wait)
                time.sleep(wait)
        raise RuntimeError(f"LLM call failed after {self.max_retries} retries") from last_err


def create_llm_client(settings: Settings | None = None) -> DeepSeekClient:
    settings = settings or get_settings()
    return DeepSeekClient(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        max_retries=settings.LLM_MAX_RETRIES,
    )
