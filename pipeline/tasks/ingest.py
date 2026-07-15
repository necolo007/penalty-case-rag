"""ARQ 后台任务：文档解析入库（长任务异步执行）。

启动：arq pipeline.tasks.ingest.WorkerSettings
"""

import logging
from pathlib import Path

from arq.connections import RedisSettings

from core.config import get_settings
from core.db import create_pool
from engine.classification.insurance_filter import InsuranceFilter
from engine.classification.risk_tagger import RiskTagger
from engine.embedding.provider import create_embedding_provider
from engine.llm.client import create_llm_client
from pipeline.extraction.extractor import ExtractorEngine
from pipeline.ingestion.orchestrator import IngestOrchestrator
from pipeline.parser.base import RawDocument
from pipeline.parser.router import DocumentRouter

logger = logging.getLogger(__name__)


def _resolve_upload_path(file_path: str) -> str:
    """将任务中的路径解析为当前环境可读路径。

    本机 API 可能入队 Windows 相对路径（uploads\\F000003.pdf）；
    Docker Worker 的 UPLOAD_DIR=/app/uploads，需用 basename 重拼。
    """
    raw = Path(file_path.replace("\\", "/"))
    if raw.is_file():
        return str(raw)

    upload_dir = Path(get_settings().UPLOAD_DIR)
    candidate = upload_dir / raw.name
    if candidate.is_file():
        return str(candidate)

    # 兼容仅传文件名、以及仍带相对目录的情况
    for alt in (upload_dir / Path(file_path).name, Path(file_path)):
        if alt.is_file():
            return str(alt)

    raise FileNotFoundError(
        f"upload file not found: {file_path!r} (tried {candidate})"
    )


async def ingest_document(ctx, file_id: str, file_path: str, file_name: str,
                          mime_type: str, regulator: str | None = None,
                          publish_date: str | None = None) -> dict:
    orchestrator: IngestOrchestrator = ctx["orchestrator"]
    try:
        resolved = _resolve_upload_path(file_path)
    except FileNotFoundError as e:
        logger.error("%s", e)
        pool = ctx["pool"]
        await pool.execute(
            "UPDATE documents SET parse_status = 'failed', parse_error = $2 WHERE file_id = $1",
            file_id, str(e),
        )
        return {"status": "failed", "file_id": file_id, "error": str(e)}

    doc = RawDocument(
        file_id=file_id, file_path=resolved, file_name=file_name, mime_type=mime_type,
    )
    try:
        return await orchestrator.ingest_document(
            doc, regulator=regulator, publish_date=publish_date,
        )
    except Exception as e:
        logger.exception("Ingest failed for %s", file_id)
        pool = ctx["pool"]
        await pool.execute(
            "UPDATE documents SET parse_status = 'failed', parse_error = $2 WHERE file_id = $1",
            file_id, str(e),
        )
        return {"status": "failed", "file_id": file_id, "error": str(e)}


async def startup(ctx):
    settings = get_settings()
    pool = await create_pool()
    llm = create_llm_client(settings) if settings.LLM_API_KEY else None
    embedder = create_embedding_provider(settings)

    # Worker 环境无 MinerU/OCR 时可自动降级到 pdfplumber 纯文本。
    # Paddle + Torch(MinerU) 同进程易 SIGSEGV：若两者皆在，优先保留 OCR。
    try:
        import importlib.util
        enable_mineru = importlib.util.find_spec("magic_pdf") is not None
        enable_ocr = (
            importlib.util.find_spec("rapidocr_onnxruntime") is not None
            or importlib.util.find_spec("paddleocr") is not None
        )
        if enable_mineru and enable_ocr:
            logger.warning(
                "Both magic_pdf and OCR backend detected; disabling MinerU to avoid "
                "Paddle/Torch SIGSEGV. Use separate workers for MinerU if needed."
            )
            enable_mineru = False
    except Exception:  # noqa: BLE001
        enable_mineru = enable_ocr = False

    ctx["pool"] = pool
    ctx["orchestrator"] = IngestOrchestrator(
        pool=pool,
        router=DocumentRouter(
            mineru_engine=settings.MINERU_ENGINE,
            enable_mineru=enable_mineru,
            enable_ocr=enable_ocr,
        ),
        extractor=ExtractorEngine(llm_client=llm),
        insurance_filter=InsuranceFilter(dict_dir=f"{settings.DATA_DIR}/dictionaries"),
        risk_tagger=RiskTagger(pool, llm_client=llm),
        embedder=embedder,
        llm=llm,
        data_dir=settings.DATA_DIR,
    )
    logger.info("Ingest worker started (mineru=%s, ocr=%s)", enable_mineru, enable_ocr)


async def shutdown(ctx):
    from core.db import close_pool

    await close_pool()


class WorkerSettings:
    functions = [ingest_document]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    max_jobs = 4
    job_timeout = 600
