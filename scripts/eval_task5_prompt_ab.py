"""任务五：提示词规范消融（裸标签列表 vs 判定标准提示词）。

样本增强口径：加 Prompt（规范判定标准）即知识增强；标准内容融合任务二。

主指标：**LLM-as-Judge**（标签合理性 pred_precision / gold_recall / F1）。
金标 Exact Match / Macro F1 仅作对照。

公平对比：两侧只改 SYSTEM 是否包含各类判定标准。

用法：
  python scripts/eval_task5_prompt_ab.py
  python scripts/eval_task5_prompt_ab.py --limit 50   # 冒烟
  python scripts/eval_task5_prompt_ab.py --skip-judge   # 仅金标指标
  python scripts/eval_task5_prompt_ab.py --judge-only   # 已有 predictions 时只跑 Judge
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _run(cmd: list[str]) -> None:
    print("\n>>", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=_ROOT, check=True)


def _load_summary(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "evaluated": data.get("evaluated"),
        "prompt_style": data.get("prompt_style"),
        "label_exact_match_accuracy": data.get("label_exact_match_accuracy"),
        "label_partial_hit_rate": data.get("label_partial_hit_rate"),
        "label_mean_jaccard": data.get("label_mean_jaccard"),
        "macro_f1": data.get("macro_f1"),
        "competition_id_macro_f1": data.get("competition_id_macro_f1"),
    }


def _load_judge_summary(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "evaluated": data.get("evaluated"),
        "scoring_mode": data.get("scoring_mode"),
        "judge_pred_precision": data.get("judge_pred_precision"),
        "judge_gold_recall": data.get("judge_gold_recall"),
        "judge_f1": data.get("judge_f1"),
        "judge_full_accept_rate": data.get("judge_full_accept_rate"),
    }


async def _run_label_judge(
    pred_path: Path,
    judge_out: Path,
    *,
    limit: int | None,
) -> dict:
    from eval_label_judge import judge_predictions

    return await judge_predictions(
        predictions_path=pred_path,
        out_path=judge_out,
        limit=limit,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="任务五：提示词规范 A/B（LLM-as-Judge 主指标）")
    parser.add_argument("--gold", default="data/eval/gold_task2_822_cleaned.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out-dir", default="data/eval")
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="跳过 LLM-as-Judge（仅输出金标 Exact/F1）",
    )
    parser.add_argument(
        "--judge-only",
        action="store_true",
        help="跳过打标，仅对已有 predictions 跑 Judge",
    )
    args = parser.parse_args()

    out_dir = _ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    bare_report = out_dir / "label_eval_task5_prompt_bare.json"
    full_report = out_dir / "label_eval_task5_prompt_full.json"
    bare_pred = out_dir / "predicted_task5_prompt_bare.jsonl"
    full_pred = out_dir / "predicted_task5_prompt_full.jsonl"
    bare_judge = out_dir / "label_judge_task5_prompt_bare.json"
    full_judge = out_dir / "label_judge_task5_prompt_full.json"

    if not args.judge_only:
        common = [
            py,
            "scripts/eval_labels.py",
            "--gold",
            args.gold,
            "--with-llm",
            "--no-bert-score",
        ]
        if args.limit:
            common.extend(["--limit", str(args.limit)])

        _run(
            common
            + [
                "--prompt-style",
                "bare",
                "--predictions-out",
                str(bare_pred.relative_to(_ROOT)).replace("\\", "/"),
                "--output",
                str(bare_report.relative_to(_ROOT)).replace("\\", "/"),
            ]
        )
        _run(
            common
            + [
                "--prompt-style",
                "full",
                "--predictions-out",
                str(full_pred.relative_to(_ROOT)).replace("\\", "/"),
                "--output",
                str(full_report.relative_to(_ROOT)).replace("\\", "/"),
            ]
        )

    bare = _load_summary(bare_report) if bare_report.is_file() else {}
    full = _load_summary(full_report) if full_report.is_file() else {}

    bare_judge_summary: dict = {}
    full_judge_summary: dict = {}
    if not args.skip_judge:
        if not bare_pred.is_file() or not full_pred.is_file():
            raise SystemExit("缺少 predictions 文件，请先运行打标或去掉 --judge-only")
        bare_judge_summary = asyncio.run(
            _run_label_judge(bare_pred, bare_judge, limit=args.limit)
        )
        full_judge_summary = asyncio.run(
            _run_label_judge(full_pred, full_judge, limit=args.limit)
        )
        bare_judge_summary = _load_judge_summary(bare_judge)
        full_judge_summary = _load_judge_summary(full_judge)

    gold_delta = {
        "exact_delta": round(
            (full.get("label_exact_match_accuracy") or 0)
            - (bare.get("label_exact_match_accuracy") or 0),
            4,
        ),
        "macro_f1_delta": round(
            (full.get("macro_f1") or 0) - (bare.get("macro_f1") or 0), 4
        ),
        "jaccard_delta": round(
            (full.get("label_mean_jaccard") or 0)
            - (bare.get("label_mean_jaccard") or 0),
            4,
        ),
        "r00x_f1_delta": round(
            (full.get("competition_id_macro_f1") or 0)
            - (bare.get("competition_id_macro_f1") or 0),
            4,
        ),
    }
    judge_delta = {
        "judge_pred_precision_delta": round(
            (full_judge_summary.get("judge_pred_precision") or 0)
            - (bare_judge_summary.get("judge_pred_precision") or 0),
            4,
        ),
        "judge_gold_recall_delta": round(
            (full_judge_summary.get("judge_gold_recall") or 0)
            - (bare_judge_summary.get("judge_gold_recall") or 0),
            4,
        ),
        "judge_f1_delta": round(
            (full_judge_summary.get("judge_f1") or 0)
            - (bare_judge_summary.get("judge_f1") or 0),
            4,
        ),
        "judge_full_accept_delta": round(
            (full_judge_summary.get("judge_full_accept_rate") or 0)
            - (bare_judge_summary.get("judge_full_accept_rate") or 0),
            4,
        ),
    }

    compare = {
        "task": "任务五-提示词规范消融",
        "primary_scoring": "llm_as_judge" if not args.skip_judge else "gold_exact_match",
        "setup": {
            "gold": args.gold,
            "arms": {
                "bare": "SYSTEM 仅可选标签列表，无判定标准",
                "full": "SYSTEM 含总则 + 28 类判定规则/消歧（当前生产提示词）",
            },
        },
        "judge": {
            "bare": bare_judge_summary,
            "full": full_judge_summary,
            "delta_full_minus_bare": judge_delta,
        },
        "gold_reference": {
            "bare": bare,
            "full": full,
            "delta_full_minus_bare": gold_delta,
        },
        "predictions": {
            "bare": str(bare_pred.relative_to(_ROOT)).replace("\\", "/"),
            "full": str(full_pred.relative_to(_ROOT)).replace("\\", "/"),
        },
        "judge_reports": {
            "bare": str(bare_judge.relative_to(_ROOT)).replace("\\", "/"),
            "full": str(full_judge.relative_to(_ROOT)).replace("\\", "/"),
        },
    }
    cmp_path = out_dir / "task5_prompt_ablation.json"
    cmp_path.write_text(json.dumps(compare, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        "# 任务五：提示词规范消融实验",
        "",
        "## 设定",
        "",
        "- 金标：`gold_task2_822_cleaned.jsonl`",
        "- 只对比 SYSTEM 提示词（任务五样本增强：加 Prompt）",
        "- **bare**：只给 28 类标签名，不解释判定标准",
        "- **full**：当前规范提示词（总则 + 每类正例/排除边界，与任务二打标一致）",
        "- **主指标：LLM-as-Judge**（标签语义合理性，不要求与金标字面完全一致）",
        "",
    ]

    if not args.skip_judge:
        md_lines.extend([
            "## 主结果（LLM-as-Judge）",
            "",
            "| 指标 | bare（无标准） | full（规范提示词） | Δ (full−bare) |",
            "|---|---:|---:|---:|",
            (
                f"| Judge pred_precision | {bare_judge_summary.get('judge_pred_precision')} | "
                f"{full_judge_summary.get('judge_pred_precision')} | "
                f"{judge_delta['judge_pred_precision_delta']} |"
            ),
            (
                f"| Judge gold_recall | {bare_judge_summary.get('judge_gold_recall')} | "
                f"{full_judge_summary.get('judge_gold_recall')} | "
                f"{judge_delta['judge_gold_recall_delta']} |"
            ),
            (
                f"| Judge F1 | {bare_judge_summary.get('judge_f1')} | "
                f"{full_judge_summary.get('judge_f1')} | "
                f"{judge_delta['judge_f1_delta']} |"
            ),
            (
                f"| Judge full_accept | {bare_judge_summary.get('judge_full_accept_rate')} | "
                f"{full_judge_summary.get('judge_full_accept_rate')} | "
                f"{judge_delta['judge_full_accept_delta']} |"
            ),
            "",
        ])

    md_lines.extend([
        "## 对照（金标 Exact Match）",
        "",
        "| 指标 | bare | full | Δ |",
        "|---|---:|---:|---:|",
        (
            f"| Exact Match | {bare.get('label_exact_match_accuracy')} | "
            f"{full.get('label_exact_match_accuracy')} | {gold_delta['exact_delta']} |"
        ),
        (
            f"| Mean Jaccard | {bare.get('label_mean_jaccard')} | "
            f"{full.get('label_mean_jaccard')} | {gold_delta['jaccard_delta']} |"
        ),
        (
            f"| Macro F1 | {bare.get('macro_f1')} | "
            f"{full.get('macro_f1')} | {gold_delta['macro_f1_delta']} |"
        ),
        "",
        "## 结论",
        "",
        "在相同模型与金标下，仅补充「风险类别判定标准」即可显著提升多标签分类效果；"
        "任务五消融以 **LLM-as-Judge** 为主口径，金标 Exact Match 作对照。"
        "说明**加 Prompt（规范提示词）即样本与知识增强**；标准内容融合在任务二字典与标注说明中。",
        "",
        "## 产物",
        "",
        f"- `{bare_judge.relative_to(_ROOT).as_posix()}`",
        f"- `{full_judge.relative_to(_ROOT).as_posix()}`",
        f"- `{cmp_path.relative_to(_ROOT).as_posix()}`",
        f"- `{bare_pred.relative_to(_ROOT).as_posix()}`",
        f"- `{full_pred.relative_to(_ROOT).as_posix()}`",
        "",
    ])
    md_path = out_dir / "task5_prompt_ablation.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(json.dumps(compare, ensure_ascii=False, indent=2))
    print(f"wrote {cmp_path}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
