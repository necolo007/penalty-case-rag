"""文档管理路由：上传 → 异步解析入库。"""

import hashlib
import json
import logging
from pathlib import Path

from arq import create_pool as create_arq_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from api.dependencies import get_pool
from core.config import get_settings
from core.dates import parse_optional_date
from core.ids import next_file_id
from pipeline.export.exporters import export_manifest

logger = logging.getLogger(__name__)
router = APIRouter()

MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
}

SOURCE_TYPE_BY_EXT = {
    ".pdf": "PDF", ".docx": "WORD", ".html": "HTML", ".htm": "HTML", ".txt": "TXT",
}

_arq_pool = None


def _query_int(request: Request, name: str, default: int) -> int:
    """Apifox/Swagger 传空字符串时回落到默认值。"""
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise HTTPException(422, detail=f"Invalid integer for {name}: {raw!r}") from exc


async def _get_arq():
    """连接 ARQ/Redis；失败时返回明确 503，避免留下 pending 文档。"""
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool

    redis_url = get_settings().REDIS_URL
    try:
        _arq_pool = await create_arq_pool(RedisSettings.from_dsn(redis_url))
        return _arq_pool
    except Exception as exc:
        _arq_pool = None
        logger.exception("Redis/ARQ connect failed (%s)", redis_url)
        raise HTTPException(
            503,
            detail={
                "error": "redis_unavailable",
                "detail": (
                    f"无法连接 Redis（{redis_url}）。"
                    "请确认 docker compose 中 redis 已启动，且 .env 的 REDIS_URL "
                    "宿主机端口与 compose 映射一致（Windows 默认 6534）。"
                ),
                "cause": str(exc),
            },
        ) from exc


async def _save_and_enqueue(pool, *, content: bytes, file_name: str, ext: str,
                            regulator: str | None, publish_date: str | None,
                            source_url: str | None = None) -> tuple[str, bool]:
    """返回 (file_id, is_duplicate)。内容哈希相同则复用已有文档并跳过入队。"""
    settings = get_settings()
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit")

    try:
        parsed_date = parse_optional_date(publish_date)
    except ValueError as exc:
        raise HTTPException(
            400,
            detail={"error": "invalid_publish_date", "detail": str(exc)},
        ) from exc

    digest = hashlib.sha256(content).hexdigest()
    existing = await pool.fetchrow(
        "SELECT file_id, parse_status FROM documents WHERE content_sha256 = $1",
        digest,
    )
    if existing is not None:
        return existing["file_id"], True

    # 先确认队列可用，再落库，避免 Redis 挂掉时产生无法解析的 pending 记录
    arq = await _get_arq()

    file_id = await next_file_id(pool)
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    save_path = upload_dir / f"{file_id}{ext}"
    save_path.write_bytes(content)

    await pool.execute(
        """
        INSERT INTO documents (file_id, file_name, source_type, source_url, regulator,
                               publish_date, parse_status, content_sha256)
        VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7)
        """,
        file_id, file_name, SOURCE_TYPE_BY_EXT[ext], source_url, regulator, parsed_date,
        digest,
    )

    # 只传 uploads 下的文件名，避免 Windows 路径（uploads\xxx）在 Linux Worker 中失效
    await arq.enqueue_job(
        "ingest_document",
        file_id, save_path.name, file_name, MIME_BY_EXT[ext],
        regulator, parsed_date.isoformat() if parsed_date else None,
    )
    return file_id, False


