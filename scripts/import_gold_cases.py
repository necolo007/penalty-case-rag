"""导入竞赛金标案例 gold_extraction_cases.jsonl → documents + penalty_cases + embeddings。

保留官方 case_id（C001–C500）与 file_id；关联赛题包 raw_text/{file_id}.txt。

用法：
  python scripts/import_gold_cases.py
  python scripts/import_gold_cases.py --no-embed
  python scripts/import_gold_cases.py --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from core.config import get_settings
from core.db import close_pool, create_pool, to_pgvector
from engine.classification.competition_label_map import cn_tags_to_competition_ids
from engine.classification.entity_normalizer import normalize_entity
from engine.embedding.provider import create_embedding_provider

logger = logging.getLogger(__name__)

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


def _default_raw_text_dir(comp_dir: Path) -> Path:
    settings = get_settings()
    if settings.COMP_RAW_TEXT_DIR:
        return Path(settings.COMP_RAW_TEXT_DIR).resolve()
    # 配套数据的上一级含 raw_text/
    sibling = comp_dir.parent / "raw_text"
    if sibling.is_dir():
        return sibling
    local = Path(settings.DATA_DIR) / "raw_text"
    return local


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _resolve_gold_path(settings, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    p = Path(settings.DATA_DIR) / "eval" / "gold_extraction_cases.jsonl"
    if p.exists():
        return p
    comp = resolve_comp_dir(None)
    return comp / "gold_extraction_cases.jsonl"


async def import_cases(
    *,
    gold_path: Path,
    raw_text_dir: Path,
    limit: int | None,
    embed: bool,
    batch_size: int = 10,
) -> dict:
    settings = get_settings()
    rows = _load_jsonl(gold_path)
    if limit:
        rows = rows[:limit]
    print(f"Loaded {len(rows)} gold cases from {gold_path}")
    print(f"raw_text dir: {raw_text_dir}")

    pool = await create_pool()
    embedder = create_embedding_provider(settings) if embed else None

    # 本地 raw_text 镜像目录（入库约定）
    local_raw = Path(settings.DATA_DIR) / "raw_text"
    local_raw.mkdir(parents=True, exist_ok=True)

    ok = failed = 0
    embed_texts: list[str] = []
    embed_case_ids: list[str] = []

    for i, item in enumerate(rows, 1):
        case_id = item["case_id"]
        file_id = item["file_id"]
        risk_tags = list(item.get("risk_tags") or [])
        risk_type_ids = cn_tags_to_competition_ids(risk_tags)
        party = (item.get("party_name") or "未知当事人").strip() or "未知当事人"
        violation = (item.get("violation_behavior") or "").strip() or "见原文"
        penalty = (item.get("penalty_content") or "").strip() or "见原文"

        src_txt = raw_text_dir / f"{file_id}.txt"
        raw_text = ""
        if src_txt.exists():
            raw_text = src_txt.read_text(encoding="utf-8", errors="ignore")
            dest_txt = local_raw / f"{file_id}.txt"
            if not dest_txt.exists():
                dest_txt.write_text(raw_text, encoding="utf-8")
        rel_path = f"raw_text/{file_id}.txt" if raw_text else None

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        INSERT INTO documents (
                            file_id, file_name, source_type, regulator,
                            raw_text, raw_text_path, parse_status
                        ) VALUES ($1, $2, 'TXT', $3, $4, $5, 'done')
                        ON CONFLICT (file_id) DO UPDATE SET
                            file_name = EXCLUDED.file_name,
                            regulator = COALESCE(EXCLUDED.regulator, documents.regulator),
                            raw_text = COALESCE(EXCLUDED.raw_text, documents.raw_text),
                            raw_text_path = COALESCE(EXCLUDED.raw_text_path, documents.raw_text_path),
                            parse_status = 'done',
                            updated_at = NOW()
                        """,
                        file_id,
                        f"{file_id}.txt",
                        item.get("regulator"),
                        raw_text or None,
                        rel_path,
                    )

                    await conn.execute(
                        """
                        INSERT INTO penalty_cases (
                            case_id, file_id, party_name, institution_type, penalty_doc_no,
                            violation_behavior, penalty_content, regulator,
                            is_insurance_related, is_insurance_candidate, candidate_reasons,
                            risk_tags, risk_type_ids, case_summary,
                            overall_confidence, extraction_method
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8,
                            TRUE, TRUE, $9, $10, $11, $12,
                            1.0, 'gold'
                        )
                        ON CONFLICT (case_id) DO UPDATE SET
                            file_id = EXCLUDED.file_id,
                            party_name = EXCLUDED.party_name,
                            institution_type = EXCLUDED.institution_type,
                            penalty_doc_no = EXCLUDED.penalty_doc_no,
                            violation_behavior = EXCLUDED.violation_behavior,
                            penalty_content = EXCLUDED.penalty_content,
                            regulator = EXCLUDED.regulator,
                            is_insurance_related = TRUE,
                            is_insurance_candidate = TRUE,
                            risk_tags = EXCLUDED.risk_tags,
                            risk_type_ids = EXCLUDED.risk_type_ids,
                            case_summary = EXCLUDED.case_summary,
                            overall_confidence = 1.0,
                            extraction_method = 'gold',
                            updated_at = NOW()
                        """,
                        case_id,
                        file_id,
                        party,
                        item.get("institution_type"),
                        item.get("penalty_doc_no") or None,
                        violation,
                        penalty,
                        item.get("regulator"),
                        ["competition_gold"],
                        risk_tags,
                        risk_type_ids,
                        item.get("case_summary"),
                    )

                    # 主体关联：先清旧再插，保持幂等
                    await conn.execute(
                        "DELETE FROM subject_relations WHERE case_id = $1", case_id,
                    )
                    entity = normalize_entity(party)
                    await conn.execute(
                        """
                        INSERT INTO subject_relations
                            (case_id, raw_party_name, normalized_name, entity_type, confidence)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        case_id, entity.raw_name, entity.normalized_name,
                        entity.entity_type, entity.confidence,
                    )

            if embedder is not None:
                # 纳入 raw_text 截断，避免金标 violation 残缺导致向量语义漂移
                raw_snip = " ".join((raw_text or "").split())[:1200]
                emb_text = " ".join(filter(None, [
                    violation, penalty, " ".join(risk_tags),
                    item.get("case_summary") or "", raw_snip,
                ]))
                if emb_text.strip():
                    embed_texts.append(emb_text[:2000])
                    embed_case_ids.append(case_id)

            ok += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            logger.exception("Failed to import %s", case_id)
            print(f"  FAILED {case_id}: {e}")

        if i % 50 == 0:
            print(f"  progress: {i}/{len(rows)}")

        # 批量向量写入
        if embedder is not None and len(embed_texts) >= batch_size:
            await _flush_embeddings(pool, embedder, embed_case_ids, embed_texts)
            embed_case_ids, embed_texts = [], []

    if embedder is not None and embed_texts:
        await _flush_embeddings(pool, embedder, embed_case_ids, embed_texts)

    await close_pool()
    return {"ok": ok, "failed": failed, "total": len(rows)}


async def _flush_embeddings(pool, embedder, case_ids: list[str], texts: list[str]) -> None:
    vectors = embedder.encode_documents(texts)
    async with pool.acquire() as conn:
        for case_id, vec in zip(case_ids, vectors, strict=True):
            await conn.execute(
                """
                INSERT INTO case_embeddings (case_id, embedding, embedding_model)
                VALUES ($1, $2::vector, $3)
                ON CONFLICT (case_id) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    embedding_model = EXCLUDED.embedding_model
                """,
                case_id, to_pgvector(vec), embedder.model_name,
            )
    print(f"  embedded {len(case_ids)} cases")


async def _amain() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="导入竞赛金标案例")
    parser.add_argument("--gold", default=None, help="gold_extraction_cases.jsonl 路径")
    parser.add_argument("--comp-dir", default=None, help="配套数据目录（用于定位 raw_text）")
    parser.add_argument("--raw-text-dir", default=None, help="赛题 raw_text 目录")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-embed", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    gold_path = _resolve_gold_path(settings, args.gold)
    try:
        comp_dir = resolve_comp_dir(args.comp_dir)
    except FileNotFoundError:
        comp_dir = gold_path.parent

    raw_dir = Path(args.raw_text_dir) if args.raw_text_dir else _default_raw_text_dir(comp_dir)
    result = await import_cases(
        gold_path=gold_path,
        raw_text_dir=raw_dir,
        limit=args.limit,
        embed=not args.no_embed,
    )
    print(f"Done: {result['ok']} ok, {result['failed']} failed / {result['total']}")


if __name__ == "__main__":
    asyncio.run(_amain())
