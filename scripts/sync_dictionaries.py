"""将词典同步到 data/dictionaries（及 risk 字典到 data/eval）。

用法：
  python scripts/sync_dictionaries.py
  python scripts/sync_dictionaries.py --src ../docs/dic
  # 竞赛配套风险字典（含 R001–R011）：
  python scripts/sync_dictionaries.py --src \"../docs/data/.../配套数据\"
"""

from __future__ import annotations

import argparse
import csv
import io
import shutil
from pathlib import Path

TERM_FILES = (
    "entity_name_dict.csv",
    "insurance_business_dict.csv",
    "regulatory_basis_dict.csv",
    "exclude_dict.csv",
)


def _detect_encoding(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def _sync_risk_dict(src: Path, dest: Path) -> None:
    enc = _detect_encoding(src)
    text = src.read_text(encoding=enc).replace("\r\n", "\n").replace("\r", "\n")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = list(reader.fieldnames or [])
    rows = list(reader)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  risk    {src.name} ({enc} → utf-8-sig, {len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="同步 docs/dic → data/dictionaries")
    parser.add_argument("--src", default=None)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    src_dir = Path(args.src).resolve() if args.src else (project_root.parent / "docs" / "dic")
    dest_dir = project_root / "data" / "dictionaries"
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not src_dir.is_dir():
        raise FileNotFoundError(f"词典源目录不存在: {src_dir}")

    print(f"Source: {src_dir}\nDest:   {dest_dir}")
    for name in TERM_FILES:
        src = src_dir / name
        if not src.exists():
            print(f"  skip    {name}")
            continue
        shutil.copy2(src, dest_dir / name)
        print(f"  copy    {name}")

    risk_src = src_dir / "risk_type_dictionary.csv"
    if risk_src.exists():
        _sync_risk_dict(risk_src, dest_dir / "risk_type_dictionary.csv")
        eval_dest = project_root / "data" / "eval" / "risk_type_dictionary.csv"
        _sync_risk_dict(risk_src, eval_dest)
    print("Done.")


if __name__ == "__main__":
    main()
