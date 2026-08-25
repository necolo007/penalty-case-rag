"""落盘 few-shot 抽取记录（原始记录，非分析稿）。

产出：
  data/fewshot/extract_fixed.jsonl              固定三样本
  data/fewshot/extract_dynamic_task2_gold.jsonl 金标逐案动态注入
  data/fewshot/extract_manifest.json            清单

用法：
  python scripts/export_fewshot_extract_logs.py
  python scripts/export_fewshot_extract_logs.py --gold-limit 50
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import get_settings
from engine.classification.competition_label_map import predict_cn_tags_by_keywords
from engine.classification.fewshot import (
    FewShotBank,
    retrieve_fewshot_hits,
    retrieve_fixed_fewshot_hits,
)


def _hit_row(h, *, rank: int) -> dict:
    return {
        "rank": rank,
        "example_id": h.example.example_id,
        "case_id": h.example.case_id,
        "score": round(float(h.score), 6),
        "reason": getattr(h, "reason", "") or "",
        "risk_tags": list(h.example.risk_tags),
        "violation_behavior": h.example.violation_behavior,
        "source": h.example.source or "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 few-shot 抽取记录落盘")
    parser.add_argument("--bank", default=None)
    parser.add_argument("--gold", default="data/eval/gold_task2_822_cleaned.jsonl")
    parser.add_argument(
        "--gold-limit",
        type=int,
        default=0,
        help="0=全量金标；>0 只导出前 N 条",
    )
    parser.add_argument("--out-dir", default="data/fewshot")
    args = parser.parse_args()

    settings = get_settings()
    bank_path = Path(args.bank or settings.FEWSHOT_BANK_PATH)
    if not bank_path.is_absolute():
        bank_path = _ROOT / bank_path
    bank = FewShotBank.from_jsonl(bank_path)

    out_dir = _ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    fixed_path = out_dir / "extract_fixed.jsonl"
    dynamic_path = out_dir / "extract_dynamic_task2_gold.jsonl"
    manifest_path = out_dir / "extract_manifest.json"

    fixed_ids = settings.FEWSHOT_FIXED_IDS
    fixed_hits = retrieve_fixed_fewshot_hits(bank=bank, fixed_ids=fixed_ids)
    with fixed_path.open("w", encoding="utf-8") as f:
        rec = {
            "record_type": "fixed",
            "mode": "fixed",
            "fixed_ids": fixed_ids,
            "top_n": len(fixed_hits),
            "injected": [_hit_row(h, rank=i + 1) for i, h in enumerate(fixed_hits)],
        }
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        for i, h in enumerate(fixed_hits):
            f.write(
                json.dumps(
                    {
                        "record_type": "fixed_example",
                        "mode": "fixed",
                        **_hit_row(h, rank=i + 1),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    gold_path = _ROOT / args.gold
    dyn_n = 0
    dyn_with_hits = 0
    with gold_path.open(encoding="utf-8") as gin, dynamic_path.open(
        "w", encoding="utf-8"
    ) as gout:
        for i, line in enumerate(gin):
            if args.gold_limit and i >= args.gold_limit:
                break
            row = json.loads(line)
            vb = (row.get("violation_behavior") or "").strip()
            case_id = str(row.get("case_id") or f"ROW-{i}")
            gold_tags = row.get("risk_tags") or row.get("labels") or []
            hints = predict_cn_tags_by_keywords(vb, max_tags=5) if vb else []
            hits = (
                retrieve_fewshot_hits(vb, bank=bank, tag_hints=hints) if vb else []
            )
            dyn_n += 1
            if hits:
                dyn_with_hits += 1
            gout.write(
                json.dumps(
                    {
                        "record_type": "dynamic",
                        "mode": "dynamic",
                        "case_id": case_id,
                        "violation_behavior": vb,
                        "gold_risk_tags": gold_tags,
                        "tag_hints": hints,
                        "injected_count": len(hits),
                        "injected": [_hit_row(h, rank=j + 1) for j, h in enumerate(hits)],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bank_path": str(bank_path.relative_to(_ROOT)).replace("\\", "/"),
        "bank_examples": len(bank),
        "bank_file": "risk_tag_fewshot_bank_multilabel.jsonl",
        "config": {
            "FEWSHOT_MODE_default": settings.FEWSHOT_MODE,
            "FEWSHOT_FIXED_IDS": fixed_ids,
            "FEWSHOT_TOP_N": settings.FEWSHOT_TOP_N,
            "FEWSHOT_RETRIEVER": settings.FEWSHOT_RETRIEVER,
            "FEWSHOT_REQUIRE_COVERED_HINT": settings.FEWSHOT_REQUIRE_COVERED_HINT,
        },
        "outputs": {
            "bank": "risk_tag_fewshot_bank_multilabel.jsonl",
            "fixed": fixed_path.name,
            "dynamic": dynamic_path.name,
            "fixed_count": len(fixed_hits),
            "dynamic_cases": dyn_n,
            "dynamic_with_hits": dyn_with_hits,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest["outputs"], ensure_ascii=False, indent=2))
    print(f"wrote {fixed_path}")
    print(f"wrote {dynamic_path}")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
