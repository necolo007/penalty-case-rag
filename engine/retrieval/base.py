"""检索基础数据结构与接口。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RetrievalResponse:
    query: str
    rewritten_query: str
    predicted_risk_ids: list[str]
    results: list["SearchResult"]
    took_ms: int
    channel_stats: dict[str, int] = field(default_factory=dict)
    predicted_cn_tags: list[str] = field(default_factory=list)


@dataclass
class SearchQuery:
    """检索请求（对齐 retrieval_train_queries / test_questions）"""
    query_text: str
    question_id: Optional[str] = None        # 比赛测试题 ID，如 QT001
    scene: Optional[str] = None              # 场景：营销宣传材料/销售话术审核 等
    risk_type: Optional[str] = None          # 按赛题扁平标签 R001–R008 过滤
    regulator: Optional[str] = None
    institution_type: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    top_k: int = 10
    use_reranker: bool = True


@dataclass
class SearchResult:
    """单条检索结果"""
    case_id: str
    party_name: str
    violation_behavior: str
    penalty_content: str
    regulator: str
    risk_tags: list[str]
    score: float                             # 相关性得分
    penalty_doc_no: str = ""
    risk_type_ids: list[str] = field(default_factory=list)
    match_reason: str = ""
    source_file: str = ""
    channels: list[str] = field(default_factory=list)   # 命中的召回通道
    highlight_fields: dict[str, str] = field(default_factory=dict)


def row_to_result(row, score: float, channel: str) -> SearchResult:
    """asyncpg Record → SearchResult"""
    data = dict(row)
    return SearchResult(
        case_id=data["case_id"],
        party_name=data["party_name"],
        violation_behavior=data["violation_behavior"],
        penalty_content=data["penalty_content"],
        regulator=data.get("regulator") or "",
        risk_tags=list(data.get("risk_tags") or []),
        risk_type_ids=list(data.get("risk_type_ids") or []),
        penalty_doc_no=data.get("penalty_doc_no") or "",
        source_file=data.get("source_file") or "",
        score=score,
        channels=[channel],
    )


class BaseRetriever(ABC):
    """检索器基类（单一召回通道）"""

    channel: str = "base"

    @abstractmethod
    async def retrieve(self, query: SearchQuery, **kwargs) -> list[SearchResult]:
        ...
