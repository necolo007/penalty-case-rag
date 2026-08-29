"""风险类型初判：规则词典优先，未命中时 LLM 分类。

返回 R001–R008，仅用于标签召回通道过滤；
对外分类 / submission 请使用 competition_label_map 的 28 类中文标签。
"""

import json
import logging
import re

import asyncpg

from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import RISK_TAG_PROMPT

logger = logging.getLogger(__name__)


class RiskPredictor:
    def __init__(self, pool: asyncpg.Pool, llm_client: DeepSeekClient | None = None):
        self.pool = pool
        self.llm = llm_client
        self._rules_cache: list[dict] | None = None
        self._risk_names_cache: dict[str, str] | None = None

    async def _load_rules(self) -> list[dict]:
        if self._rules_cache is None:
            rows = await self.pool.fetch(
                "SELECT pattern, risk_type_id, severity FROM rule_dictionary WHERE is_active"
            )
            self._rules_cache = [dict(r) for r in rows]
        return self._rules_cache

    async def load_risk_names(self) -> dict[str, str]:
        """competition_id → 官方风险类型名"""
        if self._risk_names_cache is None:
            rows = await self.pool.fetch(
                "SELECT risk_type_id, risk_type_name FROM risk_type_dict WHERE level = 1 AND is_active"
            )
            self._risk_names_cache = {r["risk_type_id"]: r["risk_type_name"] for r in rows}
        return self._risk_names_cache

    async def predict(self, query_text: str, *, use_llm_fallback: bool = True) -> list[str]:
        """返回赛题扁平风险 ID 列表，如 ['R001', 'R002']"""
        # 1. 规则匹配
        matched: list[str] = []
        for rule in await self._load_rules():
            try:
                if re.search(rule["pattern"], query_text):
                    matched.append(rule["risk_type_id"])
            except re.error:
                logger.warning("Invalid rule pattern skipped: %s", rule["pattern"])
        # 2. 同义词词典命中的风险类型
        rows = await self.pool.fetch(
            """
            SELECT DISTINCT risk_type_id FROM synonym_dictionary
            WHERE risk_type_id IS NOT NULL AND $1 LIKE '%' || business_term || '%'
            """,
            query_text,
        )
        matched.extend(r["risk_type_id"] for r in rows)

        deduped = list(dict.fromkeys(matched))
        if deduped:
            return deduped[:3]

        # 3. LLM 兜底（长尾类型）
        if use_llm_fallback and self.llm is not None:
            return await self._llm_predict(query_text)
        return []

    async def _llm_predict(self, query_text: str) -> list[str]:
        names = await self.load_risk_names()
        risk_type_list = "\n".join(f"- {rid}: {name}" for rid, name in sorted(names.items()))
        try:
            resp = self.llm.complete(
                RISK_TAG_PROMPT.format(violation_behavior=query_text, risk_type_list=risk_type_list),
                max_tokens=100,
                temperature=0.1,
                json_mode=True,
                thinking=ThinkingMode.DISABLED,
            )
            data = json.loads(resp)
            ids = [i for i in data.get("risk_type_ids", []) if i in names]
            return ids[:3]
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM risk prediction failed: %s", e)
            return []
