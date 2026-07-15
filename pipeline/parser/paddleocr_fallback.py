"""OCR 兜底解析：优先 RapidOCR（ONNX，Docker 友好），其次 PaddleOCR。

扫描件 / MinerU 置信度不足时使用。Paddle + Torch 同进程易 SIGSEGV，
Docker OCR 镜像只装 rapidocr-onnxruntime。
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
        self._backend: str | None = None
        self._engine = None

    def _get_engine(self):
        if self._engine is not None:
            return self._backend, self._engine

        try:
            from rapidocr_onnxruntime import RapidOCR

            self._backend = "rapidocr"
            self._engine = RapidOCR()
            logger.info("OCR backend: RapidOCR (onnxruntime)")
            return self._backend, self._engine
        except ImportError:
            pass

        try:
            from paddleocr import PaddleOCR

            self._backend = "paddleocr"
            self._engine = PaddleOCR(use_angle_cls=True, lang=self.lang, show_log=False)
            logger.info("OCR backend: PaddleOCR")
            return self._backend, self._engine
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "No OCR backend available. Install rapidocr-onnxruntime "
                "(Docker) or paddleocr (Linux)."
            ) from exc

    def supports(self, mime_type: str) -> bool:
        return mime_type in ("application/pdf", "image/png", "image/jpeg", "image/jpg")

    def parse(self, doc: RawDocument) -> ParseResult:
        try:
            backend, engine = self._get_engine()
            if backend == "rapidocr":
                return self._parse_rapidocr(engine, doc)
            return self._parse_paddleocr(engine, doc)
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

    def _parse_paddleocr(self, engine, doc: RawDocument) -> ParseResult:
        result = engine.ocr(doc.file_path, cls=True)
        lines: list[str] = []
        scores: list[float] = []
        for page in result or []:
            for item in page or []:
                text, score = item[1]
                lines.append(text)
                scores.append(float(score))

        markdown = "\n".join(lines)
        confidence = sum(scores) / len(scores) if scores else 0.0
        return ParseResult(
            success=bool(markdown),
            markdown=markdown,
            metadata={"parser": "PaddleOCR"},
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

        import fitz  # pymupdf

        pdf = fitz.open(doc.file_path)
        try:
            for page in pdf:
                pix = page.get_pixmap(dpi=200, alpha=False)
                yield pix.tobytes("png")
        finally:
            pdf.close()


# 兼容旧导入名
PaddleOCRFallback = OCRFallback
