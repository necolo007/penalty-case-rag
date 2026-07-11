"""ARQ 后台任务：文档解析入库（长任务异步执行）。

启动：arq pipeline.tasks.ingest.WorkerSettings
"""

import logging

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


async def ingest_document(ctx, file_id: str, file_path: str, file_name: str,
                          mime_type: str, regulator: str | None = None,
                          publish_date: str | None = None) -> dict:
    orchestrator: IngestOrchestrator = ctx["orchestrator"]
    doc = RawDocument(
        file_id=file_id, file_path=file_path, file_name=file_name, mime_type=mime_type,
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

    # Worker 环境无 MinerU/OCR 时可自动降级到 pdfplumber 纯文本
    try:
        import importlib.util
        enable_mineru = importlib.util.find_spec("magic_pdf") is not None
        enable_ocr = importlib.util.find_spec("paddleocr") is not None
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
