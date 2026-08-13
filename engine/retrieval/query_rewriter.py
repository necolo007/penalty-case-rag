"""LLM 查询改写器（强制前置）+ 可选 HyDE。

- rewrite：口语 → 规范化行为描述（JSON normalized_violation；可关，仅同义词）
- hyde：口语 → 假想违法事实（决定书语体，供 dense_hyde 通道）

LLM 不可用时：rewrite 降级同义词；hyde 返回空串（跳过该通道）。
改写结果供 dense 通道；原文由 dense_raw 单独编码，故不再强制拼接原文。
"""

from __future__ import annotations

import json
import logging
import re

from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import HYDE_PROMPT, QUERY_REWRITE_PROMPT

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _parse_normalized_violation(raw: str) -> str:
    """从模型输出中提取 normalized_violation；失败则退回清洗后的纯文本。"""
    text = (raw or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            val = data.get("normalized_violation") or data.get("rewritten_query") or ""
            if isinstance(val, str) and val.strip():
                return val.strip()
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK.search(text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                val = data.get("normalized_violation") or ""
                if isinstance(val, str) and val.strip():
                    return val.strip()
        except json.JSONDecodeError:
            pass
    # 非 JSON：去掉可能的前缀，压成一行
    cleaned = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if cleaned.lower().startswith("输出："):
        cleaned = cleaned[3:].strip()
    return cleaned


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
                    max_tokens=220,
                    temperature=0.1,
                    thinking=ThinkingMode.DISABLED,
                )
                normalized = _parse_normalized_violation(rewritten)
                if normalized:
                    return normalized
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
