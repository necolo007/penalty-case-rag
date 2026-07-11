"""案例管理路由：查询 / 筛选 / 人工修正 / 导出。"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.dependencies import get_pool
from api.schemas.models import CasePatchRequest
from core.config import get_settings
from pipeline.export.exporters import export_candidates, export_gold_cases

router = APIRouter()

PATCHABLE_FIELDS = [
    "party_name", "penalty_doc_no", "violation_behavior", "penalty_content",
    "regulator", "legal_basis", "risk_tags", "risk_type_ids", "is_insurance_related",
]


@router.get("/export/candidates")
async def export_candidates_endpoint(pool=Depends(get_pool)):
    """导出 insurance_candidate_cases.jsonl"""
    output = Path(get_settings().DATA_DIR) / "eval" / "insurance_candidate_cases.jsonl"
    path = await export_candidates(pool, output)
    return FileResponse(path, filename="insurance_candidate_cases.jsonl",
                        media_type="application/jsonl")


@router.get("/export/gold")
async def export_gold_endpoint(min_confidence: float = 0.75, pool=Depends(get_pool)):
    """导出 gold_extraction_cases.jsonl"""
    output = Path(get_settings().DATA_DIR) / "eval" / "gold_extraction_cases.jsonl"
    path = await export_gold_cases(pool, output, min_confidence=min_confidence)
    return FileResponse(path, filename="gold_extraction_cases.jsonl",
                        media_type="application/jsonl")


@router.get("/{case_id}")
async def get_case(case_id: str, pool=Depends(get_pool)):
    row = await pool.fetchrow(
        """
        SELECT c.*, d.file_name AS source_file
        FROM penalty_cases c JOIN documents d ON c.file_id = d.file_id
        WHERE c.case_id = $1
        """,
        case_id,
    )
    if row is None:
        raise HTTPException(404, detail="case not found")
    data = dict(row)
    data.pop("search_vector", None)
    return data


@router.get("")
async def list_cases(
    page: int = 1,
    page_size: int = 20,
    risk_type: str | None = None,
    regulator: str | None = None,
    institution_type: str | None = None,
    is_insurance_related: bool | None = None,
    keyword: str | None = None,
    pool=Depends(get_pool),
):
    params: list = []
    clauses: list[str] = []

    if risk_type:
        params.append(risk_type)
        clauses.append(f"${len(params)} = ANY(c.risk_type_ids)")
    if regulator:
        params.append(regulator)
        clauses.append(f"c.regulator = ${len(params)}")
    if institution_type:
        params.append(institution_type)
        clauses.append(f"c.institution_type = ${len(params)}")
    if is_insurance_related is not None:
        params.append(is_insurance_related)
        clauses.append(f"c.is_insurance_related = ${len(params)}")
    if keyword:
        params.append(keyword)
        clauses.append(
            f"c.search_vector @@ plainto_tsquery('zhparser_config', ${len(params)})"
        )

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    count_sql = f"SELECT COUNT(*) FROM penalty_cases c {where}"
    total = await pool.fetchval(count_sql, *params)

    params.extend([page_size, (page - 1) * page_size])
    rows = await pool.fetch(
        f"""
        SELECT c.case_id, c.party_name, c.institution_type, c.penalty_doc_no,
               c.violation_behavior, c.penalty_content, c.regulator, c.publish_date,
               c.risk_tags, c.risk_type_ids, c.is_insurance_related,
               c.overall_confidence, d.file_name AS source_file
        FROM penalty_cases c JOIN documents d ON c.file_id = d.file_id
        {where}
        ORDER BY c.case_id
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    return {"total": total, "page": page, "page_size": page_size,
            "items": [dict(r) for r in rows]}


@router.patch("/{case_id}")
async def patch_case(case_id: str, body: CasePatchRequest, pool=Depends(get_pool)):
    """人工修正案例字段"""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, detail="no fields to update")

    params: list = [case_id]
    set_clauses = []
    for field_name, value in updates.items():
        if field_name not in PATCHABLE_FIELDS:
            continue
        params.append(value)
        set_clauses.append(f"{field_name} = ${len(params)}")
    set_clauses.append("updated_at = NOW()")

    result = await pool.execute(
        f"UPDATE penalty_cases SET {', '.join(set_clauses)} WHERE case_id = $1",
        *params,
    )
    if result == "UPDATE 0":
        raise HTTPException(404, detail="case not found")
    return {"case_id": case_id, "updated_fields": list(updates.keys())}


@router.delete("/{case_id}", status_code=204)
async def delete_case(case_id: str, pool=Depends(get_pool)):
    result = await pool.execute("DELETE FROM penalty_cases WHERE case_id = $1", case_id)
    if result == "DELETE 0":
        raise HTTPException(404, detail="case not found")
