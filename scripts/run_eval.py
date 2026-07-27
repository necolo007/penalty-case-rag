"""一键重跑任务1/2/3 评测并写汇总报告。

用法：
  python scripts/run_eval.py
  python scripts/run_eval.py --retrieval-limit 50 --rerank
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> None:
    print("\n>>", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="重跑任务1/2/3评测")
    parser.add_argument("--extract-limit", type=int, default=100)
    parser.add_argument("--label-limit", type=int, default=500)
    parser.add_argument("--retrieval-limit", type=int, default=50)
    parser.add_argument("--rerank", action="store_true", help="任务3启用精排")
    parser.add_argument("--skip-retrieval", action="store_true")
    parser.add_argument("--skip-extract", action="store_true")
    parser.add_argument("--skip-labels", action="store_true")
    args = parser.parse_args()

    py = sys.executable
    summary: dict = {
        "evaluated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "config": {
            "extract_limit": args.extract_limit,
            "label_limit": args.label_limit,
            "retrieval_limit": args.retrieval_limit,
            "rerank": args.rerank,
        },
    }

    if not args.skip_extract:
        _run([py, "scripts/reextract_for_eval.py", "--limit", str(args.extract_limit)])
        _run([
            py, "scripts/eval_extraction.py",
            "--extracted", "data/eval/extracted_cases.jsonl",
            "--gold", "data/eval/gold_extraction_cases.jsonl",
            "--output", "data/eval/extraction_eval_report.json",
        ])
        summary["task1"] = json.loads(
            (_ROOT / "data/eval/extraction_eval_report.json").read_text(encoding="utf-8")
        )

    if not args.skip_labels:
        _run([py, "scripts/eval_labels.py", "--limit", str(args.label_limit)])
        summary["task2"] = {
            k: v for k, v in json.loads(
                (_ROOT / "data/eval/label_eval_report.json").read_text(encoding="utf-8")
            ).items() if k != "per_tag"
        }

    if not args.skip_retrieval:
        extra = ["--rerank"] if args.rerank else []
        for split in ("train", "test"):
            _run([
                py, "scripts/eval_retrieval_local.py",
                "--split", split,
                "--limit", str(args.retrieval_limit),
                *extra,
            ])
            tag = "rerank" if args.rerank else "norerank"
            report = json.loads(
                (_ROOT / f"data/eval/eval_report_{split}_{tag}.json").read_text(encoding="utf-8")
            )
            summary[f"task3_{split}_{tag}"] = {
                k: v for k, v in report.items() if k != "per_query"
            }

    out = _ROOT / "data/eval/eval_summary_latest.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 人类可读摘要
    md = _ROOT / "data/eval/评测报告_最新.md"
    lines = [
        f"# penalty-case-rag 评测报告（复测）",
        "",
        f"> 评测时间：{summary['evaluated_at']}",
        f"> 配置：extract={args.extract_limit}, labels={args.label_limit}, "
        f"retrieval={args.retrieval_limit}, rerank={args.rerank}",
        "",
    ]
    if "task1" in summary:
        t1 = summary["task1"]
        lines += [
            "## 任务1 字段抽取",
            "",
            f"- macro F1：**{t1.get('macro_f1')}**",
            f"- 保险识别准确率：**{t1.get('insurance_classification_accuracy')}**",
            "",
        ]
        for f in ("party_name", "penalty_doc_no", "violation_behavior",
                  "penalty_content", "regulator", "institution_type"):
            m = t1.get(f) or {}
            lines.append(f"- {f}: P={m.get('precision')} R={m.get('recall')} F1={m.get('f1')}")
        lines.append("")
    if "task2" in summary:
        t2 = summary["task2"]
        lines += [
            "## 任务2 风险标签",
            "",
            f"- 中文 macro F1：**{t2.get('macro_f1')}**",
            f"- exact match：**{t2.get('label_exact_match_accuracy')}**",
            f"- partial hit：**{t2.get('label_partial_hit_rate')}**",
            f"- Jaccard：**{t2.get('label_mean_jaccard')}**",
            f"- R00x macro F1：**{t2.get('competition_id_macro_f1')}** "
            f"(P={t2.get('competition_id_precision')}, R={t2.get('competition_id_recall')})",
            "",
        ]
    for key, title in (
        ("task3_train_norerank", "任务3 检索 · train · 无精排"),
        ("task3_train_rerank", "任务3 检索 · train · 有精排"),
        ("task3_test_norerank", "任务3 检索 · test · 无精排"),
        ("task3_test_rerank", "任务3 检索 · test · 有精排"),
    ):
        if key not in summary:
            continue
        t = summary[key]
        lines += [
            f"## {title}",
            "",
            f"- n={t.get('evaluated')}",
            f"- Top-1：**{t.get('top1_hit')}**",
            f"- MRR：**{t.get('mrr')}**",
            f"- Recall@5：**{t.get('recall@5')}**",
            f"- Recall@10：**{t.get('recall@10')}**",
            f"- NDCG@5：**{t.get('ndcg@5')}**",
            "",
        ]
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSummary JSON → {out}")
    print(f"Summary MD   → {md}")


if __name__ == "__main__":
    main()
