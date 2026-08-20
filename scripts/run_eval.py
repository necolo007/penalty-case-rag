"""一键重跑任务1/2/3 评测并写汇总报告（默认对齐生产 hybrid/LLM/listwise 口径）。

用法：
  python scripts/run_eval.py
  python scripts/run_eval.py --retrieval-limit 50
  python scripts/run_eval.py --skip-extract --skip-labels   # 仅检索
  python scripts/run_eval.py --cheap   # 离线可复现：任务1 regex、任务2 无 LLM、检索无 rewrite/listwise
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# 与 data/eval/README.md「当前有效」对齐
T1_GOLD = "data/eval/gold_extraction_521_cleaned.jsonl"
T1_EXTRACTED = "data/eval/extracted_cases_hybrid_521.jsonl"
T1_REPORT = "data/eval/extraction_eval_hybrid_521_cleaned_bert.json"
T2_GOLD = "data/eval/gold_task2_820_cleaned.jsonl"
T2_PRED = "data/eval/predicted_risk_tags_820_llm.jsonl"
T2_REPORT = "data/eval/label_eval_report_820_llm.json"


def _run(cmd: list[str]) -> None:
    print("\n>>", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="重跑任务1/2/3评测（默认对齐生产）")
    parser.add_argument("--extract-limit", type=int, default=None, help="任务1 file_id 上限；默认全量")
    parser.add_argument("--label-limit", type=int, default=None, help="任务2 条数上限；默认全量")
    parser.add_argument("--retrieval-limit", type=int, default=30)
    parser.add_argument(
        "--cheap",
        action="store_true",
        help="离线便宜模式：regex 抽取、规则标签、检索仅 CE 精排（不对齐生产最优）",
    )
    parser.add_argument("--skip-retrieval", action="store_true")
    parser.add_argument("--skip-extract", action="store_true")
    parser.add_argument("--skip-labels", action="store_true")
    args = parser.parse_args()

    py = sys.executable
    aligned = not args.cheap
    summary: dict = {
        "evaluated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "config": {
            "aligned_with_production": aligned,
            "extract_limit": args.extract_limit,
            "label_limit": args.label_limit,
            "retrieval_limit": args.retrieval_limit,
            "cheap": args.cheap,
        },
    }

    if not args.skip_extract:
        reextract = [
            py, "scripts/reextract_for_eval.py",
            "--gold", T1_GOLD,
            "--output", T1_EXTRACTED,
        ]
        if args.extract_limit is not None:
            reextract += ["--limit", str(args.extract_limit)]
        if aligned:
            reextract += ["--mode", "llm_first", "--with-llm"]
        else:
            reextract += ["--mode", "regex_first"]
        _run(reextract)
        _run([
            py, "scripts/eval_extraction.py",
            "--extracted", T1_EXTRACTED,
            "--gold", T1_GOLD,
            "--output", T1_REPORT,
        ])
        summary["task1"] = json.loads((_ROOT / T1_REPORT).read_text(encoding="utf-8"))

    if not args.skip_labels:
        label_cmd = [
            py, "scripts/eval_labels.py",
            "--gold", T2_GOLD,
            "--extracted", T1_EXTRACTED,
            "--output", T2_REPORT,
            "--predictions-out", T2_PRED,
        ]
        if args.label_limit is not None:
            label_cmd += ["--limit", str(args.label_limit)]
        if aligned:
            label_cmd.append("--with-llm")
        _run(label_cmd)
        summary["task2"] = {
            k: v for k, v in json.loads((_ROOT / T2_REPORT).read_text(encoding="utf-8")).items()
            if k != "per_tag" and k != "risk_tags"
        }

    if not args.skip_retrieval:
        for split in ("test",):
            ret = [
                py, "scripts/eval_retrieval_local.py",
                "--split", split,
                "--limit", str(args.retrieval_limit),
                "--rerank",
                "--backend", "bge_m3",
            ]
            if aligned:
                ret += ["--llm-rewrite", "--llm-listwise"]
            _run(ret)
            # eval_retrieval_local 命名随参数变化；优先 listwise 报告
            candidates = [
                _ROOT / f"data/eval/eval_report_{split}_vb_summary_n{args.retrieval_limit}_listwise.json",
                _ROOT / f"data/eval/eval_report_{split}_rerank.json",
                _ROOT / f"data/eval/eval_report_test_vb_summary_n30.json",
                _ROOT / f"data/eval/eval_report_test_vb_summary_n30_listwise.metrics.json",
            ]
            report_path = next((p for p in candidates if p.exists()), None)
            if report_path is None:
                # 回退：读 submission 旁 metrics
                metrics = _ROOT / "data/eval" / f"submission_test_vb_summary_n{args.retrieval_limit}_listwise.metrics.json"
                if metrics.exists():
                    report_path = metrics
            if report_path and report_path.exists():
                report = json.loads(report_path.read_text(encoding="utf-8"))
                summary[f"task3_{split}"] = {
                    k: v for k, v in report.items() if k != "per_query"
                }
                summary[f"task3_{split}_report"] = str(report_path)

    out = _ROOT / "data/eval/eval_summary_latest.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md = _ROOT / "data/eval/评测报告_最新.md"
    lines = [
        "# penalty-case-rag 评测报告（复测）",
        "",
        f"> 评测时间：{summary['evaluated_at']}",
        f"> 对齐生产：{aligned}；extract_limit={args.extract_limit}, "
        f"label_limit={args.label_limit}, retrieval_limit={args.retrieval_limit}",
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
    if "task2" in summary:
        t2 = summary["task2"]
        lines += [
            "## 任务2 风险标签",
            "",
            f"- exact：**{t2.get('label_exact_match_accuracy') or t2.get('label_accuracy')}**",
            f"- macro F1：**{t2.get('macro_f1')}**",
            f"- R00x F1：**{t2.get('competition_id_macro_f1')}**",
            "",
        ]
        cs = t2.get("case_summary") or {}
        if cs.get("f1") is not None:
            lines.append(f"- case_summary BERT F1：**{cs.get('f1')}**")
            lines.append("")
    if any(k.startswith("task3_") for k in summary):
        lines += ["## 任务3 检索", ""]
        for k, v in summary.items():
            if k.startswith("task3_") and isinstance(v, dict):
                lines.append(f"- {k}: {json.dumps(v, ensure_ascii=False)[:200]}")
        lines.append("")
    lines += [
        "## 任务4 合规审查",
        "",
        "- 无独立自动金标；复用任务3 检索引擎（含 listwise 默认开启）。",
        "",
    ]
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSummary → {out}")
    print(f"Report  → {md}")


if __name__ == "__main__":
    main()
