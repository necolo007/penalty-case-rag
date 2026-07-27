"""竞赛配套评测文件 → data/eval/（复制，避免 Windows 软链权限问题）。

用法：python scripts/link_comp_data.py [--comp-dir DIR] [--force]

注意：test_gold_labels.jsonl 仅放入 quarantine/，不进入 data/eval 主目录，
避免误用于 Prompt / 调参 / 错误分析。
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from core.config import get_settings

# 可进入评测主目录的文件（不含隐藏测试金标）
EVAL_FILES = [
    "gold_extraction_cases.jsonl",
    "retrieval_train_queries.jsonl",
    "test_questions.jsonl",
    "test_queries.jsonl",
    "risk_type_dictionary.csv",
    "README_竞赛数据说明.md",
]

# 隔离存放，默认不复制到 data/eval 根目录
QUARANTINE_FILES = [
    "test_gold_labels.jsonl",
]

_DEFAULT_REL = Path(
    "docs/data/05-金融大模型与智能体赛道-基于知识增强检索的保险监管处罚案例知识库构建与合规审查智能匹配/配套数据"
)


def resolve_comp_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    settings = get_settings()
    if settings.COMP_DATA_DIR:
        return Path(settings.COMP_DATA_DIR).resolve()
    candidate = Path(__file__).resolve().parents[2] / _DEFAULT_REL
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(
        "未找到配套数据目录。请传入 --comp-dir 或设置 COMP_DATA_DIR。"
        f" 已尝试: {candidate}"
    )


def _copy_one(src: Path, dest: Path, *, force: bool) -> str:
    if not src.exists():
        return "missing"
    if dest.exists() and not force:
        return "skip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return "copy"


def main() -> None:
    parser = argparse.ArgumentParser(description="接入竞赛配套数据到 data/eval")
    parser.add_argument("--comp-dir", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--include-test-gold",
        action="store_true",
        help="仅复制到 quarantine/，仍不进入 eval 根目录",
    )
    args = parser.parse_args()

    settings = get_settings()
    src_dir = resolve_comp_dir(args.comp_dir)
    dest_dir = Path(settings.DATA_DIR) / "eval"
    dest_dir.mkdir(parents=True, exist_ok=True)
    quarantine = dest_dir / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)

    # 若根目录已有测试金标，移入隔离区
    leaked = dest_dir / "test_gold_labels.jsonl"
    if leaked.exists():
        target = quarantine / "test_gold_labels.jsonl"
        if not target.exists() or args.force:
            shutil.move(str(leaked), str(target))
            print(f"  quarantine move test_gold_labels.jsonl → {target}")
        else:
            leaked.unlink()
            print("  remove leaked test_gold_labels.jsonl from eval root")

    print(f"Source: {src_dir}\nDest:   {dest_dir}")
    copied = skipped = missing = 0
    for name in EVAL_FILES:
        status = _copy_one(src_dir / name, dest_dir / name, force=args.force)
        print(f"  {status:7} {name}")
        if status == "copy":
            copied += 1
        elif status == "skip":
            skipped += 1
        else:
            missing += 1

    if args.include_test_gold:
        for name in QUARANTINE_FILES:
            status = _copy_one(src_dir / name, quarantine / name, force=args.force)
            print(f"  {status:7} quarantine/{name}")
            if status == "copy":
                copied += 1
            elif status == "skip":
                skipped += 1
            else:
                missing += 1
    else:
        print("  note    test_gold_labels.jsonl 未复制（合规隔离；需时加 --include-test-gold）")

    # 风险字典只进 eval；运行时 dictionaries/ 用 sync_dictionaries.py 从 docs/dic 同步
    print(f"Done: {copied} copied, {skipped} skipped, {missing} missing")


if __name__ == "__main__":
    main()
