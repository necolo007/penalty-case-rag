"""批量入库：扫描目录或读取 jsonl 清单（path 字段）。

用法：
  python scripts/batch_ingest.py --dir data/raw
  python scripts/batch_ingest.py --manifest path/to/ingest_manifest.jsonl --limit 50
"""

import argparse
import asyncio
import importlib.util
import json
from pathlib import Path

from core.config import get_settings
from core.db import close_pool, create_pool
from core.ids import next_file_id
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
INSURANCE_NAME_KEYS = (
    "人寿保险", "财产保险", "健康保险", "养老保险", "保险股份",
    "保险代理", "保险经纪", "保险公估", "相互保险", "再保险",
    "人寿", "财险", "产险", "寿险", "健康险", "养老险",
)


def _load_manifest(path: Path) -> list[Path]:
    files: list[Path] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            p = Path(row.get("path") or row.get("file_path") or "")
            if p.is_file():
                files.append(p)
    return files


def _collect_files(
    *,
    directory: Path | None,
    manifest: Path | None,
    prefer_pdf: bool,
    insurance_only: bool,
    limit: int | None,
) -> list[Path]:
    if manifest is not None:
        files = _load_manifest(manifest)
    elif directory is not None:
        raw = [
            p for p in directory.rglob("*")
            if p.is_file() and p.suffix.lower() in MIME_BY_EXT
        ]
        if prefer_pdf:
            by_stem: dict[str, list[Path]] = {}
            for p in raw:
                by_stem.setdefault(p.stem.lower(), []).append(p)
            files = []
            for group in by_stem.values():
                pdfs = [p for p in group if p.suffix.lower() == ".pdf"]
                files.append(pdfs[0] if pdfs else group[0])
        else:
            files = raw
    else:
        raise ValueError("必须指定 --dir 或 --manifest")

    files = sorted(files)
    if insurance_only:
        files = [p for p in files if any(k in p.name for k in INSURANCE_NAME_KEYS)]
    if limit is not None and limit > 0:
        files = files[:limit]
    return files


async def main():
    parser = argparse.ArgumentParser(description="批量入库")
    parser.add_argument("--dir", default=None)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--regulator", default=None)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--prefer-pdf", action="store_true")
    parser.add_argument("--insurance-only", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not args.dir and not args.manifest:
        parser.error("需要 --dir 或 --manifest")

    settings = get_settings()
    pool = await create_pool()
    llm = None if args.no_llm or not settings.LLM_API_KEY else create_llm_client(settings)

    enable_ocr = importlib.util.find_spec("rapidocr_onnxruntime") is not None
    if not enable_ocr:
        print("OCR unavailable — scanned PDFs need: docker compose up -d worker")

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

    files = _collect_files(
        directory=Path(args.dir) if args.dir else None,
        manifest=Path(args.manifest) if args.manifest else None,
        prefer_pdf=args.prefer_pdf,
        insurance_only=args.insurance_only,
        limit=args.limit,
    )
    print(f"Found {len(files)} files (ocr={enable_ocr})")

    ok = failed = 0
    for i, path in enumerate(files, 1):
        file_id = await next_file_id(pool)
        ext = path.suffix.lower()
        if ext not in MIME_BY_EXT:
            print(f"  SKIP {path.name}")
            continue

        await pool.execute(
            """
            INSERT INTO documents (file_id, file_name, source_type, regulator, parse_status)
            VALUES ($1, $2, $3, $4, 'pending')
            """,
            file_id, path.name, SOURCE_TYPE_BY_EXT[ext], args.regulator,
        )
        doc = RawDocument(
            file_id=file_id, file_path=str(path),
            file_name=path.name, mime_type=MIME_BY_EXT[ext],
        )
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
