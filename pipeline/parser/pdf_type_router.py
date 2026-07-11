"""PDF 分流（任务1核心）：公示表 → pdfplumber 表格管线；决定书 → MinerU 长文本管线。

识别策略：抽取首页文本，按特征关键词 + 表格密度判断。
"""

import logging
from enum import Enum

import pdfplumber

logger = logging.getLogger(__name__)


class PDFType(str, Enum):
    TABLE_DISCLOSURE = "table_disclosure"   # 表格型公示表
    DECISION_DOC = "decision_doc"           # 长文本决定书
    SCANNED = "scanned"                     # 扫描件（图片型）


_TABLE_KEYWORDS = ["行政处罚信息公开表", "处罚信息公开表", "公开表"]
_DECISION_KEYWORDS = ["行政处罚决定书", "处罚决定书"]


def detect_pdf_type(file_path: str) -> PDFType:
    try:
        with pdfplumber.open(file_path) as pdf:
            first_page = pdf.pages[0]
            text = first_page.extract_text() or ""
            tables = first_page.find_tables()

            if not text.strip():
                return PDFType.SCANNED

            if any(kw in text for kw in _TABLE_KEYWORDS) or len(tables) >= 1 and len(text) < 800:
                # 公示表：标题命中 或 表格主导且正文短
                if any(kw in text for kw in _TABLE_KEYWORDS) or tables:
                    return PDFType.TABLE_DISCLOSURE

            if any(kw in text for kw in _DECISION_KEYWORDS):
                return PDFType.DECISION_DOC

            # 默认：有表格走表格管线，否则长文本
            return PDFType.TABLE_DISCLOSURE if tables else PDFType.DECISION_DOC
    except Exception as e:  # noqa: BLE001
        logger.warning("PDF type detection failed (%s), fallback to decision_doc", e)
        return PDFType.DECISION_DOC
