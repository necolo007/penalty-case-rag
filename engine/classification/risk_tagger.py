"""风险标签归类：三级词典规则 + 27 类中文词典增强 + LLM 兜底。"""

import json
import logging

import asyncpg

from engine.classification.competition_label_map import (
    cn_tags_to_competition_ids,
    normalize_cn_tags,
    predict_cn_tags_by_keywords,
)
from engine.classification.tag_mapper import map_internal_to_competition
from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import RISK_TAG_PROMPT

logger = logging.getLogger(__name__)


class RiskTagger:
    def __init__(self, pool: asyncpg.Pool, llm_client: DeepSeekClient | None = None):
        self.pool = pool
        self.llm = llm_client
        self._dict_cache: list[dict] | None = None

    async def _load_dict(self) -> list[dict]:
        if self._dict_cache is None:
            rows = await self.pool.fetch(
                """
                SELECT risk_type_id, competition_id, risk_type_name, display_tags, keywords, level
                FROM risk_type_dict WHERE is_active
                ORDER BY level DESC
                """
            )
            self._dict_cache = [dict(r) for r in rows]
        return self._dict_cache

    async def classify(self, violation_behavior: str) -> dict:
        entries = await self._load_dict()

        internal_ids: list[str] = []
        display_tags: list[str] = []
        for entry in entries:
            for kw in entry["keywords"] or []:
                if kw and kw in violation_behavior:
                    internal_ids.append(entry["risk_type_id"])
                    display_tags.extend(entry["display_tags"] or [])
                    break

        method = "rule"
        if not internal_ids and self.llm is not None:
            internal_ids = await self._llm_classify(violation_behavior, entries)
            method = "llm"
            id_map = {e["risk_type_id"]: e for e in entries}
            for iid in internal_ids:
                if iid in id_map:
                    display_tags.extend(id_map[iid]["display_tags"] or [])

        cn_tags = predict_cn_tags_by_keywords(violation_behavior)
        display_tags = normalize_cn_tags(list(display_tags) + cn_tags)
        if cn_tags and method == "rule":
            method = "rule+cn_dict"

        internal_ids = list(dict.fromkeys(internal_ids))[:5]
        competition_ids = list(dict.fromkeys(
            [cid for cid in (map_internal_to_competition(i) for i in internal_ids) if cid]
            + cn_tags_to_competition_ids(display_tags)
        ))
        return {
            "internal_ids": internal_ids,
            "competition_ids": competition_ids,
            "display_tags": display_tags[:5],
            "method": method,
        }

    async def _llm_classify(self, violation_behavior: str, entries: list[dict]) -> list[str]:
        level1 = [e for e in entries if e["level"] == 1]
        risk_type_list = "\n".join(f"- {e['risk_type_id']}: {e['risk_type_name']}" for e in level1)
        try:
            resp = self.llm.complete(
                RISK_TAG_PROMPT.format(
                    violation_behavior=violation_behavior[:500],
                    risk_type_list=risk_type_list,
                ),
                max_tokens=100,
                temperature=0.1,
                json_mode=True,
                thinking=ThinkingMode.DISABLED,
            )
            data = json.loads(resp)
            valid = {e["risk_type_id"] for e in level1}
            return [i for i in data.get("risk_type_ids", []) if i in valid]
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM tag classify failed: %s", e)
            return []
