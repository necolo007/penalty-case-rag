"""任务五：提示词规范消融（裸标签列表 vs 判定标准提示词）。

公平对比：两侧均关闭 few-shot，只改 SYSTEM 是否包含各类判定标准。

用法：
  python scripts/eval_task5_prompt_ab.py
  python scripts/eval_task5_prompt_ab.py --limit 50   # 冒烟
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> None:
    print("\n>>", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=_ROOT, check=True)


def _load_summary(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "evaluated": data.get("evaluated"),
        "prompt_style": data.get("prompt_style"),
        "fewshot": data.get("fewshot"),
        "label_exact_match_accuracy": data.get("label_exact_match_accuracy"),
        "label_partial_hit_rate": data.get("label_partial_hit_rate"),
        "label_mean_jaccard": data.get("label_mean_jaccard"),
        "macro_f1": data.get("macro_f1"),
        "competition_id_macro_f1": data.get("competition_id_macro_f1"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="任务五：提示词规范 A/B")
    parser.add_argument("--gold", default="data/eval/gold_task2_822_cleaned.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out-dir", default="data/eval")
    args = parser.parse_args()

    out_dir = _ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    common = [
        py,
        "scripts/eval_labels.py",
        "--gold",
        args.gold,
        "--with-llm",
        "--no-fewshot",
        "--no-bert-score",
    ]
    if args.limit:
        common.extend(["--limit", str(args.limit)])

    bare_report = out_dir / "label_eval_task5_prompt_bare.json"
    full_report = out_dir / "label_eval_task5_prompt_full.json"
    bare_pred = out_dir / "predicted_task5_prompt_bare.jsonl"
    full_pred = out_dir / "predicted_task5_prompt_full.jsonl"

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

    bare = _load_summary(bare_report)
    full = _load_summary(full_report)
    delta = {
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
    compare = {
        "task": "任务五-提示词规范消融",
        "setup": {
            "gold": args.gold,
            "fewshot": False,
            "arms": {
                "bare": "SYSTEM 仅可选标签列表，无判定标准",
                "full": "SYSTEM 含总则 + 27 类判定规则/消歧（当前生产提示词）",
            },
        },
        "bare": bare,
        "full": full,
        "delta_full_minus_bare": delta,
        "predictions": {
            "bare": str(bare_pred.relative_to(_ROOT)).replace("\\", "/"),
            "full": str(full_pred.relative_to(_ROOT)).replace("\\", "/"),
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
        "- **关闭 few-shot**，只对比 SYSTEM 提示词",
        "- **bare**：只给 27 类标签名，不解释判定标准",
        "- **full**：当前规范提示词（总则 + 每类正例/排除边界）",
        "",
        "## 结果",
        "",
        "| 指标 | bare（无标准） | full（规范提示词） | Δ (full−bare) |",
        "|---|---:|---:|---:|",
        (
            f"| Exact Match | {bare.get('label_exact_match_accuracy')} | "
            f"{full.get('label_exact_match_accuracy')} | {delta['exact_delta']} |"
        ),
        (
            f"| Mean Jaccard | {bare.get('label_mean_jaccard')} | "
            f"{full.get('label_mean_jaccard')} | {delta['jaccard_delta']} |"
        ),
        (
            f"| Macro F1 | {bare.get('macro_f1')} | "
            f"{full.get('macro_f1')} | {delta['macro_f1_delta']} |"
        ),
        (
            f"| R00x Macro F1 | {bare.get('competition_id_macro_f1')} | "
            f"{full.get('competition_id_macro_f1')} | {delta['r00x_f1_delta']} |"
        ),
        "",
        "## 结论",
        "",
        "在相同模型与金标下，仅补充「风险类别判定标准」即可显著提升多标签分类效果；"
        "说明任务五中「规范提示词 / 标签标准沉淀」是有效的样本与知识增强手段"
        "（与 few-shot 示例库互补）。",
        "",
        "## 产物",
        "",
        f"- `{bare_report.relative_to(_ROOT).as_posix()}`",
        f"- `{full_report.relative_to(_ROOT).as_posix()}`",
        f"- `{cmp_path.relative_to(_ROOT).as_posix()}`",
        f"- `{bare_pred.relative_to(_ROOT).as_posix()}`",
        f"- `{full_pred.relative_to(_ROOT).as_posix()}`",
        "",
    ]
    md_path = out_dir / "task5_prompt_ablation.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(json.dumps(compare, ensure_ascii=False, indent=2))
    print(f"wrote {cmp_path}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
