"""批量入库 CLI：扫描目录中的 PDF/Word/HTML/TXT 直接走入库编排（不经 API）。

用法：python scripts/batch_ingest.py --dir data/raw --regulator 可选
"""

import argparse
import asyncio
import importlib.util
from pathlib import Path

from core.config import get_settings
from core.db import close_pool, create_pool
from engine.classification.insurance_filter import InsuranceFilter
from engine.classification.risk_tagger import RiskTagger
from engine.embedding.provider import create_embedding_provider
from engine.llm.client import create_llm_client
from pipeline.extraction.extractor import ExtractorEngine
from pipeline.ingestion.orchestrator import IngestOrchestrator
from pipeline.parser.base import RawDocument
from pipeline.parser.router import DocumentRouter

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


async def main():
    parser = argparse.ArgumentParser(description="批量入库")
    parser.add_argument("--dir", required=True, help="原始文件目录")
    parser.add_argument("--regulator", default=None)
    parser.add_argument("--no-llm", action="store_true", help="禁用 LLM（仅规则）")
    args = parser.parse_args()

    settings = get_settings()
    pool = await create_pool()
    llm = None if args.no_llm or not settings.LLM_API_KEY else create_llm_client(settings)

    enable_ocr = (
        importlib.util.find_spec("rapidocr_onnxruntime") is not None
        or importlib.util.find_spec("rapidocr") is not None
        or importlib.util.find_spec("paddleocr") is not None
    )
    orchestrator = IngestOrchestrator(
        pool=pool,
        router=DocumentRouter(
            mineru_engine=settings.MINERU_ENGINE,
            enable_mineru=importlib.util.find_spec("magic_pdf") is not None,
            enable_ocr=enable_ocr,
        ),
        extractor=ExtractorEngine(llm_client=llm),
        insurance_filter=InsuranceFilter(dict_dir=f"{settings.DATA_DIR}/dictionaries"),
        risk_tagger=RiskTagger(pool, llm_client=llm),
        embedder=create_embedding_provider(settings),
        llm=llm,
        data_dir=settings.DATA_DIR,
    )

    files = sorted(
        p for p in Path(args.dir).rglob("*")
        if p.is_file() and p.suffix.lower() in MIME_BY_EXT
    )
    print(f"Found {len(files)} files (ocr={enable_ocr})")

    from core.ids import next_file_id

    ok = failed = 0
    for i, path in enumerate(files, 1):
        file_id = await next_file_id(pool)
        ext = path.suffix.lower()

        await pool.execute(
            """
            INSERT INTO documents (file_id, file_name, source_type, regulator, parse_status)
            VALUES ($1, $2, $3, $4, 'pending')
            """,
            file_id, path.name, SOURCE_TYPE_BY_EXT[ext], args.regulator,
        )
        doc = RawDocument(file_id=file_id, file_path=str(path),
                          file_name=path.name, mime_type=MIME_BY_EXT[ext])
        result = await orchestrator.ingest_document(doc, regulator=args.regulator)
        if result["status"] == "completed":
            ok += 1
        else:
            failed += 1
            print(f"  FAILED {path.name}: {result.get('error')}")
        if i % 20 == 0:
            print(f"  progress: {i}/{len(files)}")

    print(f"Done: {ok} ok, {failed} failed")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
