"""风险句定位：三重判断。

① 高危词规则（确定性，最快）
② 同义词词典命中（业务口语 → 风险类型）
③ LLM 辅助判断（规则未覆盖的隐含风险，可关闭以控制成本）
"""

import json
import logging
from dataclasses import dataclass, field

import asyncpg

from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import RISK_SENTENCE_PROMPT
from engine.review.risk_rules import match_risk_rules
from engine.review.segmenter import Sentence

logger = logging.getLogger(__name__)


@dataclass
class RiskSentence:
    sentence: Sentence
    risk_type_ids: list[str]
    severity: str                     # high / medium / low
    detection_method: str             # rule / dict / llm
    reasons: list[str] = field(default_factory=list)


class RiskSentenceLocator:
    def __init__(self, pool: asyncpg.Pool, llm_client: DeepSeekClient | None = None,
                 llm_enabled: bool = True, min_sentence_len: int = 6):
        self.pool = pool
        self.llm = llm_client
        self.llm_enabled = llm_enabled
        self.min_sentence_len = min_sentence_len

    async def _dict_hits(self, text: str) -> list[dict]:
        rows = await self.pool.fetch(
            """
            SELECT business_term, risk_type_id FROM synonym_dictionary
            WHERE risk_type_id IS NOT NULL AND $1 LIKE '%' || business_term || '%'
            """,
            text,
        )
        return [dict(r) for r in rows]

    async def locate(self, sentences: list[Sentence], scene: str | None = None) -> list[RiskSentence]:
        risky: list[RiskSentence] = []
        for sent in sentences:
            if sent.is_heading or len(sent.text) < self.min_sentence_len:
                continue

            # ① 高危词规则
            rule_hits = match_risk_rules(sent.text, scene=scene)
            if rule_hits:
                severity = "high" if any(h.severity == "high" for h in rule_hits) else "medium"
                risky.append(RiskSentence(
                    sentence=sent,
                    risk_type_ids=list(dict.fromkeys(h.risk_type_id for h in rule_hits)),
                    severity=severity,
                    detection_method="rule",
                    reasons=[f"命中高危词：{h.matched_text}" for h in rule_hits],
                ))
                continue

            # ② 同义词词典
            dict_hits = await self._dict_hits(sent.text)
            if dict_hits:
                risky.append(RiskSentence(
                    sentence=sent,
                    risk_type_ids=list(dict.fromkeys(h["risk_type_id"] for h in dict_hits)),
                    severity="medium",
                    detection_method="dict",
                    reasons=[f"命中词典：{h['business_term']}" for h in dict_hits],
                ))
                continue

            # ③ LLM 兜底（隐含风险）
            if self.llm_enabled and self.llm is not None:
                llm_result = await self._llm_judge(sent)
                if llm_result is not None:
                    risky.append(llm_result)
        return risky

    async def _llm_judge(self, sent: Sentence) -> RiskSentence | None:
        try:
            resp = self.llm.complete(
                RISK_SENTENCE_PROMPT.format(sentence=sent.text),
                max_tokens=100,
                temperature=0.1,
                json_mode=True,
                thinking=ThinkingMode.DISABLED,
            )
            data = json.loads(resp)
            if data.get("is_risky"):
                risk_id = data.get("risk_type_id") or ""
                return RiskSentence(
                    sentence=sent,
                    risk_type_ids=[risk_id] if risk_id else [],
                    severity="low",
                    detection_method="llm",
                    reasons=[data.get("reason", "LLM 判断存在隐含风险")],
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM risk judge failed for sentence: %s", e)
        return None
