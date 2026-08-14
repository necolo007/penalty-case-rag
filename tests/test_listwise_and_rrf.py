"""LLM listwise 与 raw/rewrite RRF pair 辅助单测。"""

from engine.retrieval.base import SearchResult
from engine.retrieval.llm_listwise import apply_listwise_order
from engine.retrieval.merger import reciprocal_rank_fusion
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


def test_raw_rewrite_rrf_pair_sums_to_one():
    from core.config import Settings

    s = Settings()
    w = s.with_raw_rewrite_rrf_pair(0.4)
    assert abs(w["dense_raw"] + w["dense"] - 1.0) < 1e-9
    assert w["dense_raw"] == 0.4
    assert w["dense"] == 0.6


def test_m3_rrf_weights_defaults():
    from core.config import Settings

    s = Settings()
    w = s.m3_rrf_channel_weights()
    assert set(w) >= {"dense", "dense_raw", "sparse"}


def test_weighted_rrf_prefers_higher_weight_channel():
    """改写权重更高时，仅出现在改写通道的案应压过仅出现在原文通道的案。"""
    channel_results = {
        "dense_raw": [_sr("R1", 0.9), _sr("BOTH", 0.8), _sr("R2", 0.7)],
        "dense": [_sr("W1", 0.9), _sr("BOTH", 0.85), _sr("W2", 0.7)],
    }
    fused_hi_rw = reciprocal_rank_fusion(
        channel_results, k=60, top_k=5,
        weights={"dense_raw": 0.2, "dense": 0.8},
        multi_channel_bonus=0.0,
    )
    fused_hi_raw = reciprocal_rank_fusion(
        channel_results, k=60, top_k=5,
        weights={"dense_raw": 0.8, "dense": 0.2},
        multi_channel_bonus=0.0,
    )
    ids_rw = [r.case_id for r in fused_hi_rw]
    ids_raw = [r.case_id for r in fused_hi_raw]
    assert ids_rw.index("W1") < ids_rw.index("R1")
    assert ids_raw.index("R1") < ids_raw.index("W1")
    # 双通道命中通常仍最靠前
    assert fused_hi_rw[0].case_id == "BOTH"


def test_m3_fuse_channels_modes():
    # 最小 stub：不初始化真实依赖
    obj = object.__new__(M3HybridRetriever)
    obj.fusion_size = 10
    obj.rrf_k = 60
    obj.multi_channel_bonus = 0.0
    obj.channel_weights = {"dense_raw": 0.4, "dense": 0.6, "sparse": 0.0}
    obj.fusion_mode = "max_merge"

    raw = [_sr("A", 0.5), _sr("B", 0.4)]
    rw = [_sr("A", 0.9), _sr("C", 0.8)]
    channels = {"dense_raw": raw, "dense": rw, "sparse": []}

    obj.fusion_mode = "max_merge"
    fused_max = M3HybridRetriever._fuse_max_merge(obj, channels)
    assert fused_max[0].case_id == "A"
    assert abs(fused_max[0].score - 0.9) < 1e-9

    obj.fusion_mode = "weighted_rrf"
    fused_rrf = M3HybridRetriever._fuse_weighted_rrf(obj, channels)
    assert {r.case_id for r in fused_rrf} >= {"A", "B", "C"}
