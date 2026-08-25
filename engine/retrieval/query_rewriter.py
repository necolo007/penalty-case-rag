"""查询改写 + 可选 HyDE；LLM 失败时改写降级同义词，HyDE 返回空串。"""

from __future__ import annotations

import json
import logging
import re

from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import HYDE_PROMPT, QUERY_REWRITE_PROMPT
from core.config import get_settings

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
                # 示例里含 JSON 花括号，不能用 str.format
                prompt = QUERY_REWRITE_PROMPT.replace("{query_text}", query_text)
                rewritten = self.llm.complete(
                    prompt,
                    max_tokens=220,
                    temperature=get_settings().LLM_TEMPERATURE,
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
