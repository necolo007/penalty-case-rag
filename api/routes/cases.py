"""案例管理路由：查询 / 筛选 / 人工修正 / 导出。"""

import csv
import io
import json
import logging
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from api.dependencies import get_pool
from api.schemas.models import CaseExcludeRequest, CasePatchRequest
from core.config import get_settings
from pipeline.export.exporters import export_candidates, export_extracted_cases, export_gold_cases

logger = logging.getLogger(__name__)
router = APIRouter()

PATCHABLE_FIELDS = [
    "party_name", "penalty_doc_no", "violation_behavior", "penalty_content",
    "regulator", "legal_basis", "risk_tags", "risk_type_ids", "is_insurance_related",
]

QUEUE_VALUES = frozenset({"confirmed", "pending", "excluded", "all"})

# 列表可排序字段 → SQL 表达式（含处罚金额数值化）
_FINE_AMOUNT_SORT_EXPR = """
CASE
  WHEN c.fine_amount IS NULL OR TRIM(c.fine_amount) = '' THEN 0
  WHEN c.fine_amount ~ '万' THEN
    COALESCE(NULLIF(regexp_replace(c.fine_amount, '[^0-9.]', '', 'g'), '')::double precision, 0) * 10000
  WHEN c.fine_amount ~ '千' THEN
    COALESCE(NULLIF(regexp_replace(c.fine_amount, '[^0-9.]', '', 'g'), '')::double precision, 0) * 1000
  ELSE
    COALESCE(NULLIF(regexp_replace(c.fine_amount, '[^0-9.]', '', 'g'), '')::double precision, 0)
END
"""

SORTABLE_COLUMNS = {
    "case_id": "c.case_id",
    "party_name": "c.party_name",
    "publish_date": "c.publish_date",
    "overall_confidence": "c.overall_confidence",
    "fine_amount": _FINE_AMOUNT_SORT_EXPR,
    "regulator": "c.regulator",
}

CASE_LIST_SELECT = """
        SELECT c.case_id, c.file_id, c.party_name, c.institution_type, c.penalty_doc_no,
               c.violation_behavior, c.penalty_content, c.fine_amount, c.regulator,
               c.publish_date, c.risk_tags, c.risk_type_ids, c.is_insurance_related,
               c.is_insurance_candidate, c.candidate_reasons, c.overall_confidence,
               d.file_name AS source_file
        FROM penalty_cases c JOIN documents d ON c.file_id = d.file_id
"""


def _serialize_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return "、".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _build_case_filters(
    *,
    risk_type: str | None,
    regulator: str | None,
    institution_type: str | None,
    is_insurance_related: bool | None,
    keyword: str | None,
    date_from: date | None,
    date_to: date | None,
    case_ids: list[str] | None = None,
    queue: str | None = None,
    file_id: str | None = None,
) -> tuple[str, list]:
    params: list = []
    clauses: list[str] = []

    # 三级队列优先于 is_insurance_related
    q = (queue or "").strip().lower() or None
    if q and q not in QUEUE_VALUES:
        raise HTTPException(422, detail=f"Invalid queue: {queue!r}")
    if q == "confirmed":
        clauses.append("c.is_insurance_related = TRUE")
    elif q == "pending":
        clauses.append(
            "c.is_insurance_candidate = TRUE AND c.is_insurance_related = FALSE"
        )
    elif q == "excluded":
        clauses.append(
            "c.is_insurance_related = FALSE AND c.is_insurance_candidate = FALSE"
        )
    elif is_insurance_related is not None:
        params.append(is_insurance_related)
        clauses.append(f"c.is_insurance_related = ${len(params)}")

    if file_id:
        params.append(file_id)
        clauses.append(f"c.file_id = ${len(params)}")

    if risk_type:
        # 支持 27 类中文标签或 R00x；中文优先匹配 risk_tags
        rt = risk_type.strip()
        if rt.upper().startswith("R0") and len(rt) <= 5:
            params.append(rt.upper())
            clauses.append(f"${len(params)} = ANY(c.risk_type_ids)")
        else:
            params.append(rt)
            clauses.append(f"${len(params)} = ANY(c.risk_tags)")
    if regulator:
        params.append(regulator)
        clauses.append(f"c.regulator ILIKE ${len(params)}")
        params[-1] = f"%{regulator}%"
    if institution_type:
        params.append(institution_type)
        clauses.append(f"c.institution_type = ${len(params)}")
    if keyword:
        params.append(keyword)
        clauses.append(
            f"c.search_vector @@ plainto_tsquery('zhparser_config', ${len(params)})"
        )
    if date_from is not None:
        params.append(date_from)
        clauses.append(f"c.publish_date >= ${len(params)}")
    if date_to is not None:
        params.append(date_to)
        clauses.append(f"c.publish_date <= ${len(params)}")
    if case_ids:
        params.append(case_ids)
        clauses.append(f"c.case_id = ANY(${len(params)})")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


