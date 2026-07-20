"""OCR 兜底解析：RapidOCR（ONNX），仅在 Docker Worker 镜像中安装。

扫描件 / MinerU 置信度不足时使用。请勿在本机 pip 安装 OCR 依赖；
扫描件入库请使用 `docker compose up -d worker`（Dockerfile.worker.ocr）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.parser.base import BaseParser, ParseResult, RawDocument

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.5


class OCRFallback(BaseParser):
    def __init__(self, lang: str = "ch"):
        self.lang = lang
        self._engine = None

    def _get_engine(self):
        if self._engine is not None:
            return self._engine

        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError(
                "RapidOCR not available. Use Docker OCR Worker: "
                "`docker compose build worker && docker compose up -d worker`. "
                "Do not install OCR packages on the host."
            ) from exc

        self._engine = RapidOCR()
        logger.info("OCR backend: RapidOCR (onnxruntime)")
        return self._engine

    def supports(self, mime_type: str) -> bool:
        return mime_type in ("application/pdf", "image/png", "image/jpeg", "image/jpg")

    def parse(self, doc: RawDocument) -> ParseResult:
        try:
            engine = self._get_engine()
            return self._parse_rapidocr(engine, doc)
        except Exception as e:  # noqa: BLE001
            return ParseResult(success=False, markdown="", error=f"OCR failed: {e}")

    def _parse_rapidocr(self, engine, doc: RawDocument) -> ParseResult:
        lines: list[str] = []
        scores: list[float] = []
        for image_bytes in self._iter_page_images(doc):
            result, _ = engine(image_bytes)
            for item in result or []:
                # RapidOCR: [box, text, score]
                text, score = item[1], float(item[2])
                if text and text.strip():
                    lines.append(text.strip())
                    scores.append(score)

        markdown = "\n".join(lines)
        confidence = sum(scores) / len(scores) if scores else 0.0
        return ParseResult(
            success=bool(markdown),
            markdown=markdown,
            metadata={"parser": "RapidOCR"},
            confidence=confidence,
            error=None if markdown else "no text recognized",
        )

    @staticmethod
    def _iter_page_images(doc: RawDocument):
        """PDF 按页渲染为 PNG bytes；图片则读原文件。"""
        path = Path(doc.file_path)
        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            yield path.read_bytes()
            return

        import fitz  # pymupdf（仅 OCR Worker 镜像提供）

        pdf = fitz.open(doc.file_path)
        try:
            for page in pdf:
                pix = page.get_pixmap(dpi=200, alpha=False)
                yield pix.tobytes("png")
        finally:
            pdf.close()


# 兼容旧导入名
PaddleOCRFallback = OCRFallback
