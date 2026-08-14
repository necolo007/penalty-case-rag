"""双路 CE：aux_query 与主 query 取 max。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from engine.retrieval.base import SearchResult
from engine.retrieval.reranker import Reranker


def _case(case_id: str) -> SearchResult:
    return SearchResult(
        case_id=case_id,
        score=0.0,
        party_name="甲公司",
        violation_behavior="虚构保险中介业务",
        penalty_content="警告并罚款",
        regulator="银保监",
        risk_tags=["虚假业务"],
        channels=["dense"],
    )


@pytest.mark.asyncio
async def test_rerank_aux_takes_max():
    rr = Reranker.__new__(Reranker)
    rr.batch_size = 8
    rr.doc_max_chars = 1200
    rr._model = MagicMock()

    # 主 query：case_a 高；aux：case_b 更高 → max 后 b 应排前
    primary = [0.2, 0.9]
    aux = [0.95, 0.1]
    call = {"n": 0}

    def _score(pairs, normalize=True, batch_size=8):  # noqa: ARG001
        call["n"] += 1
        return primary if call["n"] == 1 else aux

    rr._score_pairs = _score  # type: ignore[method-assign]

    cands = [_case("a"), _case("b")]
    out = await rr.rerank("口语话术", cands, top_k=2, aux_query_text="假想违法事实")
    assert [c.case_id for c in out] == ["a", "b"]
    assert out[0].score == pytest.approx(0.95)
    assert out[1].score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_rerank_skips_identical_aux():
    rr = Reranker.__new__(Reranker)
    rr.batch_size = 8
    rr.doc_max_chars = 1200
    n = {"c": 0}

    def _score(pairs, normalize=True, batch_size=8):  # noqa: ARG001
        n["c"] += 1
        return [0.5] * len(pairs)

    rr._score_pairs = _score  # type: ignore[method-assign]
    out = await rr.rerank("same", [_case("x")], top_k=1, aux_query_text="same")
    assert n["c"] == 1
    assert out[0].case_id == "x"
