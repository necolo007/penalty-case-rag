"""审查意见生成器：基于检索案例生成可追溯的合规审查意见（JSON 输出）。

原则：所有结论必须附带检索案例引用，不得凭空生成。
"""

import json
import logging
import re

from engine.classification.tag_mapper import COMPETITION_TAGS
from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import REVIEW_PROMPT
from engine.retrieval.base import SearchResult

logger = logging.getLogger(__name__)


class ReviewGenerator:
    def __init__(self, llm_client: DeepSeekClient):
        self.llm = llm_client

    @staticmethod
    def _build_case_context(cases: list[SearchResult]) -> str:
        parts = []
        for c in cases:
            parts.append(
                f"[案例 {c.case_id}]\n"
                f"  文号：{c.penalty_doc_no or 'N/A'}\n"
                f"  当事人：{c.party_name}\n"
                f"  违法行为：{c.violation_behavior}\n"
                f"  处罚内容：{c.penalty_content}\n"
                f"  监管机构：{c.regulator}\n"
                f"  风险标签：{'、'.join(c.risk_tags) or 'N/A'}\n"
                f"  来源文件：{c.source_file or 'N/A'}"
            )
        return "\n\n".join(parts)

    def generate(self, query_text: str, retrieved_cases: list[SearchResult]) -> dict:
        if not retrieved_cases:
            return {
                "risk_types": [],
                "case_analysis": [],
                "compliance_reason": "未检索到相似处罚案例，无法给出基于案例的审查意见，建议人工复核。",
                "suggestion": "",
                "confidence": 0.0,
            }

        prompt = REVIEW_PROMPT.format(
            query_text=query_text,
            case_context=self._build_case_context(retrieved_cases),
            risk_type_list="、".join(COMPETITION_TAGS.values()),
        )
        try:
            response = self.llm.complete(
                prompt,
                max_tokens=800,
                temperature=0.2,
                json_mode=True,
                thinking=ThinkingMode.DISABLED,
            )
            result = self._parse_response(response)
        except Exception as e:  # noqa: BLE001 - LLM 故障降级为纯检索结果
            logger.warning("Review generation failed, degrade to retrieval-only: %s", e)
            result = self._fallback(retrieved_cases)

        result = self._enforce_traceability(result, retrieved_cases)
        return result

    @staticmethod
    def _parse_response(response: str) -> dict:
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
            if match:
                return json.loads(match.group(1))
            return {"raw_response": response, "parse_error": True}

    @staticmethod
    def _fallback(cases: list[SearchResult]) -> dict:
        """LLM 不可用：用检索结果 + 模板理由拼装最小审查结论"""
        tags = list(dict.fromkeys(t for c in cases for t in c.risk_tags))[:3]
        return {
            "risk_types": tags,
            "case_analysis": [
                {
                    "case_id": c.case_id,
                    "penalty_doc_no": c.penalty_doc_no,
                    "similarity_reason": c.match_reason,
                    "relevance": "medium",
                }
                for c in cases[:5]
            ],
            "compliance_reason": "LLM 服务暂不可用，以下为四路检索直接返回的相似案例，请人工判断合规风险。",
            "suggestion": "建议参照相似案例的处罚事由修改相关表述。",
            "confidence": 0.3,
        }

    @staticmethod
    def _enforce_traceability(result: dict, cases: list[SearchResult]) -> dict:
        """可追溯性校验：剔除引用了不存在案例 ID 的分析条目（防 LLM 幻觉）"""
        valid_ids = {c.case_id for c in cases}
        analysis = result.get("case_analysis") or []
        result["case_analysis"] = [a for a in analysis if a.get("case_id") in valid_ids]
        if analysis and not result["case_analysis"]:
            logger.warning("All case_analysis entries referenced unknown case ids, dropped")
        return result
