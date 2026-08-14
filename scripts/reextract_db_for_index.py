"""对库内保险案例做 LLM 重抽，写回 violation_behavior / case_summary，可选再 reindex。

按 file_id 抽一次，再与该文档下的库内 case 做文号/当事人匹配后更新。
不直接信任官方 gold_extraction 字段；用于任务3「违规行为+案件总结」嵌入。

用法：
  python scripts/reextract_db_for_index.py --limit 20          # 小样试跑
  python scripts/reextract_db_for_index.py --reindex           # 全量 + 重建向量
  python scripts/reextract_db_for_index.py --dry-run --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import get_settings
from core.db import close_pool, create_pool
from pipeline.extraction.extractor import ExtractorEngine
from pipeline.parser.base import ParseResult

logger = logging.getLogger(__name__)


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def _match_score(db: dict, pred) -> float:
    score = 0.0
    db_no, pred_no = _norm(db.get("penalty_doc_no")), _norm(getattr(pred, "penalty_doc_no", ""))
    if db_no and pred_no and db_no == pred_no:
        score += 10.0
    db_p, pred_p = _norm(db.get("party_name")), _norm(getattr(pred, "party_name", ""))
    if db_p and pred_p:
        if db_p == pred_p:
            score += 5.0
        elif db_p in pred_p or pred_p in db_p:
            score += 3.0
    vb = (getattr(pred, "violation_behavior", None) or "").strip()
    if vb:
        score += min(2.0, len(vb) / 200.0)
    method = getattr(pred, "extraction_method", "") or ""
    if method in ("llm", "hybrid"):
        score += 1.0
    return score


def _assign(db_rows: list[dict], preds: list) -> list[tuple[dict, object, float]]:
    """贪心一对一匹配。"""
    if not db_rows or not preds:
        return []
    pairs: list[tuple[float, int, int]] = []
    for i, db in enumerate(db_rows):
        for j, pred in enumerate(preds):
            s = _match_score(db, pred)
            if s >= 3.0:  # 至少要有当事人弱匹配或文号
                pairs.append((s, i, j))
    pairs.sort(reverse=True)
    used_i: set[int] = set()
    used_j: set[int] = set()
    out: list[tuple[dict, object, float]] = []
    for s, i, j in pairs:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        out.append((db_rows[i], preds[j], s))
    # 1:1 兜底
    if not out and len(db_rows) == 1 and len(preds) == 1:
        pred = preds[0]
        if (getattr(pred, "violation_behavior", None) or "").strip():
            out.append((db_rows[0], pred, _match_score(db_rows[0], pred)))
    return out


async def run(*, limit: int | None, dry_run: bool, do_reindex: bool, journal: Path) -> None:
    settings = get_settings()
    if not (settings.LLM_API_KEY or "").strip():
        raise SystemExit("需要配置 LLM_API_KEY")

    from engine.llm.client import create_llm_client

    llm = create_llm_client(settings)
    engine = ExtractorEngine(
        llm_client=llm,
        use_llm_refine=False,
        extraction_mode="llm_first",
    )

    pool = await create_pool()
    rows = await pool.fetch(
        """
        SELECT c.case_id, c.file_id, c.party_name, c.penalty_doc_no,
               c.violation_behavior, c.case_summary, c.penalty_content,
               d.raw_text
        FROM penalty_cases c
        JOIN documents d ON c.file_id = d.file_id
        WHERE c.is_insurance_related = TRUE
        ORDER BY c.file_id, c.case_id
        """
    )
    by_file: dict[str, list[dict]] = {}
    for r in rows:
        fid = r["file_id"]
        by_file.setdefault(fid, []).append(dict(r))

    file_ids = list(by_file.keys())
    if limit:
        file_ids = file_ids[:limit]

    journal.parent.mkdir(parents=True, exist_ok=True)
    updated = skipped = failed = unmatched = 0

    with journal.open("w", encoding="utf-8") as jf:
        for n, fid in enumerate(file_ids, 1):
            db_rows = by_file[fid]
            text = (db_rows[0].get("raw_text") or "").strip()
            if not text:
                skipped += 1
                jf.write(json.dumps({"file_id": fid, "status": "no_raw"}, ensure_ascii=False) + "\n")
                continue
            try:
                parse = ParseResult(success=True, markdown=text, confidence=1.0)
                preds = engine.extract(parse, file_id=fid, source_file=f"{fid}.txt")
            except Exception as e:  # noqa: BLE001
                failed += 1
                logger.warning("extract failed %s: %s", fid, e)
                jf.write(json.dumps(
                    {"file_id": fid, "status": "extract_error", "error": str(e)},
                    ensure_ascii=False,
                ) + "\n")
                continue

            if not preds:
                failed += 1
                jf.write(json.dumps({"file_id": fid, "status": "empty_pred"}, ensure_ascii=False) + "\n")
                continue

            assigned = _assign(db_rows, preds)
            if not assigned:
                unmatched += 1
                jf.write(json.dumps({
                    "file_id": fid,
                    "status": "unmatched",
                    "db_cases": [d["case_id"] for d in db_rows],
                    "n_pred": len(preds),
                }, ensure_ascii=False) + "\n")
                continue

            for db, pred, score in assigned:
                vb = (pred.violation_behavior or "").strip()
                summary = (pred.case_summary or "").strip()
                if not vb:
                    continue
                rec = {
                    "file_id": fid,
                    "case_id": db["case_id"],
                    "status": "updated" if not dry_run else "dry_run",
                    "match_score": score,
                    "method": pred.extraction_method,
                    "old_vb_len": len(db.get("violation_behavior") or ""),
                    "new_vb_len": len(vb),
                    "old_summary_len": len(db.get("case_summary") or ""),
                    "new_summary_len": len(summary),
                    "party_name": pred.party_name,
                }
                if not dry_run:
                    await pool.execute(
                        """
                        UPDATE penalty_cases
                        SET violation_behavior = $2,
                            case_summary = COALESCE(NULLIF(trim($3), ''), case_summary),
                            extraction_method = $4,
                            updated_at = NOW()
                        WHERE case_id = $1
                        """,
                        db["case_id"],
                        vb,
                        summary,
                        f"llm_reextract:{pred.extraction_method}",
                    )
                    updated += 1
                else:
                    updated += 1
                jf.write(json.dumps(rec, ensure_ascii=False) + "\n")

            if n % 10 == 0 or n == len(file_ids):
                print(
                    f"  progress {n}/{len(file_ids)} updated={updated} "
                    f"skip={skipped} fail={failed} unmatched={unmatched}",
                    flush=True,
                )

    print(
        f"Done files={len(file_ids)} updated_rows={updated} skipped={skipped} "
        f"failed={failed} unmatched={unmatched} dry_run={dry_run} journal={journal}"
    )

    await close_pool()

    if do_reindex and not dry_run:
        print("Reindexing embeddings (violation_behavior + case_summary)...", flush=True)
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "reindex_embeddings", _ROOT / "scripts" / "reindex_embeddings.py",
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        await mod.reindex(limit=None, batch_size=4)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="LLM 重抽库内案例字段并可选 reindex")
    p.add_argument("--limit", type=int, default=None, help="限制处理的 file_id 数")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--reindex", action="store_true", help="更新后重建 bge-m3 向量")
    p.add_argument(
        "--journal",
        default="data/eval/reextract_db_llm_journal.jsonl",
        help="变更日志路径",
    )
    args = p.parse_args()
    journal = Path(args.journal)
    if not journal.is_absolute():
        journal = _ROOT / journal
    asyncio.run(run(
        limit=args.limit,
        dry_run=args.dry_run,
        do_reindex=args.reindex,
        journal=journal,
    ))


if __name__ == "__main__":
    main()
