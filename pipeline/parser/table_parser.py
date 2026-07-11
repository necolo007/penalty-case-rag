"""公示表专用表格解析：表头识别、跨页拼接、空单元格补全、多主体拆分。

「行政处罚信息公开表」典型结构：多列表格，每行一个处罚主体，
跨页时表头不重复、单元格断裂需拼接。
"""

import logging

import pdfplumber

from pipeline.parser.base import BaseParser, ParseResult, RawDocument

logger = logging.getLogger(__name__)

# 公示表常见表头 → 标准字段名
HEADER_ALIASES = {
    "party_name": ["当事人名称", "当事人", "被处罚人", "被处罚机构", "单位名称", "姓名"],
    "penalty_doc_no": ["行政处罚决定书文号", "处罚决定书文号", "决定书文号", "文号"],
    "violation_behavior": ["主要违法违规事实", "违法违规事实", "主要违法违规行为", "违法行为", "案由"],
    "penalty_content": ["行政处罚内容", "处罚内容", "处罚决定", "处罚种类及金额"],
    "regulator": ["作出处罚决定的机关名称", "作出处罚决定的机关", "处罚机关", "决定机关"],
    "publish_date": ["作出处罚决定的日期", "处罚决定日期", "作出决定日期", "日期"],
    "legal_basis": ["处罚依据", "行政处罚依据", "法律依据"],
}


def normalize_header(raw: str) -> str | None:
    cell = (raw or "").replace("\n", "").replace(" ", "")
    for field_name, aliases in HEADER_ALIASES.items():
        if any(alias in cell for alias in aliases):
            return field_name
    return None


class TableParser(BaseParser):
    """pdfplumber 公示表解析器"""

    def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf"

    def parse(self, doc: RawDocument) -> ParseResult:
        try:
            records = self.extract_records(doc.file_path)
        except Exception as e:  # noqa: BLE001
            return ParseResult(success=False, markdown="", error=str(e))

        if not records:
            return ParseResult(success=False, markdown="", confidence=0.0,
                               error="no table records extracted")

        markdown = self._records_to_markdown(records)
        # 置信度：核心字段（当事人+违法行为）非空比例
        core_filled = sum(
            1 for r in records if r.get("party_name") and r.get("violation_behavior")
        )
        confidence = core_filled / len(records)

        return ParseResult(
            success=True,
            markdown=markdown,
            tables=[],
            metadata={"parser": "TableParser", "record_count": len(records), "records": records},
            confidence=confidence,
        )

    def extract_records(self, file_path: str) -> list[dict]:
        """跨页拼接 + 表头映射 + 多主体逐行输出"""
        records: list[dict] = []
        header_map: dict[int, str] = {}     # 列索引 → 标准字段（跨页沿用）

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    for row in table:
                        if not row or all(not c for c in row):
                            continue
                        mapped = self._try_map_header(row)
                        if mapped:
                            header_map = mapped
                            continue
                        if not header_map:
                            continue
                        record = self._row_to_record(row, header_map)
                        if record is None:
                            # 空当事人行：视为上一条记录的跨页续行，拼接补全
                            if records:
                                self._merge_continuation(records[-1], row, header_map)
                            continue
                        records.append(record)
        return records

    @staticmethod
    def _try_map_header(row: list) -> dict[int, str] | None:
        mapped = {}
        for idx, cell in enumerate(row):
            std = normalize_header(cell or "")
            if std:
                mapped[idx] = std
        # 命中 2 个以上标准表头才认定为表头行
        return mapped if len(mapped) >= 2 else None

    @staticmethod
    def _row_to_record(row: list, header_map: dict[int, str]) -> dict | None:
        record: dict = {}
        for idx, field_name in header_map.items():
            if idx < len(row):
                value = (row[idx] or "").replace("\n", "").strip()
                record[field_name] = value
        if not record.get("party_name"):
            return None
        return record

    @staticmethod
    def _merge_continuation(prev: dict, row: list, header_map: dict[int, str]) -> None:
        for idx, field_name in header_map.items():
            if idx < len(row) and row[idx]:
                extra = row[idx].replace("\n", "").strip()
                if extra:
                    prev[field_name] = (prev.get(field_name, "") + extra).strip()

    @staticmethod
    def _records_to_markdown(records: list[dict]) -> str:
        lines = []
        for i, r in enumerate(records, 1):
            lines.append(f"## 记录 {i}")
            for k, v in r.items():
                lines.append(f"- {k}: {v}")
            lines.append("")
        return "\n".join(lines)