async def _ensure_tags_and_embedding(pool, case_id: str, row) -> dict:
    """确认保险后：补打标签（若空）并补写向量（若不存在）。"""
    updated: dict = {}
    risk_tags = list(row["risk_tags"] or [])
    risk_type_ids = list(row["risk_type_ids"] or [])

    if not risk_tags and (row["violation_behavior"] or "").strip():
        try:
            from engine.classification.risk_tagger import RiskTagger

            tagger = RiskTagger(pool)
            tags = await tagger.classify(row["violation_behavior"])
            risk_tags = tags.get("display_tags") or []
            risk_type_ids = tags.get("competition_ids") or risk_type_ids
            await pool.execute(
                """
                UPDATE penalty_cases
                SET risk_tags = $2, risk_type_ids = $3, updated_at = NOW()
                WHERE case_id = $1
                """,
                case_id, risk_tags, risk_type_ids,
            )
            updated["risk_tags"] = risk_tags
            updated["risk_type_ids"] = risk_type_ids
        except Exception:  # noqa: BLE001
            logger.exception("confirm: risk tagging failed for %s", case_id)

    has_emb = await pool.fetchval(
        "SELECT 1 FROM case_embeddings WHERE case_id = $1", case_id,
    )
    if not has_emb:
        try:
            from core.config import get_settings as _gs
            from core.db import to_pgvector
            from engine.embedding.provider import create_embedding_provider
            from engine.embedding.store import (
                UPSERT_EMBEDDING_SQL,
                encode_documents_maybe_dual,
                upsert_embedding_args,
            )
            from engine.retrieval.assemble import get_sparse_index

            text = " ".join(filter(None, [
                row["violation_behavior"] or "",
                row["penalty_content"] or "",
                " ".join(risk_tags),
            ])).strip()
            if text:
                embedder = create_embedding_provider(_gs())
                dense_list, sparse_list = encode_documents_maybe_dual(embedder, [text])
                sparse = sparse_list[0] if sparse_list is not None else None
                await pool.execute(
                    UPSERT_EMBEDDING_SQL,
                    *upsert_embedding_args(
                        case_id,
                        dense_list[0],
                        embedder.model_name,
                        sparse=sparse,
                        to_pgvector=to_pgvector,
                    ),
                )
                if sparse is not None:
                    get_sparse_index().upsert(case_id, sparse)
                updated["embedded"] = True
        except Exception:  # noqa: BLE001
            logger.exception("confirm: embedding failed for %s", case_id)

    return updated


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
    output = Path(get_settings().DATA_DIR) / "eval" / "gold_extraction_cases.exported.jsonl"
    path = await export_gold_cases(pool, output, min_confidence=min_confidence)
    return FileResponse(path, filename="gold_extraction_cases.jsonl",
                        media_type="application/jsonl")


@router.get("/export/extracted")
async def export_extracted_endpoint(pool=Depends(get_pool)):
    """导出 extracted_cases.jsonl（全量结构化案例）"""
    output = Path(get_settings().DATA_DIR) / "eval" / "extracted_cases.jsonl"
    path = await export_extracted_cases(pool, output)
    return FileResponse(path, filename="extracted_cases.jsonl",
                        media_type="application/jsonl")


@router.get("/export/table")
async def export_cases_table(
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    risk_type: str | None = None,
    regulator: str | None = None,
    institution_type: str | None = None,
    is_insurance_related: bool | None = None,
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    queue: str | None = None,
    file_id: str | None = None,
    case_ids: str | None = Query(None, description="逗号分隔的 case_id 列表"),
    sort_by: str = Query("publish_date"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    pool=Depends(get_pool),
):
    """导出当前筛选条件下的案例为 CSV / Excel（支持勾选 case_ids）。"""
    ids = [x.strip() for x in (case_ids or "").split(",") if x.strip()] or None
    where, params = _build_case_filters(
        risk_type=risk_type,
        regulator=regulator,
        institution_type=institution_type,
        is_insurance_related=is_insurance_related,
        keyword=keyword,
        date_from=date_from,
        date_to=date_to,
        case_ids=ids,
        queue=queue,
        file_id=file_id,
    )
    sort_col = SORTABLE_COLUMNS.get(sort_by, SORTABLE_COLUMNS["publish_date"])
    order = "DESC" if sort_order.lower() == "desc" else "ASC"
    rows = await pool.fetch(
        f"""
        {CASE_LIST_SELECT}
        {where}
        ORDER BY {sort_col} {order} NULLS LAST, c.case_id ASC
        LIMIT 10000
        """,
        *params,
    )

    headers = [
        "case_id", "party_name", "penalty_doc_no", "violation_behavior",
        "penalty_content", "fine_amount", "regulator", "publish_date",
        "risk_tags", "risk_type_ids", "overall_confidence", "source_file",
    ]
    header_zh = [
        "案例ID", "当事人", "文号", "违规行为", "处罚内容", "处罚金额",
        "监管机构", "发布日期", "风险标签", "风险类型", "置信度", "来源文件",
    ]

    if format == "xlsx":
        try:
            import pandas as pd
        except ImportError as exc:
            raise HTTPException(503, detail="pandas unavailable for xlsx export") from exc
        records = [{h: _serialize_cell(r[h]) for h in headers} for r in rows]
        df = pd.DataFrame(records)
        df.columns = header_zh
        buf = io.BytesIO()
        try:
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="处罚案例")
        except ImportError:
            # 无 openpyxl 时退化为带 BOM 的 CSV，Excel 可直接打开
            format = "csv"
        else:
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="penalty_cases.xlsx"'},
            )

    # CSV（UTF-8 BOM，Excel 友好）
    text_buf = io.StringIO()
    text_buf.write("\ufeff")
    writer = csv.writer(text_buf)
    writer.writerow(header_zh)
    for r in rows:
        writer.writerow([_serialize_cell(r[h]) for h in headers])
    payload = io.BytesIO(text_buf.getvalue().encode("utf-8"))
    return StreamingResponse(
        payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="penalty_cases.csv"'},
    )


