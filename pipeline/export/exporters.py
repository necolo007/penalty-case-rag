"""赛题官方 jsonl / csv 导出（schema 严格对齐设计文档 §9.4，为唯一真相源）。"""

import csv
import json
from pathlib import Path

import asyncpg


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


async def export_manifest(pool: asyncpg.Pool, output: str | Path) -> Path:
    """penalty_raw_manifest.jsonl：原始文件清单（任务1）"""
    rows = await pool.fetch(
        """
        SELECT file_id, file_name, source_type, publish_date, regulator, source_url, raw_text_path
        FROM documents
        WHERE parse_status = 'done'
        ORDER BY file_id
        """
    )
    data = [
        {
            "file_id": r["file_id"],
            "source_file": r["file_name"],
            "source_type": r["source_type"],
            "publish_date": r["publish_date"].isoformat() if r["publish_date"] else None,
            "regulator": r["regulator"],
            "source_url": r["source_url"],
            "raw_text_path": r["raw_text_path"],
            "note": "原始公开处罚材料，未人工校验",
        }
        for r in rows
    ]
    return _write_jsonl(Path(output), data)


async def export_candidates(pool: asyncpg.Pool, output: str | Path) -> Path:
    """insurance_candidate_cases.jsonl：规则初筛候选集（任务2）"""
    rows = await pool.fetch(
        """
        SELECT case_id, file_id, candidate_reasons, party_name,
               violation_behavior, penalty_content, is_insurance_candidate
        FROM penalty_cases
        WHERE is_insurance_candidate = TRUE
        ORDER BY case_id
        """
    )
    data = [
        {
            "case_candidate_id": f"CC{r['case_id'].lstrip('C')}",
            "file_id": r["file_id"],
            "candidate_reason": list(r["candidate_reasons"] or []),
            "raw_party_name": r["party_name"],
            "raw_violation_behavior": r["violation_behavior"],
            "raw_penalty_content": r["penalty_content"],
            "is_insurance_candidate": r["is_insurance_candidate"],
        }
        for r in rows
    ]
    return _write_jsonl(Path(output), data)


async def export_gold_cases(pool: asyncpg.Pool, output: str | Path,
                            min_confidence: float = 0.75) -> Path:
    """gold_extraction_cases.jsonl：高质量结构化案例（任务1）"""
    rows = await pool.fetch(
        """
        SELECT c.case_id, c.file_id, d.file_name, c.is_insurance_related,
               c.party_name, c.institution_type, c.penalty_doc_no,
               c.violation_behavior, c.penalty_content, c.regulator,
               c.risk_tags, c.case_summary
        FROM penalty_cases c
        JOIN documents d ON c.file_id = d.file_id
        WHERE c.is_insurance_related = TRUE AND c.overall_confidence >= $1
        ORDER BY c.case_id
        """,
        min_confidence,
    )
    data = [
        {
            "case_id": r["case_id"],
            "file_id": r["file_id"],
            "source_file": r["file_name"],
            "is_insurance_related": r["is_insurance_related"],
            "party_name": r["party_name"],
            "institution_type": r["institution_type"],
            "penalty_doc_no": r["penalty_doc_no"],
            "violation_behavior": r["violation_behavior"],
            "penalty_content": r["penalty_content"],
            "regulator": r["regulator"],
            "risk_tags": list(r["risk_tags"] or []),
            "case_summary": r["case_summary"],
        }
        for r in rows
    ]
    return _write_jsonl(Path(output), data)


async def export_extracted_cases(pool: asyncpg.Pool, output: str | Path) -> Path:
    """extracted_cases.jsonl：全量结构化案例（不按置信度过滤）。"""
    rows = await pool.fetch(
        """
        SELECT c.case_id, c.file_id, d.file_name, c.is_insurance_related,
               c.is_insurance_candidate, c.party_name, c.institution_type,
               c.penalty_doc_no, c.violation_behavior, c.penalty_content,
               c.regulator, c.publish_date, c.risk_tags, c.risk_type_ids,
               c.case_summary, c.overall_confidence, c.extraction_method
        FROM penalty_cases c
        JOIN documents d ON c.file_id = d.file_id
        ORDER BY c.case_id
        """
    )
    data = [
        {
            "case_id": r["case_id"],
            "file_id": r["file_id"],
            "source_file": r["file_name"],
            "is_insurance_related": r["is_insurance_related"],
            "is_insurance_candidate": r["is_insurance_candidate"],
            "party_name": r["party_name"],
            "institution_type": r["institution_type"],
            "penalty_doc_no": r["penalty_doc_no"],
            "violation_behavior": r["violation_behavior"],
            "penalty_content": r["penalty_content"],
            "regulator": r["regulator"],
            "publish_date": r["publish_date"].isoformat() if r["publish_date"] else None,
            "risk_tags": list(r["risk_tags"] or []),
            "risk_type_ids": list(r["risk_type_ids"] or []),
            "case_summary": r["case_summary"],
            "overall_confidence": r["overall_confidence"],
            "extraction_method": r["extraction_method"],
        }
        for r in rows
    ]
    return _write_jsonl(Path(output), data)


async def export_risk_type_dict(pool: asyncpg.Pool, output: str | Path) -> Path:
    """risk_type_dictionary.csv：风险标签字典（任务2）"""
    rows = await pool.fetch(
        """
        SELECT risk_type_id, competition_id, parent_id, level, risk_type_name,
               description, keywords
        FROM risk_type_dict WHERE is_active
        ORDER BY risk_type_id
        """
    )
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["risk_type_id", "competition_id", "parent_id", "level",
                         "risk_type_name", "description", "keywords"])
        for r in rows:
            writer.writerow([
                r["risk_type_id"], r["competition_id"], r["parent_id"], r["level"],
                r["risk_type_name"], r["description"] or "",
                "|".join(r["keywords"] or []),
            ])
    return path


async def export_subject_relations(pool: asyncpg.Pool, output: str | Path) -> Path:
    """subject_relations.csv：主体关联表（任务2）"""
    rows = await pool.fetch(
        """
        SELECT relation_id, case_id, raw_party_name, normalized_name, entity_type, confidence
        FROM subject_relations ORDER BY relation_id
        """
    )
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["relation_id", "case_id", "raw_party_name",
                         "normalized_name", "entity_type", "confidence"])
        for r in rows:
            writer.writerow([r["relation_id"], r["case_id"], r["raw_party_name"],
                             r["normalized_name"], r["entity_type"], r["confidence"]])
    return path
