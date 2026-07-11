"""文档管理路由：上传 → 异步解析入库。"""

import logging
from pathlib import Path

from arq import create_pool as create_arq_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.dependencies import get_pool
from core.config import get_settings
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


async def _get_arq():
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_arq_pool(RedisSettings.from_dsn(get_settings().REDIS_URL))
    return _arq_pool


async def _next_file_id(pool) -> str:
    row = await pool.fetchrow("SELECT COUNT(*) + 1 AS n FROM documents")
    return f"F{row['n']:06d}"


async def _save_and_enqueue(pool, *, content: bytes, file_name: str, ext: str,
                            regulator: str | None, publish_date: str | None,
                            source_url: str | None = None) -> str:
    settings = get_settings()
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit")

    file_id = await _next_file_id(pool)
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    save_path = upload_dir / f"{file_id}{ext}"
    save_path.write_bytes(content)

    await pool.execute(
        """
        INSERT INTO documents (file_id, file_name, source_type, source_url, regulator,
                               publish_date, parse_status)
        VALUES ($1, $2, $3, $4, $5, $6::date, 'pending')
        """,
        file_id, file_name, SOURCE_TYPE_BY_EXT[ext], source_url, regulator, publish_date,
    )

    arq = await _get_arq()
    await arq.enqueue_job(
        "ingest_document",
        file_id, str(save_path), file_name, MIME_BY_EXT[ext],
        regulator, publish_date,
    )
    return file_id


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
    file_id = await _save_and_enqueue(
        pool, content=content, file_name=file.filename, ext=ext,
        regulator=regulator, publish_date=publish_date,
    )
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
    file_id = await _save_and_enqueue(
        pool, content=content, file_name=source_file or file.filename, ext=ext,
        regulator=regulator, publish_date=None,
    )
    return {"file_id": file_id, "status": "pending", "message": "OCR text queued for extraction"}


@router.get("/export/manifest")
async def export_manifest_endpoint(pool=Depends(get_pool)):
    """导出 penalty_raw_manifest.jsonl"""
    settings = get_settings()
    output = Path(settings.DATA_DIR) / "eval" / "penalty_raw_manifest.jsonl"
    path = await export_manifest(pool, output)
    return FileResponse(path, filename="penalty_raw_manifest.jsonl",
                        media_type="application/jsonl")


@router.get("/{file_id}")
async def get_document(file_id: str, pool=Depends(get_pool)):
    row = await pool.fetchrow(
        """
        SELECT file_id, file_name, source_type, regulator, publish_date,
               parse_status, parse_error, raw_text_path, created_at, updated_at
        FROM documents WHERE file_id = $1
        """,
        file_id,
    )
    if row is None:
        raise HTTPException(404, detail="document not found")
    return dict(row)


@router.get("")
async def list_documents(page: int = 1, page_size: int = 20,
                         parse_status: str | None = None, pool=Depends(get_pool)):
    params: list = []
    where = ""
    if parse_status:
        params.append(parse_status)
        where = "WHERE parse_status = $1"
    params.extend([page_size, (page - 1) * page_size])
    rows = await pool.fetch(
        f"""
        SELECT file_id, file_name, source_type, regulator, publish_date,
               parse_status, created_at
        FROM documents {where}
        ORDER BY created_at DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    total = await pool.fetchval(
        f"SELECT COUNT(*) FROM documents {where}",
        *(params[:-2]),
    )
    return {"total": total, "page": page, "page_size": page_size,
            "items": [dict(r) for r in rows]}