@router.post("/upload", status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    regulator: str | None = Form(None),
    publish_date: str | None = Form(None),
    pool=Depends(get_pool),
):
    """上传 PDF/Word/HTML，触发异步解析"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".pdf", ".docx", ".html", ".htm"):
        raise HTTPException(400, detail={"error": "unsupported_file_type",
                                         "detail": "Only PDF, DOCX, HTML are supported"})
    content = await file.read()
    file_id, dup = await _save_and_enqueue(
        pool, content=content, file_name=file.filename, ext=ext,
        regulator=regulator, publish_date=publish_date,
    )
    if dup:
        return {"file_id": file_id, "status": "duplicate",
                "message": "Identical content already uploaded; reusing existing document"}
    return {"file_id": file_id, "status": "pending", "message": "Document queued for parsing"}


@router.post("/upload-ocr-text", status_code=202)
async def upload_ocr_text(
    file: UploadFile = File(...),
    source_file: str | None = Form(None),
    regulator: str | None = Form(None),
    pool=Depends(get_pool),
):
    """上传 OCR 转写纯文本（赛题任务1）：跳过 MinerU，直接进入字段抽取流水线"""
    ext = Path(file.filename or "").suffix.lower()
    if ext != ".txt":
        raise HTTPException(400, detail={"error": "unsupported_file_type",
                                         "detail": "Only .txt is supported for OCR text"})
    content = await file.read()
    file_id, dup = await _save_and_enqueue(
        pool, content=content, file_name=source_file or file.filename, ext=ext,
        regulator=regulator, publish_date=None,
    )
    if dup:
        return {"file_id": file_id, "status": "duplicate",
                "message": "Identical content already uploaded; reusing existing document"}
    return {"file_id": file_id, "status": "pending", "message": "OCR text queued for extraction"}


@router.post("/{file_id}/retry", status_code=202)
async def retry_document(file_id: str, pool=Depends(get_pool)):
    """失败或卡住的文档重新入队解析。"""
    row = await pool.fetchrow(
        "SELECT file_id, file_name, source_type, regulator, publish_date, parse_status "
        "FROM documents WHERE file_id = $1",
        file_id,
    )
    if row is None:
        raise HTTPException(404, detail="document not found")

    settings = get_settings()
    ext = {"PDF": ".pdf", "WORD": ".docx", "HTML": ".html", "TXT": ".txt"}.get(
        row["source_type"], ".pdf",
    )
    upload_path = Path(settings.UPLOAD_DIR) / f"{file_id}{ext}"
    if not upload_path.exists():
        alt = Path(settings.DATA_DIR) / "raw_text" / f"{file_id}.txt"
        if alt.exists():
            upload_path = alt
            ext = ".txt"
        else:
            raise HTTPException(404, detail="source file not found on disk")

    arq = await _get_arq()
    await pool.execute(
        """
        UPDATE documents
        SET parse_status = 'pending',
            parse_error = NULL,
            parse_metadata = COALESCE(parse_metadata, '{}'::jsonb)
                - 'stage' - 'progress_pct' - 'cases_done' - 'cases_total' - 'failed_stage',
            updated_at = NOW()
        WHERE file_id = $1
        """,
        file_id,
    )
    pub = row["publish_date"].isoformat() if row["publish_date"] else None
    await arq.enqueue_job(
        "ingest_document",
        file_id, upload_path.name, row["file_name"], MIME_BY_EXT.get(ext, "application/pdf"),
        row["regulator"], pub,
    )
    return {"file_id": file_id, "status": "pending", "message": "Document re-queued for parsing"}


@router.get("/export/manifest")
async def export_manifest_endpoint(pool=Depends(get_pool)):
    """导出 penalty_raw_manifest.jsonl"""
    settings = get_settings()
    output = Path(settings.DATA_DIR) / "eval" / "penalty_raw_manifest.jsonl"
    path = await export_manifest(pool, output)
    return FileResponse(path, filename="penalty_raw_manifest.jsonl",
                        media_type="application/jsonl")


def _case_queue_counts(cases: list) -> dict:
    total = len(cases)
    confirmed = sum(1 for c in cases if c.get("is_insurance_related"))
    pending = sum(
        1 for c in cases
        if c.get("is_insurance_candidate") and not c.get("is_insurance_related")
    )
    excluded = total - confirmed - pending
    return {
        "case_total": total,
        "case_confirmed": confirmed,
        "case_pending": pending,
        "case_excluded": max(0, excluded),
    }


def _as_meta_dict(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


_PARSE_STEPS = [
    ("文档识别", "doc"),
    ("OCR文本提取", "ocr"),
    ("案例字段抽取", "extract"),
    ("保险主体识别", "entity"),
    ("风险标签/入库审核", "review"),
]
_STAGE_INDEX = {key: i for i, (_, key) in enumerate(_PARSE_STEPS)}


def _derive_parse_stages(
    parse_status: str,
    case_total: int,
    parse_metadata: dict | None = None,
) -> list[dict]:
    """由 Worker 写入的 stage + parse_status 推导五步进度；无 stage 时回退启发式。"""
    meta = parse_metadata or {}
    stage = meta.get("stage")
    failed_stage = meta.get("failed_stage") or (stage if parse_status == "failed" else None)

    if parse_status == "done":
        done_until = 4 if case_total > 0 else 3
        return [
            {
                "key": key,
                "label": label,
                "status": "done" if i <= done_until else "pending",
            }
            for i, (label, key) in enumerate(_PARSE_STEPS)
        ]

    if parse_status == "pending":
        return [
            {"key": key, "label": label, "status": "pending"}
            for label, key in _PARSE_STEPS
        ]

    if isinstance(stage, str) and stage in _STAGE_INDEX:
        active_idx = _STAGE_INDEX[stage]
        fail_idx = (
            _STAGE_INDEX.get(str(failed_stage), active_idx)
            if parse_status == "failed"
            else None
        )
        out = []
        for i, (label, key) in enumerate(_PARSE_STEPS):
            if fail_idx is not None:
                if i < fail_idx:
                    status = "done"
                elif i == fail_idx:
                    status = "failed"
                else:
                    status = "pending"
            elif i < active_idx:
                status = "done"
            elif i == active_idx:
                status = "active"
            else:
                status = "pending"
            out.append({"key": key, "label": label, "status": status})
        return out

    # 兼容旧数据：无 stage 时按粗状态估算
    if parse_status == "failed":
        done_until, failed_at = 1, 2
    elif parse_status == "parsing":
        done_until, failed_at = 1, None
    else:
        done_until, failed_at = -1, None

    out = []
    for i, (label, key) in enumerate(_PARSE_STEPS):
        if failed_at is not None and i == failed_at:
            status = "failed"
        elif i <= done_until:
            status = "done"
        elif parse_status == "parsing" and i == done_until + 1:
            status = "active"
        else:
            status = "pending"
        out.append({"key": key, "label": label, "status": status})
    return out


def _progress_fields(parse_status: str, case_total: int, meta: dict) -> dict:
    """对外暴露 progress_pct / parse_stage / 案例处理计数。"""
    stage = meta.get("stage")
    pct = meta.get("progress_pct")
    if parse_status == "done":
        pct = 100
        stage = stage or "review"
    elif parse_status == "pending":
        pct = pct if isinstance(pct, (int, float)) else 0
    elif isinstance(pct, (int, float)):
        pct = max(0, min(100, int(pct)))
    else:
        # 无显式百分比时按阶段估算
        stages = _derive_parse_stages(parse_status, case_total, meta)
        done = sum(1 for s in stages if s["status"] == "done")
        active = 1 if any(s["status"] == "active" for s in stages) else 0
        pct = int(((done + active * 0.45) / max(len(stages), 1)) * 100)

    out: dict = {
        "parse_stage": stage,
        "progress_pct": pct,
    }
    if "cases_done" in meta:
        out["cases_done"] = meta.get("cases_done")
    if "cases_total" in meta:
        out["cases_total"] = meta.get("cases_total")
    return out


@router.get("/{file_id}")
async def get_document(file_id: str, pool=Depends(get_pool)):
    row = await pool.fetchrow(
        """
        SELECT file_id, file_name, source_type, regulator, publish_date,
               parse_status, parse_error, parse_metadata, raw_text_path,
               created_at, updated_at
        FROM documents WHERE file_id = $1
        """,
        file_id,
    )
    if row is None:
        raise HTTPException(404, detail="document not found")
    data = dict(row)
    meta = _as_meta_dict(data.pop("parse_metadata", None))
    cases = await pool.fetch(
        """
        SELECT case_id, party_name, penalty_doc_no, violation_behavior,
               penalty_content, fine_amount, regulator, publish_date, legal_basis,
               risk_tags, risk_type_ids, is_insurance_related, is_insurance_candidate,
               candidate_reasons, overall_confidence, field_confidences,
               extraction_method
        FROM penalty_cases
        WHERE file_id = $1
        ORDER BY case_id
        """,
        file_id,
    )
    case_dicts = [dict(c) for c in cases]
    data["cases"] = case_dicts
    counts = _case_queue_counts(case_dicts)
    data.update(counts)
    data["parse_stages"] = _derive_parse_stages(
        data["parse_status"], counts["case_total"], meta,
    )
    data.update(_progress_fields(data["parse_status"], counts["case_total"], meta))
    return data


@router.delete("/{file_id}", status_code=204)
async def delete_document(file_id: str, pool=Depends(get_pool)):
    """删除文档及其关联案例（入库队列/失败文档清理）。"""
    exists = await pool.fetchval("SELECT 1 FROM documents WHERE file_id = $1", file_id)
    if not exists:
        raise HTTPException(404, detail="document not found")
    async with pool.acquire() as conn:
        async with conn.transaction():
            case_ids = [
                r["case_id"]
                for r in await conn.fetch(
                    "SELECT case_id FROM penalty_cases WHERE file_id = $1", file_id,
                )
            ]
            if case_ids:
                await conn.execute(
                    "DELETE FROM review_case_refs WHERE case_id = ANY($1::text[])",
                    case_ids,
                )
                await conn.execute(
                    "DELETE FROM penalty_cases WHERE file_id = $1", file_id,
                )
            await conn.execute("DELETE FROM documents WHERE file_id = $1", file_id)
    return None


@router.get("")
async def list_documents(
    request: Request,
    parse_status: str | None = None,
    pool=Depends(get_pool),
):
    page = max(1, _query_int(request, "page", 1))
    page_size = max(1, _query_int(request, "page_size", 20))
    params: list = []
    where = ""
    if parse_status:
        params.append(parse_status)
        where = "WHERE parse_status = $1"
    params.extend([page_size, (page - 1) * page_size])
    rows = await pool.fetch(
        f"""
        SELECT d.file_id, d.file_name, d.source_type, d.regulator, d.publish_date,
               d.parse_status, d.parse_error, d.parse_metadata,
               d.created_at, d.updated_at,
               COALESCE(agg.case_total, 0)::int AS case_total,
               COALESCE(agg.case_confirmed, 0)::int AS case_confirmed,
               COALESCE(agg.case_pending, 0)::int AS case_pending,
               COALESCE(agg.case_excluded, 0)::int AS case_excluded
        FROM documents d
        LEFT JOIN (
            SELECT file_id,
                   COUNT(*)::int AS case_total,
                   COUNT(*) FILTER (WHERE is_insurance_related)::int AS case_confirmed,
                   COUNT(*) FILTER (
                     WHERE is_insurance_candidate AND NOT is_insurance_related
                   )::int AS case_pending,
                   COUNT(*) FILTER (
                     WHERE NOT is_insurance_related AND NOT is_insurance_candidate
                   )::int AS case_excluded
            FROM penalty_cases
            GROUP BY file_id
        ) agg ON agg.file_id = d.file_id
        {where.replace("parse_status", "d.parse_status") if where else ""}
        ORDER BY d.created_at DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    total = await pool.fetchval(
        f"SELECT COUNT(*) FROM documents {where}",
        *(params[:-2]),
    )
    items = []
    for r in rows:
        item = dict(r)
        meta = _as_meta_dict(item.pop("parse_metadata", None))
        item["parse_stages"] = _derive_parse_stages(
            item["parse_status"], item["case_total"], meta,
        )
        item.update(_progress_fields(item["parse_status"], item["case_total"], meta))
        items.append(item)
    return {"total": total, "page": page, "page_size": page_size, "items": items}
