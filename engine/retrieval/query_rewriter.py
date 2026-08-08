"""LLM 查询改写器（强制前置）+ 可选 HyDE。

- rewrite：口语 → 保留关键信息 + 追加法言法语（可关，仅同义词）
- hyde：口语 → 假想违法事实（决定书语体，供 dense_hyde 通道）

LLM 不可用时：rewrite 降级同义词；hyde 返回空串（跳过该通道）。
"""

from __future__ import annotations

import logging

from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import HYDE_PROMPT, QUERY_REWRITE_PROMPT

logger = logging.getLogger(__name__)


class QueryRewriter:
    def __init__(
        self,
        llm_client: DeepSeekClient | None,
        synonym_expander=None,
        *,
        use_llm_rewrite: bool = True,
    ):
        self.llm = llm_client
        self.synonym_expander = synonym_expander
        self.use_llm_rewrite = use_llm_rewrite

    async def rewrite(self, query_text: str) -> str:
        if self.use_llm_rewrite and self.llm is not None:
            try:
                rewritten = self.llm.complete(
                    QUERY_REWRITE_PROMPT.format(query_text=query_text),
                    max_tokens=180,
                    temperature=0.1,
                    thinking=ThinkingMode.DISABLED,
                )
                merged = " ".join(
                    line.strip() for line in rewritten.split("\n") if line.strip()
                )
                if merged:
                    q = query_text.strip()
                    if q and q not in merged:
                        return f"{q} {merged}"
                    return merged
            except Exception as e:  # noqa: BLE001
                logger.warning("LLM rewrite failed, fallback to synonym expansion: %s", e)

        if self.synonym_expander is not None:
            expanded = await self.synonym_expander.expand(query_text)
            if expanded:
                return expanded
        return query_text

    async def hyde(self, query_text: str) -> str:
        """生成假想违法事实；失败返回空串。"""
        q = (query_text or "").strip()
        if not q or self.llm is None:
            return ""
        try:
            text = self.llm.complete(
                HYDE_PROMPT.format(query_text=q),
                max_tokens=280,
                temperature=0.2,
                thinking=ThinkingMode.DISABLED,
            )
            cleaned = " ".join(line.strip() for line in text.splitlines() if line.strip())
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.lower().startswith("text"):
                    cleaned = cleaned[4:].strip()
            return cleaned[:600]
        except Exception as e:  # noqa: BLE001
            logger.warning("HyDE generation failed: %s", e)
            return ""
