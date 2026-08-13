"""CE Top-K 后 LLM 列表重排 + 减枝。"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from engine.llm.prompts import LISTWISE_RERANK_PROMPT
from engine.retrieval.base import SearchResult

logger = logging.getLogger(__name__)
_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _parse_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK.search(text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}


def _cases_block(candidates: list[SearchResult], doc_max_chars: int = 280) -> str:
    lines: list[str] = []
    for i, c in enumerate(candidates, 1):
        vb = (c.violation_behavior or "").strip().replace("\n", " ")
        if len(vb) > doc_max_chars:
            vb = vb[: doc_max_chars - 1] + "…"
        tags = "、".join((c.risk_tags or [])[:5])
        lines.append(
            f"{i}. case_id={c.case_id}\n"
            f"   当事人：{(c.party_name or '')[:40]}\n"
            f"   风险标签：{tags or '无'}\n"
            f"   违法事实：{vb or '无'}"
        )
    return "\n".join(lines)


def apply_listwise_order(
    candidates: list[SearchResult],
    ordered_ids: list[str],
    *,
    keep_min: int,
    keep_max: int,
) -> list[SearchResult]:
    """按 LLM 给出的 id 顺序重排；非法/缺失 id 忽略，不足 keep_min 时用原序补齐。"""
    by_id = {c.case_id: c for c in candidates}
    seen: set[str] = set()
    ordered: list[SearchResult] = []
    for cid in ordered_ids:
        cid = str(cid).strip()
        if not cid or cid in seen or cid not in by_id:
            continue
        ordered.append(by_id[cid])
        seen.add(cid)
        if len(ordered) >= keep_max:
            break

    if len(ordered) < keep_min:
        for c in candidates:
            if c.case_id in seen:
                continue
            ordered.append(c)
            seen.add(c.case_id)
            if len(ordered) >= keep_min:
                break

    if not ordered:
        return candidates[: max(keep_min, min(keep_max, len(candidates)))]
    return ordered[:keep_max]


class LlmListwiseReranker:
    def __init__(
        self,
        llm_client,
        *,
        keep_min: int = 3,
        keep_max: int = 10,
        doc_max_chars: int = 280,
    ):
        self.llm = llm_client
        self.keep_min = max(1, int(keep_min))
        self.keep_max = max(self.keep_min, int(keep_max))
        self.doc_max_chars = doc_max_chars

    async def rerank(
        self,
        query_text: str,
        candidates: list[SearchResult],
        *,
        top_k: int | None = None,
    ) -> list[SearchResult]:
        if not candidates or self.llm is None:
            return candidates[: (top_k or self.keep_max)]

        keep_max = min(self.keep_max, top_k or self.keep_max, len(candidates))
        keep_min = min(self.keep_min, keep_max)
        prompt = LISTWISE_RERANK_PROMPT.format(
            query_text=query_text,
            cases_block=_cases_block(candidates, self.doc_max_chars),
            keep_min=keep_min,
            keep_max=keep_max,
        )
        try:
            raw = await asyncio.to_thread(
                self.llm.complete,
                prompt,
                max_tokens=600,
                temperature=0.0,
                json_mode=True,
            )
            data = _parse_json(raw)
            ordered_ids = data.get("ordered_case_ids") or data.get("ordered") or []
            if not isinstance(ordered_ids, list):
                ordered_ids = []
            out = apply_listwise_order(
                candidates,
                [str(x) for x in ordered_ids],
                keep_min=keep_min,
                keep_max=keep_max,
            )
            for i, r in enumerate(out):
                # 列表位次转为伪分，便于下游展示
                r.score = float(keep_max - i)
            return out
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM listwise rerank failed, keep CE order: %s", e)
            return candidates[:keep_max]
