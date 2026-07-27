"""基于 example 抽样清单评测 InsuranceFilter（文件名弱标签，不依赖 DB）。

用法：python scripts/eval_example_filter.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.classification.insurance_filter import InsuranceFilter


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


def main() -> None:
    parser = argparse.ArgumentParser(description="example 语料筛选弱标签评测")
    parser.add_argument("--manifest", default="data/eval/example/example_filter_eval.jsonl")
    parser.add_argument("--dict-dir", default="data/dictionaries")
    parser.add_argument("--out", default="data/eval/example/example_filter_eval_report.json")
    args = parser.parse_args()

    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = _ROOT / manifest
    if not manifest.exists():
        raise FileNotFoundError(f"清单不存在: {manifest}（先运行 build_example_testset.py）")

    dict_dir = Path(args.dict_dir)
    if not dict_dir.is_absolute():
        dict_dir = _ROOT / dict_dir
    filt = InsuranceFilter(dict_dir=dict_dir)

    tp = fp = tn = fn = 0
    details = []
    for row in load_jsonl(manifest):
        expected = row.get("expected_is_insurance")
        if expected is None:
            continue
        name = row.get("file_name") or ""
        score = filt.score(name, "", "")
        # 仅文件名时：主体命中即视为保险相关
        pred = score.is_insurance or (score.entity > 0 and score.exclude == 0)
        if expected and pred:
            tp += 1
        elif expected and not pred:
            fn += 1
        elif (not expected) and pred:
            fp += 1
        else:
            tn += 1
        if pred != expected:
            details.append({
                "sample_id": row.get("sample_id"),
                "file_name": name[:120],
                "expected": expected,
                "predicted": pred,
                "final": round(score.final, 3),
                "reasons": score.reasons[:5],
            })

    precision, recall, f1 = _prf(tp, fp, fn)
    report = {
        "n": tp + fp + tn + fn,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "errors_shown": details[:40],
        "error_count": len(details),
        "note": "weak_label 来自文件名启发式，仅作回归基线。",
    }
    out = Path(args.out)
    if not out.is_absolute():
        out = _ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("n", "precision", "recall", "f1", "tp", "fp", "tn", "fn")},
                     ensure_ascii=False))
    print(f"Report → {out}")


if __name__ == "__main__":
    main()
