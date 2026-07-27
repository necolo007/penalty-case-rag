"""从 docs/example 监管处罚案例库构建抽样测试集清单。

去重（PDF 优先）→ 文件名弱标签分层抽样 → 写出入库/筛选评测清单。

用法：python scripts/build_example_testset.py [--src DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

INSURANCE_NAME_KEYS = (
    "人寿保险", "财产保险", "健康保险", "养老保险", "保险股份",
    "保险有限", "保险代理", "保险经纪", "保险公估", "相互保险", "再保险",
    "人寿", "财险", "产险", "寿险", "健康险", "养老险",
    "太保", "平安人寿", "人保财", "新华人寿", "泰康人寿", "阳光人寿",
    "大地保险", "中华联合", "出口信用保险", "众安在线", "泰康在线",
)
REGULATOR_ONLY_KEYS = (
    "保险监督管理委员会", "银保监会", "银保监局", "银保监分局",
    "金融监督管理总局", "金融监管局", "保监局", "保监罚",
)
NON_INSURANCE_NAME_KEYS = (
    "银行", "农商行", "信用社", "消费金融", "信托", "小额贷款",
    "融资担保", "金融租赁", "村镇银行", "城市商业银行",
)
LEVEL_ALIASES = {"总局": "hq", "分局": "branch", "支局": "subbranch"}


def _level_from_folder(name: str) -> str:
    for zh, code in LEVEL_ALIASES.items():
        if zh in name:
            return code
    return "other"


def _weak_label(filename: str) -> str:
    has_ins = any(k in filename for k in INSURANCE_NAME_KEYS)
    has_non = any(k in filename for k in NON_INSURANCE_NAME_KEYS)
    if not has_ins and any(k in filename for k in REGULATOR_ONLY_KEYS):
        return "unknown"
    if has_ins and not has_non:
        return "insurance"
    if has_non and not has_ins:
        return "non_insurance"
    return "unknown"


def _prefer_pdf(paths: list[Path]) -> Path:
    pdfs = [p for p in paths if p.suffix.lower() == ".pdf"]
    return pdfs[0] if pdfs else paths[0]


def scan_corpus(src: Path) -> list[dict]:
    buckets: dict[str, list[Path]] = {}
    for p in src.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".pdf", ".doc", ".docx"}:
            continue
        buckets.setdefault(p.stem.strip().lower(), []).append(p)

    records: list[dict] = []
    for stem, paths in buckets.items():
        chosen = _prefer_pdf(paths)
        try:
            rel = chosen.relative_to(src)
            top = rel.parts[0] if rel.parts else "."
        except ValueError:
            top = chosen.parent.name
            rel = Path(chosen.name)
        year_m = re.search(r"(20\d{2})", chosen.name)
        records.append({
            "path": str(chosen.resolve()),
            "rel_path": str(rel).replace("\\", "/"),
            "file_name": chosen.name,
            "ext": chosen.suffix.lower(),
            "level": _level_from_folder(top),
            "folder": top,
            "year": year_m.group(1) if year_m else "",
            "weak_label": _weak_label(chosen.name),
            "duplicate_count": len(paths),
            "file_id_hint": "E" + hashlib.md5(stem.encode("utf-8")).hexdigest()[:8].upper(),
        })
    return records


def stratified_sample(
    records: list[dict],
    *,
    limit_pos: int,
    limit_neg: int,
    limit_unknown: int,
    seed: int,
) -> list[dict]:
    rng = random.Random(seed)
    by_label: dict[str, list[dict]] = {"insurance": [], "non_insurance": [], "unknown": []}
    for r in records:
        by_label.setdefault(r["weak_label"], []).append(r)

    def pick(pool: list[dict], n: int) -> list[dict]:
        if n <= 0 or not pool:
            return []
        by_level: dict[str, list[dict]] = {}
        for r in pool:
            by_level.setdefault(r["level"], []).append(r)
        for level_pool in by_level.values():
            rng.shuffle(level_pool)
        levels = list(by_level.keys())
        rng.shuffle(levels)
        out: list[dict] = []
        i = 0
        while len(out) < n and any(by_level[lv] for lv in levels):
            lv = levels[i % len(levels)]
            if by_level[lv]:
                out.append(by_level[lv].pop())
            i += 1
        return out

    sampled = (
        pick(by_label["insurance"], limit_pos)
        + pick(by_label["non_insurance"], limit_neg)
        + pick(by_label["unknown"], limit_unknown)
    )
    rng.shuffle(sampled)
    return [{**r, "sample_id": f"EX{i:04d}"} for i, r in enumerate(sampled, 1)]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _stats(rows: list[dict]) -> dict:
    return {
        "total": len(rows),
        "by_label": dict(Counter(r["weak_label"] for r in rows)),
        "by_level": dict(Counter(r["level"] for r in rows)),
        "by_ext": dict(Counter(r["ext"] for r in rows)),
    }


def default_src() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "example"


def main() -> None:
    parser = argparse.ArgumentParser(description="从 docs/example 构建测试集清单")
    parser.add_argument("--src", default=None)
    parser.add_argument("--out-dir", default="data/eval/example")
    parser.add_argument("--limit-pos", type=int, default=300)
    parser.add_argument("--limit-neg", type=int, default=150)
    parser.add_argument("--limit-unknown", type=int, default=200)
    parser.add_argument("--ingest-limit", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--full-index", action="store_true")
    args = parser.parse_args()

    src = Path(args.src).resolve() if args.src else default_src()
    if not src.is_dir():
        raise FileNotFoundError(f"案例库不存在: {src}")

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = Path(__file__).resolve().parents[1] / out_dir

    print(f"Scanning: {src}")
    records = scan_corpus(src)
    print(f"Deduped files: {len(records)}")

    sample = stratified_sample(
        records,
        limit_pos=args.limit_pos,
        limit_neg=args.limit_neg,
        limit_unknown=args.limit_unknown,
        seed=args.seed,
    )
    write_jsonl(out_dir / "example_testset_manifest.jsonl", sample)
    (out_dir / "example_testset_summary.json").write_text(
        json.dumps(
            {
                "corpus": _stats(records),
                "sample": _stats(sample),
                "note": "weak_label 来自文件名启发式；正式判定以 InsuranceFilter 为准。",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    ingest_pool = [r for r in sample if r["weak_label"] == "insurance" and r["ext"] == ".pdf"]
    if len(ingest_pool) < args.ingest_limit:
        seen = {id(r) for r in ingest_pool}
        ingest_pool.extend(r for r in sample if id(r) not in seen and r["ext"] == ".pdf")
    ingest = ingest_pool[: args.ingest_limit]
    write_jsonl(out_dir / "example_ingest_manifest.jsonl", ingest)

    filter_rows = [
        {
            "sample_id": r["sample_id"],
            "path": r["path"],
            "file_name": r["file_name"],
            "weak_label": r["weak_label"],
            "expected_is_insurance": True if r["weak_label"] == "insurance"
            else False if r["weak_label"] == "non_insurance" else None,
        }
        for r in sample
        if r["weak_label"] in {"insurance", "non_insurance"}
    ]
    write_jsonl(out_dir / "example_filter_eval.jsonl", filter_rows)

    if args.full_index:
        write_jsonl(out_dir / "example_full_index.jsonl", records)

    print(f"Sample {len(sample)}, ingest {len(ingest)}, filter {len(filter_rows)} → {out_dir}")


if __name__ == "__main__":
    main()
