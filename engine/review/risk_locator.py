"""风险句定位：规则 → 词典 → 可选 LLM。跳过法条引用与程序性套话。"""

import json
import logging
import re
from dataclasses import dataclass, field

import asyncpg

from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import RISK_SENTENCE_PROMPT
from engine.review.risk_rules import match_risk_rules
from engine.review.segmenter import Sentence

logger = logging.getLogger(__name__)

# 决定书/材料中的法条依据、程序告知——不是待审查的风险行为句
_NON_RISK_SENTENCE_RE = re.compile(
    r"("
    r"上述行为违反了|"
    r"违反了《|"
    r"依据《|"
    r"根据《|"
    r"依照《|"
    r"适用《|"
    r"第[一二三四五六七八九十百零〇\d]+条|"
    r"现依据|"
    r"决定如下|"
    r"责令改正|"
    r"作出如下处罚|"
    r"本决定书|"
    r"如不服本决定|"
    r"申请行政复议|"
    r"提起行政诉讼|"
    r"特此公告|"
    r"联系地址|"
    r"邮\s*编|"
    r"本机关地址"
    r")"
)


def is_non_risk_boilerplate(text: str) -> bool:
    """法条引用、处罚决定套话等，不应作为风险语句。"""
    t = (text or "").strip()
    if not t:
        return True
    if _NON_RISK_SENTENCE_RE.search(t):
        # 「行为事实 + 法条」合句且足够长时，留给规则/词典判断
        behavior_cues = (
            "虚列", "套取", "赠送", "返佣", "保本", "承诺收益", "欺骗投保",
            "销售误导", "虚假宣传", "隐瞒", "诱导", "电销",
        )
        if any(c in t for c in behavior_cues) and len(t) > 80:
            return False
        return True
    return False


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
            # 切分失败时可能把整张信息公开表粘成超长「一句」；跳过以免全文标红
            if len(sent.text) > 400:
                logger.debug("skip oversized segment (%s chars)", len(sent.text))
                continue
            if is_non_risk_boilerplate(sent.text):
                continue

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
