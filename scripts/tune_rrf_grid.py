"""离线网格搜索：基于 dump_channels.py 缓存的四路排名列表，尝试不同
RRF_K / channel_weights / multi_channel_bonus 组合，比较 Top-60（对齐
RETRIEVAL_RERANK_CANDIDATES）命中率。不触发任何 LLM / Embedding / DB 调用，
可以放心大量组合网格搜索。

用法：python scripts/dump_channels.py --split test --limit 100   # 先落盘缓存
      python scripts/dump_channels.py --split train --limit 100
      python scripts/tune_rrf_grid.py

⚠️ 重要警告（五次优化实测得出，务必先读）：
本脚本给出的"候选池是否包含金标案例"命中率只是一个**代理指标**，与真实精排
后的 MRR/Top-1 相关性并不可靠！实测 RRF_K 60→200 在该代理指标上 test 从
27%→31%、train 77%→78%（双双"变好"），但用同一批 query 实际跑完整链路
（含 bge-reranker-v2-m3 精排，n=30）后，test MRR 0.1→0.033、train MRR
0.5→0.425，**双双明显变差**。原因：精排是逐对打分，候选池构成变化后，即使
目标案例仍在池内，也可能有新进入的候选把它挤出精排后的 Top-10。
因此：本脚本只适合快速排除"明显更差"的方向、缩小网格范围；任何看起来更优的
组合，上线前必须用 eval_retrieval_local.py --rerank 做真实端到端验证
（n>=30，且 train/test 都要看），代理指标"变好"绝不能单独作为采纳依据。
当前默认值（RRF_K=60、RRF_W_*、RETRIEVAL_RERANK_CANDIDATES=60）已经过该验证
流程确认为已知最优，本脚本本轮未能找到能通过端到端验证的更优组合。
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
for p in (_ROOT, _SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from engine.retrieval.base import SearchResult
from engine.retrieval.merger import reciprocal_rank_fusion


def _load_dump(split: str, limit: int = 100) -> dict:
    path = _ROOT / f"data/eval/_channel_dump_{split}_{limit}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _to_results(channel_case_ids: list[str]) -> list[SearchResult]:
    return [
        SearchResult(
            case_id=cid, party_name="", violation_behavior="", penalty_content="",
            regulator="", risk_tags=[], score=0.0,
        )
        for cid in channel_case_ids
    ]


def hit_rate(dump: dict, *, top_k: int, k: int, weights: dict, bonus: float) -> float:
    hits = 0
    n = 0
    for qid, entry in dump.items():
        relevant = set(entry["relevant"])
        if not relevant:
            continue
        n += 1
        channel_results = {
            ch: _to_results(ids) for ch, ids in entry["channels"].items()
        }
        fused = reciprocal_rank_fusion(
            channel_results, k=k, top_k=top_k, weights=weights, multi_channel_bonus=bonus,
        )
        if {r.case_id for r in fused} & relevant:
            hits += 1
    return hits / n if n else 0.0


def main() -> None:
    test_dump = _load_dump("test")
    train_dump = _load_dump("train")

    base_weights = {"bm25": 1.15, "vector": 1.45, "tag": 1.0, "rule": 1.2}
    base_k = 60
    base_bonus = 0.08
    top_k = 60  # 对齐 RETRIEVAL_RERANK_CANDIDATES=60（精排真正能看到的窗口）

    baseline_test = hit_rate(test_dump, top_k=top_k, k=base_k, weights=base_weights, bonus=base_bonus)
    baseline_train = hit_rate(train_dump, top_k=top_k, k=base_k, weights=base_weights, bonus=base_bonus)
    print(f"基线 (k={base_k}, weights={base_weights}, bonus={base_bonus}) @top{top_k}:")
    print(f"  test={baseline_test:.2%}  train={baseline_train:.2%}\n")

    print("=== 网格1: RRF_K ===")
    for k in (20, 30, 45, 60, 80, 100, 150):
        t = hit_rate(test_dump, top_k=top_k, k=k, weights=base_weights, bonus=base_bonus)
        tr = hit_rate(train_dump, top_k=top_k, k=k, weights=base_weights, bonus=base_bonus)
        print(f"  k={k:4d}: test={t:.2%}  train={tr:.2%}")

    print("\n=== 网格2: vector 权重 ===")
    for wv in (1.0, 1.15, 1.3, 1.45, 1.6, 1.8, 2.0, 2.5):
        w = dict(base_weights, vector=wv)
        t = hit_rate(test_dump, top_k=top_k, k=base_k, weights=w, bonus=base_bonus)
        tr = hit_rate(train_dump, top_k=top_k, k=base_k, weights=w, bonus=base_bonus)
        print(f"  w_vector={wv:.2f}: test={t:.2%}  train={tr:.2%}")

    print("\n=== 网格3: multi_channel_bonus ===")
    for b in (0.0, 0.05, 0.08, 0.12, 0.2, 0.3, 0.5):
        t = hit_rate(test_dump, top_k=top_k, k=base_k, weights=base_weights, bonus=b)
        tr = hit_rate(train_dump, top_k=top_k, k=base_k, weights=base_weights, bonus=b)
        print(f"  bonus={b:.2f}: test={t:.2%}  train={tr:.2%}")

    print("\n=== 网格4: bm25/tag/rule 权重（vector 固定在网格2最优附近） ===")
    best_wv = 1.45
    for wb, wt, wr in itertools.product((0.8, 1.15, 1.5), (0.6, 1.0, 1.4), (0.8, 1.2, 1.6)):
        w = {"bm25": wb, "vector": best_wv, "tag": wt, "rule": wr}
        t = hit_rate(test_dump, top_k=top_k, k=base_k, weights=w, bonus=base_bonus)
        tr = hit_rate(train_dump, top_k=top_k, k=base_k, weights=w, bonus=base_bonus)
        if t >= baseline_test and tr >= baseline_train - 0.01:
            print(f"  bm25={wb} vector={best_wv} tag={wt} rule={wr}: test={t:.2%}  train={tr:.2%}  <-- 不劣于基线")

    print("\n=== 网格5: RRF_K 继续放大 ===")
    for k in (150, 200, 250, 300, 400, 500, 800):
        t = hit_rate(test_dump, top_k=top_k, k=k, weights=base_weights, bonus=base_bonus)
        tr = hit_rate(train_dump, top_k=top_k, k=k, weights=base_weights, bonus=base_bonus)
        print(f"  k={k:4d}: test={t:.2%}  train={tr:.2%}")

    print("\n=== 网格6: k=150~300 叠加 bm25=1.5 ===")
    for k in (60, 100, 150, 200, 250, 300):
        w = dict(base_weights, bm25=1.5)
        t = hit_rate(test_dump, top_k=top_k, k=k, weights=w, bonus=base_bonus)
        tr = hit_rate(train_dump, top_k=top_k, k=k, weights=w, bonus=base_bonus)
        print(f"  k={k:4d} bm25=1.5: test={t:.2%}  train={tr:.2%}")

    print("\n=== 网格7: 同时看 top_k=100（RETRIEVAL_FUSION_SIZE 上限）避免只对 60 过拟合 ===")
    for k in (60, 100, 150, 200, 300):
        for wb in (1.15, 1.5):
            w = dict(base_weights, bm25=wb)
            t100 = hit_rate(test_dump, top_k=100, k=k, weights=w, bonus=base_bonus)
            tr100 = hit_rate(train_dump, top_k=100, k=k, weights=w, bonus=base_bonus)
            print(f"  k={k:4d} bm25={wb}: test@100={t100:.2%}  train@100={tr100:.2%}")


if __name__ == "__main__":
    main()
