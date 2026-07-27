"""任务2：金标 violation_behavior 规则/关键词打标评测。

用法：python scripts/eval_labels.py [--limit 500]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.db import close_pool, create_pool
from engine.classification.competition_label_map import (
    CANONICAL_CN_TAGS,
    cn_tags_to_competition_ids,
    normalize_cn_tags,
)
from engine.classification.risk_tagger import RiskTagger


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f1


async def main() -> None:
    parser = argparse.ArgumentParser(description="风险标签评测")
    parser.add_argument("--gold", default="data/eval/gold_extraction_cases.jsonl")
    parser.add_argument("--output", default="data/eval/label_eval_report.json")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    gold_path = Path(args.gold)
    if not gold_path.is_absolute():
        gold_path = _ROOT / gold_path
    rows = _load_jsonl(gold_path)
    if args.limit:
        rows = rows[: args.limit]

    pool = await create_pool()
    tagger = RiskTagger(pool, llm_client=None)

    exact = partial = 0
    jaccards: list[float] = []
    tag_tp: dict[str, int] = defaultdict(int)
    tag_fp: dict[str, int] = defaultdict(int)
    tag_fn: dict[str, int] = defaultdict(int)
    cid_tp = cid_fp = cid_fn = 0

    for item in rows:
        text = item.get("violation_behavior") or ""
        gold_tags = normalize_cn_tags(item.get("risk_tags") or [])
        gold_set = set(gold_tags)

        tags = await tagger.classify(text)
        # 与生产一致：以 RiskTagger 输出为准（内部已含词典补全）
        pred_tags = normalize_cn_tags(list(tags.get("display_tags") or []))
        pred_set = set(pred_tags)

        if pred_set == gold_set:
            exact += 1
        if pred_set & gold_set:
            partial += 1
        union = pred_set | gold_set
        jaccards.append(len(pred_set & gold_set) / len(union) if union else 1.0)

        for t in pred_set:
            if t in gold_set:
                tag_tp[t] += 1
            else:
                tag_fp[t] += 1
        for t in gold_set:
            if t not in pred_set:
                tag_fn[t] += 1

        gold_cids = set(cn_tags_to_competition_ids(gold_tags))
        pred_cids = set(tags.get("competition_ids") or []) | set(cn_tags_to_competition_ids(pred_tags))
        cid_tp += len(pred_cids & gold_cids)
        cid_fp += len(pred_cids - gold_cids)
        cid_fn += len(gold_cids - pred_cids)

    n = len(rows) or 1
    per_tag = {}
    f1s = []
    for tag in CANONICAL_CN_TAGS:
        if tag == "其他" and tag_tp[tag] + tag_fp[tag] + tag_fn[tag] == 0:
            continue
        p, r, f1 = _prf(tag_tp[tag], tag_fp[tag], tag_fn[tag])
        if tag_tp[tag] + tag_fp[tag] + tag_fn[tag] == 0:
            continue
        per_tag[tag] = {
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4),
            "tp": tag_tp[tag], "fp": tag_fp[tag], "fn": tag_fn[tag],
        }
        f1s.append(f1)

    cp, cr, cf1 = _prf(cid_tp, cid_fp, cid_fn)
    report = {
        "evaluated": len(rows),
        "label_exact_match_accuracy": round(exact / n, 4),
        "label_partial_hit_rate": round(partial / n, 4),
        "label_mean_jaccard": round(sum(jaccards) / n, 4),
        "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
        "competition_id_macro_f1": round(cf1, 4),
        "competition_id_precision": round(cp, 4),
        "competition_id_recall": round(cr, 4),
        "per_tag": per_tag,
        "note": "规则 RiskTagger + 中文关键词词典 vs 金标 risk_tags",
    }

    out = Path(args.output)
    if not out.is_absolute():
        out = _ROOT / out
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "per_tag"}, ensure_ascii=False, indent=2))
    print(f"Report → {out}")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
