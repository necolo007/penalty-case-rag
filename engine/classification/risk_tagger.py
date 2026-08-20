"""风险标签归类：默认与任务二评测对齐（中文 27 类 LLM + refine）。

无 LLM 时回退：三级词典规则 + 中文关键词 + refine。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import asyncpg

from engine.classification.competition_label_map import (
    CANONICAL_CN_TAGS,
    cn_tags_to_competition_ids,
    format_cn_tag_guide_for_prompt,
    normalize_cn_tags,
    predict_cn_tags_by_keywords,
    refine_cn_tags,
)
from engine.classification.tag_mapper import map_internal_to_competition
from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import RISK_CN_SYSTEM_PROMPT, RISK_CN_USER_PROMPT, RISK_TAG_PROMPT

logger = logging.getLogger(__name__)


def _parse_json_obj(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def predict_cn_tags_with_llm(llm: Any, violation_behavior: str) -> list[str]:
    """与 scripts/eval_labels.py --with-llm 相同的中文 27 类打标。"""
    text = (violation_behavior or "").strip()
    if not text:
        return ["其他"]
    resp = llm.complete(
        RISK_CN_USER_PROMPT.format(
            tag_list="、".join(CANONICAL_CN_TAGS),
            tag_guide=format_cn_tag_guide_for_prompt(max_chars=2800),
            violation_behavior=text[:3500],
        ),
        system=RISK_CN_SYSTEM_PROMPT,
        max_tokens=400,
        temperature=0.1,
        json_mode=True,
        thinking=ThinkingMode.DISABLED,
    )
    data = _parse_json_obj(resp)
    tags = data.get("risk_tags") or []
    if not isinstance(tags, list):
        tags = []
    return refine_cn_tags(normalize_cn_tags([str(t) for t in tags]), text)


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

    async def classify(self, violation_behavior: str, *, prefer_llm: bool = True) -> dict:
        from core.config import get_settings

        settings = get_settings()
        text = violation_behavior or ""
        method = "rule"
        internal_ids: list[str] = []
        display_tags: list[str] = []

        if prefer_llm and self.llm is not None and text.strip():
            try:
                display_tags = predict_cn_tags_with_llm(self.llm, text)
                method = "llm_cn"
            except Exception as e:  # noqa: BLE001
                logger.warning("LLM CN tag classify failed, fallback to rules: %s", e)

        if not display_tags:
            display_tags, internal_ids, method = await self._classify_by_rules(text, settings)

        cap = max(int(getattr(settings, "CN_TAG_CASE_MAX", 12) or 12), 1)
        display_tags = refine_cn_tags(display_tags, text)[:cap]
        internal_ids = list(dict.fromkeys(internal_ids))[:5]
        competition_ids = cn_tags_to_competition_ids(display_tags)
        if not competition_ids:
            competition_ids = list(dict.fromkeys(
                cid for cid in (map_internal_to_competition(i) for i in internal_ids) if cid
            ))
        return {
            "internal_ids": internal_ids,
            "competition_ids": competition_ids[: settings.RISK_ID_CAP],
            "display_tags": display_tags,
            "method": method,
        }

    async def _classify_by_rules(self, violation_behavior: str, settings) -> tuple[list[str], list[str], str]:
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
            internal_ids = await self._llm_classify_r_codes(violation_behavior, entries)
            method = "llm"
            id_map = {e["risk_type_id"]: e for e in entries}
            for iid in internal_ids:
                if iid in id_map:
                    display_tags.extend(id_map[iid]["display_tags"] or [])

        cn_tags = predict_cn_tags_by_keywords(
            violation_behavior, max_tags=settings.CN_TAG_PREDICT_MAX,
        )
        rule_tags = normalize_cn_tags(display_tags)
        if not rule_tags:
            display_tags = cn_tags
            if cn_tags:
                method = "cn_dict"
        else:
            extras = [t for t in cn_tags if t not in rule_tags][:2]
            display_tags = rule_tags + extras
            if extras:
                method = "rule+cn_dict"
            else:
                display_tags = rule_tags
        return normalize_cn_tags(display_tags), internal_ids, method

    async def _llm_classify_r_codes(self, violation_behavior: str, entries: list[dict]) -> list[str]:
        """旧兜底：仅在中文 LLM 失败且规则为空时，用 R00x 提示词补内部 ID。"""
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
            logger.warning("LLM R-code tag classify failed: %s", e)
            return []
