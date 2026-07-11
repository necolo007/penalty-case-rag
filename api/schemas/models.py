"""API 请求 / 响应 Pydantic 模型。"""

from typing import Optional

from pydantic import BaseModel, Field


# ---------- 检索（任务3） ----------

class RetrieveRequest(BaseModel):
    query_text: str = Field(..., min_length=1, max_length=2000)
    question_id: Optional[str] = None
    scene: Optional[str] = None
    risk_type: Optional[str] = None            # R001–R008
    regulator: Optional[str] = None
    institution_type: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    top_k: int = Field(10, ge=1, le=50)
    use_reranker: bool = True


class CaseResult(BaseModel):
    rank: int
    case_id: str
    party_name: str
    penalty_doc_no: str
    violation_behavior: str
    penalty_content: str
    regulator: str
    risk_tags: list[str]
    score: float
    match_reason: str
    source_file: str
    channels: list[str] = []


class RetrieveResponse(BaseModel):
    query: str
    rewritten_query: str
    predicted_risk_ids: list[str]
    results: list[CaseResult]
    channel_stats: dict[str, int]
    took_ms: int


class SubmissionCase(BaseModel):
    case_id: str
    rank: int
    reason: str


class SubmissionResponse(BaseModel):
    """严格对齐 submission.jsonl schema"""
    question_id: Optional[str]
    risk_type: str                              # 多类型中文分号拼接
    retrieved_cases: list[SubmissionCase]
    suggestion: str


# ---------- 审查（任务4） ----------

class ReviewGenerateRequest(BaseModel):
    query_text: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)
    generate_suggestion: bool = True


class MaterialReviewRequest(BaseModel):
    text: str = Field(..., min_length=1)
    scene: Optional[str] = None


class FeedbackRequest(BaseModel):
    feedback: str = Field(..., pattern="^(agree|disagree|partial)$")
    feedback_note: Optional[str] = None
    reviewer: Optional[str] = None


# ---------- 文档 / 案例 ----------

class DocumentStatus(BaseModel):
    file_id: str
    file_name: str
    parse_status: str
    parse_error: Optional[str] = None
    created_at: Optional[str] = None


class CasePatchRequest(BaseModel):
    party_name: Optional[str] = None
    penalty_doc_no: Optional[str] = None
    violation_behavior: Optional[str] = None
    penalty_content: Optional[str] = None
    regulator: Optional[str] = None
    legal_basis: Optional[str] = None
    risk_tags: Optional[list[str]] = None
    risk_type_ids: Optional[list[str]] = None
    is_insurance_related: Optional[bool] = None
