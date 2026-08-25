"""对比两份任务二评测报告，定位逐标签变化（few-shot A/B / 模型迭代报告用）。

用法：
  python scripts/compare_label_reports.py \\
    --base data/eval/label_eval_task2_test_nofs.json \\
    --new  data/eval/label_eval_task2_test_fs.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_OVERALL_KEYS = (
    "label_accuracy",
    "label_partial_hit_rate",
    "label_mean_jaccard",
    "macro_f1",
    "competition_id_macro_f1",
)


def _load(path: str) -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = _ROOT / p
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="对比两份任务二标签评测报告")
    parser.add_argument("--base", required=True, help="基线报告（如 --no-fewshot）")
    parser.add_argument("--new", required=True, help="对比报告（如 --fewshot）")
    parser.add_argument("--top", type=int, default=12, help="逐标签变化展示条数")
    parser.add_argument("--output", default=None, help="可选：写出 JSON 对比结果")
    args = parser.parse_args()

    base, new = _load(args.base), _load(args.new)
    b_tags, n_tags = base["risk_tags"], new["risk_tags"]

    overall = {
        key: {
            "base": b_tags.get(key, base.get(key)),
            "new": n_tags.get(key, new.get(key)),
            "delta": round(
                (n_tags.get(key, new.get(key)) or 0) - (b_tags.get(key, base.get(key)) or 0), 4
            ),
        }
        for key in _OVERALL_KEYS
    }

    b_per, n_per = b_tags.get("per_tag", {}), n_tags.get("per_tag", {})
    per_tag = []
    for tag in sorted(set(b_per) | set(n_per)):
        bf = (b_per.get(tag) or {}).get("f1", 0.0)
        nf = (n_per.get(tag) or {}).get("f1", 0.0)
        support = (n_per.get(tag) or b_per.get(tag) or {})
        per_tag.append({
            "tag": tag,
            "base_f1": bf,
            "new_f1": nf,
            "delta": round(nf - bf, 4),
            "support": support.get("tp", 0) + support.get("fn", 0),
        })
    per_tag.sort(key=lambda r: r["delta"])

    result = {
        "base": {"file": args.base, "split": base.get("split"),
                 "fewshot": base.get("fewshot"), "evaluated": base.get("evaluated")},
        "new": {"file": args.new, "split": new.get("split"),
                "fewshot": new.get("fewshot"), "evaluated": new.get("evaluated")},
        "overall": overall,
        "improved": [r for r in reversed(per_tag) if r["delta"] > 0][: args.top],
        "regressed": [r for r in per_tag if r["delta"] < 0][: args.top],
        "unchanged": sum(1 for r in per_tag if r["delta"] == 0),
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        out = Path(args.output)
        if not out.is_absolute():
            out = _ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Diff → {out}")


if __name__ == "__main__":
    main()
