"""SparseLexicalIndex 基础单测（无 GPU / 无 FlagEmbedding）。"""

from engine.retrieval.sparse_index import SparseLexicalIndex


def test_sparse_search_inner_product():
    idx = SparseLexicalIndex()
    idx.upsert("a", {"保险": 1.0, "误导": 0.5})
    idx.upsert("b", {"保险": 0.8})
    idx.upsert("c", {"合同": 1.0})
    hits = idx.search({"保险": 1.0, "误导": 1.0}, top_k=2)
    assert hits[0][0] == "a"
    assert hits[0][1] == 1.5
    assert hits[1][0] == "b"


def test_sparse_upsert_replace():
    idx = SparseLexicalIndex()
    idx.upsert("a", {"保险": 1.0})
    idx.upsert("a", {"误导": 2.0})
    assert idx.search({"保险": 1.0}, 5) == []
    assert idx.search({"误导": 1.0}, 5)[0] == ("a", 2.0)
