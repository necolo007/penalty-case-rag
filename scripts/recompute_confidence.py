"""按 field_confidences / 字段完整度回算 overall_confidence。

用法：
  python scripts/recompute_confidence.py
  python scripts/recompute_confidence.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg

from core.config import get_settings
from pipeline.extraction.extractor import ExtractorEngine
from pipeline.extraction.schema import ExtractedCase

LEVEL_SCORE = ExtractorEngine._LEVEL_SCORE
FIELD_WEIGHTS = ExtractorEngine._FIELD_WEIGHTS


def score_case(row: asyncpg.Record) -> float:
    confidences = row["field_confidences"] or {}
    if isinstance(confidences, str):
        try:
            confidences = json.loads(confidences)
        except json.JSONDecodeError:
            confidences = {}

    method = row["extraction_method"] or "regex"
    # 金标无字段置信度：按字段是否齐全估算，上限 0.96
    if method == "gold" and not confidences:
        filled = 0
        total = 0
        for field_name, weight in FIELD_WEIGHTS.items():
            total += weight
            val = row[field_name] if field_name in row else None
            if val not in (None, ""):
                filled += weight
        ratio = filled / total if total else 0.0
        return round(min(0.96, max(0.7, 0.7 + ratio * 0.26)), 3)

    case = ExtractedCase(
        file_id=row["file_id"] or "",
        source_file="",
        party_name=row["party_name"] or "",
        penalty_doc_no=row["penalty_doc_no"] or "",
        violation_behavior=row["violation_behavior"] or "",
        penalty_content=row["penalty_content"] or "",
        fine_amount=row["fine_amount"] or "",
        regulator=row["regulator"] or "",
        publish_date=row["publish_date"].isoformat() if row["publish_date"] else None,
        legal_basis=row["legal_basis"] or "",
        field_confidences=dict(confidences),
        extraction_method=method,
    )
    # 金标默认字段档位为 high
    if method == "gold":
        for f in FIELD_WEIGHTS:
            if getattr(case, f) and f not in case.field_confidences:
                case.field_confidences[f] = "high"

    engine = ExtractorEngine(use_llm_refine=False)
    engine._validate(case)
    return case.overall_confidence


async def main(dry_run: bool) -> None:
    settings = get_settings()
    pool = await asyncpg.create_pool(settings.DATABASE_URL)
    assert pool is not None
    rows = await pool.fetch(
        """
        SELECT case_id, file_id, party_name, penalty_doc_no, violation_behavior,
               penalty_content, fine_amount, regulator, publish_date, legal_basis,
               field_confidences, extraction_method, overall_confidence
        FROM penalty_cases
        ORDER BY case_id
        """
    )
    updates: list[tuple[float, str]] = []
    hist: dict[str, int] = {}
    for row in rows:
        new_conf = score_case(row)
        bucket = f"{new_conf:.2f}"
        hist[bucket] = hist.get(bucket, 0) + 1
        if abs(float(row["overall_confidence"] or 0) - new_conf) > 1e-6:
            updates.append((new_conf, row["case_id"]))

    print(f"cases={len(rows)} changed={len(updates)}")
    print("distribution:", dict(sorted(hist.items(), reverse=True)[:12]))
    if dry_run:
        print("dry-run, no write")
        await pool.close()
        return

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                "UPDATE penalty_cases SET overall_confidence = $1, updated_at = NOW() WHERE case_id = $2",
                updates,
            )
    print(f"updated {len(updates)} rows")
    await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
