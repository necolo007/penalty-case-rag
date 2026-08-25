"""LLM listwise 与 M3 max_merge 融合单测。"""

from engine.retrieval.base import SearchResult
from engine.retrieval.llm_listwise import apply_listwise_order
from engine.retrieval.m3_retriever import M3HybridRetriever


def _sr(cid: str, score: float = 0.0) -> SearchResult:
    return SearchResult(
        case_id=cid,
        party_name="",
        violation_behavior="",
        penalty_content="",
        regulator="",
        risk_tags=[],
        score=score,
        channels=[],
    )


def test_apply_listwise_order_prune_and_fill():
    cands = [_sr("A"), _sr("B"), _sr("C"), _sr("D"), _sr("E")]
    out = apply_listwise_order(cands, ["C", "A", "Z"], keep_min=3, keep_max=4)
    assert [x.case_id for x in out] == ["C", "A", "B"]  # B 补齐 keep_min


def test_apply_listwise_respects_keep_max():
    cands = [_sr(x) for x in "ABCDE"]
    out = apply_listwise_order(cands, list("EDCBA"), keep_min=2, keep_max=3)
    assert [x.case_id for x in out] == ["E", "D", "C"]


def test_m3_fuse_channels_max_merge():
    obj = object.__new__(M3HybridRetriever)
    obj.fusion_size = 10

    raw = [_sr("A", 0.5), _sr("B", 0.4)]
    rw = [_sr("A", 0.9), _sr("C", 0.8)]
    channels = {"dense_raw": raw, "dense": rw, "sparse": []}

    fused = M3HybridRetriever.fuse_channels(obj, channels)
    assert fused[0].case_id == "A"
    assert abs(fused[0].score - 0.9) < 1e-9
    assert {r.case_id for r in fused} >= {"A", "B", "C"}
