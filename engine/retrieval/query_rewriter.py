"""LLM 查询改写器（强制前置，实测向量相似度 0.39 → 0.81）。

口语 → 法言法语。LLM 不可用时降级为同义词词典改写。
"""

import logging

from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import QUERY_REWRITE_PROMPT

logger = logging.getLogger(__name__)


class QueryRewriter:
    def __init__(self, llm_client: DeepSeekClient, synonym_expander=None):
        self.llm = llm_client
        self.synonym_expander = synonym_expander

    async def rewrite(self, query_text: str) -> str:
        try:
            rewritten = self.llm.complete(
                QUERY_REWRITE_PROMPT.format(query_text=query_text),
                max_tokens=150,
                temperature=0.1,
                thinking=ThinkingMode.DISABLED,
            )
            merged = " ".join(line.strip() for line in rewritten.split("\n") if line.strip())
            if merged:
                return merged
        except Exception as e:  # noqa: BLE001 - LLM 故障时降级，检索不可中断
            logger.warning("LLM rewrite failed, fallback to synonym expansion: %s", e)

        # 降级：同义词词典改写
        if self.synonym_expander is not None:
            expanded = await self.synonym_expander.expand(query_text)
            if expanded:
                return expanded
        return query_text
