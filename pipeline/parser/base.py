"""解析器基础数据结构与接口。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParseResult:
    """解析结果"""
    success: bool
    markdown: str                    # 正文 Markdown
    tables: list[str] = field(default_factory=list)   # 表格 HTML 列表
    metadata: dict = field(default_factory=dict)
    confidence: float = 0.0          # 全局置信度 0-1
    error: Optional[str] = None


@dataclass
class RawDocument:
    """原始文档"""
    file_id: str
    file_path: str
    file_name: str
    mime_type: str
    source_url: Optional[str] = None


class BaseParser(ABC):
    """解析器基类"""

    @abstractmethod
    def parse(self, doc: RawDocument) -> ParseResult:
        ...

    @abstractmethod
    def supports(self, mime_type: str) -> bool:
        ...
