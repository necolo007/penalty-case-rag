"""审查意见生成器：基于检索案例生成可追溯的合规审查意见（JSON 输出）。

原则：所有结论必须附带检索案例引用，不得凭空生成。
"""

import json
import logging
import re

from engine.classification.competition_label_map import (
    CANONICAL_CN_TAGS,
    format_cn_tag_guide_for_prompt,
    normalize_cn_tags,
)
from engine.llm.client import DeepSeekClient, ThinkingMode
from engine.llm.prompts import MATERIAL_SUGGESTION_PROMPT, REVIEW_PROMPT
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
            risk_type_list="、".join(CANONICAL_CN_TAGS),
            risk_tag_guide=format_cn_tag_guide_for_prompt(),
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
        if result.get("risk_types"):
            result["risk_types"] = normalize_cn_tags(list(result["risk_types"]))
        return result

    def generate_material_suggestion(
        self,
        material_text: str,
        risk_items: list[dict],
    ) -> str:
        """对整份审查材料生成唯一整改建议（对象=材料原文，不是处罚案例）。"""
        if not (material_text or "").strip():
            return ""
        if not risk_items:
            return "未识别到明确风险语句；建议人工通读材料，避免收益承诺、绝对化表述与合同外利益诱导。"

        blocks: list[str] = []
        for i, item in enumerate(risk_items, 1):
            text = (item.get("text") or "").strip()
            tags = "、".join(item.get("risk_types") or []) or "未标注"
            blocks.append(f"{i}. 风险类型：{tags}\n   原文：{text[:300]}")

        prompt = MATERIAL_SUGGESTION_PROMPT.format(
            material_text=material_text[:6000],
            risk_blocks="\n".join(blocks),
        )
        try:
            raw = self.llm.complete(
                prompt,
                max_tokens=700,
                temperature=0.2,
                json_mode=True,
                thinking=ThinkingMode.DISABLED,
            )
            data = self._parse_response(raw)
            suggestion = (data.get("suggestion") or "").strip()
            if suggestion:
                return suggestion
        except Exception as e:  # noqa: BLE001
            logger.warning("Material suggestion generation failed: %s", e)

        # 降级：合并句级「改材料」建议
        parts = [
            (item.get("suggestion") or "").strip()
            for item in risk_items
            if (item.get("suggestion") or "").strip()
        ]
        uniq = list(dict.fromkeys(parts))
        if uniq:
            return "\n".join(f"{i}. {s}" for i, s in enumerate(uniq, 1))
        return "请针对材料中已标红的风险语句删除或改写违规表述，完整披露风险与除外责任，不以合同外利益诱导投保。"

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
            "suggestion": "建议删除或改写待审查语句中可能构成销售误导、收益承诺或合同外利益的表述，并完整披露风险与除外责任。",
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