@router.post("/{case_id}/confirm")
async def confirm_case(case_id: str, pool=Depends(get_pool)):
    """人工确认保险相关：写入 is_insurance_related，必要时补标签与向量。"""
    row = await pool.fetchrow(
        "SELECT * FROM penalty_cases WHERE case_id = $1", case_id,
    )
    if row is None:
        raise HTTPException(404, detail="case not found")

    await pool.execute(
        """
        UPDATE penalty_cases
        SET is_insurance_related = TRUE,
            is_insurance_candidate = TRUE,
            updated_at = NOW()
        WHERE case_id = $1
        """,
        case_id,
    )
    extras = await _ensure_tags_and_embedding(pool, case_id, row)
    return {"case_id": case_id, "status": "confirmed", **extras}


@router.post("/{case_id}/exclude")
async def exclude_case(
    case_id: str,
    body: CaseExcludeRequest | None = None,
    pool=Depends(get_pool),
):
    """人工排除：非保险相关，并记录排除原因。"""
    row = await pool.fetchrow(
        "SELECT candidate_reasons FROM penalty_cases WHERE case_id = $1", case_id,
    )
    if row is None:
        raise HTTPException(404, detail="case not found")

    reason = (body.reason if body else None) or "人工排除"
    reasons = list(row["candidate_reasons"] or [])
    tag = f"人工排除：{reason}" if not reason.startswith("人工排除") else reason
    if tag not in reasons:
        reasons.append(tag)

    await pool.execute(
        """
        UPDATE penalty_cases
        SET is_insurance_related = FALSE,
            is_insurance_candidate = FALSE,
            candidate_reasons = $2,
            updated_at = NOW()
        WHERE case_id = $1
        """,
        case_id, reasons,
    )
    # 排除后移出检索语料：删除向量（若有）
    await pool.execute("DELETE FROM case_embeddings WHERE case_id = $1", case_id)
    return {"case_id": case_id, "status": "excluded", "candidate_reasons": reasons}


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
    request: Request,
    risk_type: str | None = None,
    regulator: str | None = None,
    institution_type: str | None = None,
    is_insurance_related: bool | None = None,
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    queue: str | None = Query(
        None,
        description="confirmed|pending|excluded|all；默认不限（由前端传 confirmed）",
    ),
    file_id: str | None = None,
    sort_by: str = Query("publish_date"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    pool=Depends(get_pool),
):
    def _qint(name: str, default: int) -> int:
        raw = request.query_params.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise HTTPException(422, detail=f"Invalid integer for {name}: {raw!r}") from exc

    page = max(1, _qint("page", 1))
    page_size = max(1, min(100, _qint("page_size", 20)))
    where, params = _build_case_filters(
        risk_type=risk_type,
        regulator=regulator,
        institution_type=institution_type,
        is_insurance_related=is_insurance_related,
        keyword=keyword,
        date_from=date_from,
        date_to=date_to,
        queue=queue,
        file_id=file_id,
    )

    count_sql = f"SELECT COUNT(*) FROM penalty_cases c {where}"
    total = await pool.fetchval(count_sql, *params)

    sort_col = SORTABLE_COLUMNS.get(sort_by, SORTABLE_COLUMNS["publish_date"])
    order = "DESC" if sort_order.lower() == "desc" else "ASC"
    params.extend([page_size, (page - 1) * page_size])
    rows = await pool.fetch(
        f"""
        {CASE_LIST_SELECT}
        {where}
        ORDER BY {sort_col} {order} NULLS LAST, c.case_id ASC
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
