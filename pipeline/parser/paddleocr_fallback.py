"""PaddleOCR 扫描件兜底：MinerU 置信度 < 阈值或图片型 PDF 时启用。"""

import logging

from pipeline.parser.base import BaseParser, ParseResult, RawDocument

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.5


class PaddleOCRFallback(BaseParser):
    def __init__(self, lang: str = "ch"):
        self.lang = lang
        self._ocr = None

    def _get_ocr(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR  # 延迟导入：parsing 可选依赖

            self._ocr = PaddleOCR(use_angle_cls=True, lang=self.lang, show_log=False)
        return self._ocr

    def supports(self, mime_type: str) -> bool:
        return mime_type in ("application/pdf", "image/png", "image/jpeg")

    def parse(self, doc: RawDocument) -> ParseResult:
        try:
            ocr = self._get_ocr()
            result = ocr.ocr(doc.file_path, cls=True)
        except Exception as e:  # noqa: BLE001
            return ParseResult(success=False, markdown="", error=f"OCR failed: {e}")

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
