"""将竞赛配套评测文件接入 data/eval/（默认复制；体积小，避免 Windows 软链权限问题）。

用法：
  python scripts/link_comp_data.py
  python scripts/link_comp_data.py --comp-dir "D:/code/Drafter/docs/data/.../配套数据"

也可设置环境变量 COMP_DATA_DIR。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from core.config import get_settings

EVAL_FILES = [
    "gold_extraction_cases.jsonl",
    "retrieval_train_queries.jsonl",
    "test_questions.jsonl",
    "test_gold_labels.jsonl",
    "test_queries.jsonl",
    "risk_type_dictionary.csv",
    "README_竞赛数据说明.md",
]

# 仓库内默认相对路径（相对 Drafter 根，而非 penalty-case-rag）
_DEFAULT_REL = Path(
    "docs/data/05-金融大模型与智能体赛道-基于知识增强检索的保险监管处罚案例知识库构建与合规审查智能匹配/配套数据"
)


def resolve_comp_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    settings = get_settings()
    if settings.COMP_DATA_DIR:
        return Path(settings.COMP_DATA_DIR).resolve()
    # penalty-case-rag 的上一级是 Drafter
    candidate = Path(__file__).resolve().parents[2] / _DEFAULT_REL
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(
        "未找到配套数据目录。请传入 --comp-dir 或设置 COMP_DATA_DIR。"
        f" 已尝试: {candidate}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="接入竞赛配套数据到 data/eval")
    parser.add_argument("--comp-dir", default=None, help="配套数据目录")
    parser.add_argument("--force", action="store_true", help="覆盖已存在文件")
    args = parser.parse_args()

    settings = get_settings()
    src_dir = resolve_comp_dir(args.comp_dir)
    dest_dir = Path(settings.DATA_DIR) / "eval"
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Source: {src_dir}")
    print(f"Dest:   {dest_dir}")

    copied = skipped = missing = 0
    for name in EVAL_FILES:
        src = src_dir / name
        dest = dest_dir / name
        if not src.exists():
            print(f"  MISSING {name}")
            missing += 1
            continue
        if dest.exists() and not args.force:
            print(f"  skip    {name} (exists)")
            skipped += 1
            continue
        shutil.copy2(src, dest)
        print(f"  copy    {name}")
        copied += 1

    # 同步官方风险字典到 dictionaries
    risk_csv = src_dir / "risk_type_dictionary.csv"
    dict_dest = Path(settings.DATA_DIR) / "dictionaries" / "risk_type_dictionary.csv"
    if risk_csv.exists() and (args.force or not dict_dest.exists()):
        dict_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(risk_csv, dict_dest)
        print(f"  copy    risk_type_dictionary.csv → dictionaries/")

    print(f"Done: {copied} copied, {skipped} skipped, {missing} missing")


if __name__ == "__main__":
    main()
