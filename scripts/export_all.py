"""一键导出全部赛题交付物 jsonl / csv。

用法：python scripts/export_all.py [--out data/eval]
"""

import argparse
import asyncio
from pathlib import Path

from core.db import close_pool, create_pool
from pipeline.export.exporters import (
    export_candidates,
    export_gold_cases,
    export_manifest,
    export_risk_type_dict,
    export_subject_relations,
)


async def main():
    parser = argparse.ArgumentParser(description="导出赛题交付物")
    parser.add_argument("--out", default="data/eval")
    args = parser.parse_args()

    out = Path(args.out)
    pool = await create_pool()
    try:
        paths = [
            await export_manifest(pool, out / "penalty_raw_manifest.jsonl"),
            await export_candidates(pool, out / "insurance_candidate_cases.jsonl"),
            await export_gold_cases(pool, out / "gold_extraction_cases.jsonl"),
            await export_risk_type_dict(pool, out / "risk_type_dictionary.csv"),
            await export_subject_relations(pool, out / "subject_relations.csv"),
        ]
        for p in paths:
            print(f"Exported: {p}")
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
