"""MinerU 长文本决定书解析器（CLI 调用，GPU 环境）。"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from pipeline.parser.base import BaseParser, ParseResult, RawDocument

logger = logging.getLogger(__name__)


class MinerUParser(BaseParser):
    def __init__(self, engine: str = "hybrid", timeout: int = 300):
        self.engine = engine
        self.timeout = timeout

    def supports(self, mime_type: str) -> bool:
        return mime_type in ("application/pdf",
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    def parse(self, doc: RawDocument) -> ParseResult:
        output_dir = Path(tempfile.gettempdir()) / "mineru_output" / doc.file_id

        result = subprocess.run(
            ["magic-pdf", "-p", doc.file_path, "-o", str(output_dir), "-m", self.engine],
            capture_output=True, text=True, timeout=self.timeout,
        )

        if result.returncode != 0:
            return ParseResult(success=False, markdown="", confidence=0.0, error=result.stderr)

        md_path = output_dir / doc.file_id / "auto" / f"{doc.file_id}.md"
        layout_path = output_dir / doc.file_id / "auto" / f"{doc.file_id}_layout.json"

        markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        tables, confidence = self._extract_tables_and_confidence(layout_path)

        return ParseResult(
            success=bool(markdown),
            markdown=markdown,
            tables=tables,
            metadata={"parser": "MinerU", "engine": self.engine},
            confidence=confidence,
            error=None if markdown else "empty markdown output",
        )

    @staticmethod
    def _extract_tables_and_confidence(layout_path: Path) -> tuple[list[str], float]:
        if not layout_path.exists():
            return [], 0.5  # 无 layout 时给中性置信度

        data = json.loads(layout_path.read_text(encoding="utf-8"))
        blocks = data.get("blocks", [])
        tables = [b["html"] for b in blocks if b.get("type") == "table" and b.get("html")]
        scores = [b.get("score", 0) for b in blocks]
        confidence = sum(scores) / len(scores) if scores else 0.0
        return tables, confidence
