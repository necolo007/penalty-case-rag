from engine.retrieval.base import SearchResult
from engine.retrieval.merger import reciprocal_rank_fusion


def make_result(case_id: str, channel: str, score: float = 1.0) -> SearchResult:
    return SearchResult(
        case_id=case_id, party_name=f"公司{case_id}", violation_behavior="违法行为",
        penalty_content="罚款", regulator="监管局", risk_tags=[], score=score,
        channels=[channel],
    )


def test_rrf_merges_channels_and_dedupes():
    channel_results = {
        "bm25": [make_result("C1", "bm25"), make_result("C2", "bm25")],
        "vector": [make_result("C2", "vector"), make_result("C3", "vector")],
    }
    merged = reciprocal_rank_fusion(channel_results, top_k=10)

    ids = [r.case_id for r in merged]
    assert len(ids) == len(set(ids)) == 3
    # C2 在两路都命中，融合分最高
    assert ids[0] == "C2"
    c2 = merged[0]
    assert set(c2.channels) == {"bm25", "vector"}


def test_rrf_respects_top_k():
    channel_results = {
        "bm25": [make_result(f"C{i}", "bm25") for i in range(20)],
    }
    merged = reciprocal_rank_fusion(channel_results, top_k=5)
    assert len(merged) == 5


def test_rrf_empty_input():
    assert reciprocal_rank_fusion({"bm25": [], "vector": []}) == []
