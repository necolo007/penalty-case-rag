"""DocumentRouter：根据 MIME 类型 / PDF 类型分流到对应解析器。

PDF 分流：
  公示表 → TableParser (pdfplumber)
  决定书 → MinerUParser（不可用时降级 pdfplumber 纯文本）
  扫描件 / 低置信度 → OCRFallback（RapidOCR，仅 Docker Worker）
"""

import logging

from pipeline.parser.base import BaseParser, ParseResult, RawDocument
from pipeline.parser.paddleocr_fallback import CONFIDENCE_THRESHOLD, PaddleOCRFallback
from pipeline.parser.pdf_type_router import PDFType, detect_pdf_type
from pipeline.parser.simple_parsers import HTMLParser, PlainTextParser, PPTParser, WordParser
from pipeline.parser.table_parser import TableParser

logger = logging.getLogger(__name__)


class PdfPlumberTextParser(BaseParser):
    """MinerU 不可用时的决定书降级解析：pdfplumber 纯文本抽取。"""

    def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf"

    def parse(self, doc: RawDocument) -> ParseResult:
        import pdfplumber

        try:
            with pdfplumber.open(doc.file_path) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            text = "\n\n".join(p for p in pages if p.strip())
            return ParseResult(
                success=bool(text), markdown=text,
                metadata={"parser": "PdfPlumberText"},
                confidence=0.7 if text else 0.0,
                error=None if text else "no text extracted",
            )
        except Exception as e:  # noqa: BLE001
            return ParseResult(success=False, markdown="", error=str(e))


class DocumentRouter:
    def __init__(
        self,
        mineru_engine: str = "hybrid",
        enable_mineru: bool = True,
        enable_ocr: bool = True,
        *,
        confidence_threshold: float | None = None,
    ):
        if confidence_threshold is None:
            try:
                from core.config import get_settings
                confidence_threshold = get_settings().PARSE_CONFIDENCE_THRESHOLD
            except Exception:  # noqa: BLE001
                confidence_threshold = CONFIDENCE_THRESHOLD
        self.confidence_threshold = confidence_threshold
        self.table_parser = TableParser()
        self.text_pdf_parser: BaseParser
        if enable_mineru:
            from pipeline.parser.mineru_parser import MinerUParser

            self.text_pdf_parser = MinerUParser(engine=mineru_engine)
        else:
            self.text_pdf_parser = PdfPlumberTextParser()
        self.pdfplumber_fallback = PdfPlumberTextParser()
        self.ocr = PaddleOCRFallback() if enable_ocr else None
        self.word = WordParser()
        self.html = HTMLParser()
        self.ppt = PPTParser()
        self.txt = PlainTextParser()

    def parse(self, doc: RawDocument) -> ParseResult:
        if doc.mime_type == "application/pdf":
            return self._parse_pdf(doc)
        for parser in (self.word, self.html, self.ppt, self.txt):
            if parser.supports(doc.mime_type):
                return parser.parse(doc)
        return ParseResult(success=False, markdown="",
                           error=f"unsupported mime type: {doc.mime_type}")

    def _parse_pdf(self, doc: RawDocument) -> ParseResult:
        pdf_type = detect_pdf_type(doc.file_path)
        logger.info("PDF %s detected as %s", doc.file_id, pdf_type.value)

        if pdf_type == PDFType.SCANNED:
            return self._ocr_or_fail(doc, reason="scanned pdf")

        if pdf_type == PDFType.TABLE_DISCLOSURE:
            result = self.table_parser.parse(doc)
            if result.success and result.confidence >= self.confidence_threshold:
                return result
            logger.info("Table parsing weak (conf=%.2f), fallback to text pipeline",
                        result.confidence)

        # 决定书 / 表格解析失败 → 长文本管线
        result = self._parse_text_pdf(doc)
        if result.success and result.confidence >= self.confidence_threshold:
            return result

        # 置信度不足 → OCR 兜底
        ocr_result = self._ocr_or_fail(doc, reason=f"low confidence {result.confidence:.2f}")
        return ocr_result if ocr_result.success else result

    def _parse_text_pdf(self, doc: RawDocument) -> ParseResult:
        result = self.text_pdf_parser.parse(doc)
        if not result.success and not isinstance(self.text_pdf_parser, PdfPlumberTextParser):
            logger.warning("MinerU failed (%s), fallback to pdfplumber text", result.error)
            return self.pdfplumber_fallback.parse(doc)
        return result

    def _ocr_or_fail(self, doc: RawDocument, reason: str) -> ParseResult:
        if self.ocr is None:
            return ParseResult(success=False, markdown="",
                               error=f"OCR disabled but needed: {reason}")
        logger.info("OCR fallback for %s: %s", doc.file_id, reason)
        return self.ocr.parse(doc)
