"""合规审查路由（任务4）：单句审查 / 整篇材料审查 / 人工复核反馈。"""

import json
import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from api.dependencies import get_generator, get_material_reviewer, get_pool, get_retriever
from api.schemas.models import FeedbackRequest, MaterialReviewRequest, ReviewGenerateRequest
from engine.retrieval.base import SearchQuery
from pipeline.parser.base import RawDocument
from pipeline.parser.simple_parsers import PlainTextParser, PPTParser, WordParser

logger = logging.getLogger(__name__)
router = APIRouter()

MATERIAL_EXTS = {".txt", ".docx", ".pdf", ".pptx"}


@router.post("/generate")
async def generate_review(
    req: ReviewGenerateRequest,
    retriever=Depends(get_retriever),
    generator=Depends(get_generator),
    pool=Depends(get_pool),
):
    """单句合规审查意见生成"""
    if generator is None:
        raise HTTPException(503, detail="LLM not configured, review generation unavailable")

    import time

    started = time.perf_counter()
    retrieval = await retriever.retrieve(
        SearchQuery(query_text=req.query_text, top_k=req.top_k)
    )
    review = generator.generate(req.query_text, retrieval.results)

    review_id = str(uuid.uuid4())
    await pool.execute(
        """
        INSERT INTO review_logs (review_id, query_text, rewritten_query, risk_types,
                                 suggestion, raw_response)
        VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb)
        """,
        review_id, req.query_text, retrieval.rewritten_query,
        review.get("risk_types", []), review.get("suggestion", ""),
        json.dumps(review, ensure_ascii=False),
    )
    for rank, r in enumerate(retrieval.results, start=1):
        await pool.execute(
            """
            INSERT INTO review_case_refs (review_id, case_id, rank, relevance, reason)
            VALUES ($1::uuid, $2, $3, $4, $5) ON CONFLICT DO NOTHING
            """,
            review_id, r.case_id, rank, "medium", r.match_reason,
        )

    took_ms = int((time.perf_counter() - started) * 1000)
    return {
        "review_id": review_id,
        "query_text": req.query_text,
        "rewritten_query": retrieval.rewritten_query,
        **review,
        "took_ms": took_ms,
    }


@router.post("/material")
async def review_material(
    req: MaterialReviewRequest,
    reviewer=Depends(get_material_reviewer),
):
    """整篇材料合规审查（粘贴文本）"""
    if reviewer is None:
        raise HTTPException(503, detail="LLM not configured, material review unavailable")
    report = await reviewer.review(req.text, scene=req.scene, source_type="paste")
    return report.to_dict()


@router.post("/material/upload")
async def review_material_upload(
    file: UploadFile = File(...),
    scene: str | None = Form(None),
    reviewer=Depends(get_material_reviewer),
):
    """上传材料文件审查 (txt/docx/pdf/pptx)"""
    if reviewer is None:
        raise HTTPException(503, detail="LLM not configured, material review unavailable")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in MATERIAL_EXTS:
        raise HTTPException(400, detail=f"unsupported material type: {ext}")

    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        text = _extract_material_text(tmp_path, ext, file.filename or "material")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not text.strip():
        raise HTTPException(422, detail="no text extracted from material")

    report = await reviewer.review(
        text, scene=scene, source_type="upload", file_name=file.filename,
    )
    return report.to_dict()


def _extract_material_text(file_path: str, ext: str, file_name: str) -> str:
    doc = RawDocument(file_id="material", file_path=file_path,
                      file_name=file_name, mime_type="")
    if ext == ".txt":
        doc.mime_type = "text/plain"
        return PlainTextParser().parse(doc).markdown
    if ext == ".docx":
        doc.mime_type = WordParser.MIME
        return WordParser().parse(doc).markdown
    if ext == ".pptx":
        doc.mime_type = PPTParser.MIME
        return PPTParser().parse(doc).markdown
    # pdf：pdfplumber 纯文本（材料审查不需要精细版式还原）
    from pipeline.parser.router import PdfPlumberTextParser

    doc.mime_type = "application/pdf"
    return PdfPlumberTextParser().parse(doc).markdown


@router.get("/material/{material_id}")
async def get_material_report(material_id: str, pool=Depends(get_pool)):
    """查询材料审查报告（含风险句高亮位置）"""
    material = await pool.fetchrow(
        "SELECT * FROM material_reviews WHERE material_id = $1::uuid", material_id,
    )
    if material is None:
        raise HTTPException(404, detail="material not found")

    sentences = await pool.fetch(
        """
        SELECT s.*, r.risk_types, r.suggestion AS sentence_suggestion, r.raw_response
        FROM risk_sentences s
        LEFT JOIN review_logs r ON s.review_id = r.review_id
        WHERE s.material_id = $1::uuid
        ORDER BY s.position_start
        """,
        material_id,
    )
    return {
        **dict(material),
        "risk_sentence_details": [dict(s) for s in sentences],
    }


@router.get("/{review_id}")
async def get_review(review_id: str, pool=Depends(get_pool)):
    """查询历史审查记录"""
    row = await pool.fetchrow(
        "SELECT * FROM review_logs WHERE review_id = $1::uuid", review_id,
    )
    if row is None:
        raise HTTPException(404, detail="review not found")

    refs = await pool.fetch(
        """
        SELECT ref.case_id, ref.rank, ref.relevance, ref.reason,
               c.party_name, c.violation_behavior, c.penalty_content
        FROM review_case_refs ref
        JOIN penalty_cases c ON ref.case_id = c.case_id
        WHERE ref.review_id = $1::uuid
        ORDER BY ref.rank
        """,
        review_id,
    )
    return {**dict(row), "case_refs": [dict(r) for r in refs]}


@router.patch("/{review_id}/feedback")
async def submit_feedback(review_id: str, body: FeedbackRequest, pool=Depends(get_pool)):
    """提交人工复核反馈（agree / disagree / partial）"""
    result = await pool.execute(
        """
        UPDATE review_logs SET feedback = $2, feedback_note = $3, reviewer = $4
        WHERE review_id = $1::uuid
        """,
        review_id, body.feedback, body.feedback_note, body.reviewer,
    )
    if result == "UPDATE 0":
        raise HTTPException(404, detail="review not found")
    return {"review_id": review_id, "feedback": body.feedback}
