"""案例检索路由（任务3核心）：单条检索 / 比赛格式 / 批量 submission。"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from api.dependencies import get_generator, get_retriever, get_risk_predictor
from api.schemas.models import (
    CaseResult,
    RetrieveRequest,
    RetrieveResponse,
    SubmissionCase,
    SubmissionResponse,
)
from core.config import get_settings
from core.config import get_settings
from engine.classification.competition_label_map import (
    competition_ids_to_cn_tags,
    format_submission_risk_type,
    predict_cn_tags_by_keywords,
)
from engine.classification.tag_mapper import competition_name
from engine.retrieval.base import SearchQuery

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_search_query(req: RetrieveRequest) -> SearchQuery:
    return SearchQuery(
        query_text=req.query_text,
        question_id=req.question_id,
        scene=req.scene,
        risk_type=req.risk_type,
        regulator=req.regulator,
        institution_type=req.institution_type,
        date_from=req.date_from,
        date_to=req.date_to,
        top_k=req.top_k,
        use_reranker=req.use_reranker,
    )


async def _build_submission(req: RetrieveRequest, retriever, generator,
                            risk_predictor) -> SubmissionResponse:
    """改写 → 四路检索 → 多风险类型判断 → 审查建议生成，输出 submission schema"""
    retrieval = await retriever.retrieve(_to_search_query(req))

    # 中文标签：规则关键词 + Top 案例标签并集
    cn_tags = list(dict.fromkeys([
        *predict_cn_tags_by_keywords(req.query_text),
        *[t for r in retrieval.results[:3] for t in (r.risk_tags or [])],
    ]))[:5]
    if not cn_tags:
        cn_tags = competition_ids_to_cn_tags(retrieval.predicted_risk_ids)

    suggestion = ""
    reasons = {r.case_id: r.match_reason for r in retrieval.results}
    llm_risk_names: list[str] = []

    if generator is not None and retrieval.results:
        review = generator.generate(req.query_text, retrieval.results)
        if review.get("risk_types"):
            llm_risk_names = list(review["risk_types"])
            for name in llm_risk_names:
                if name and not str(name).startswith("R0") and name not in cn_tags:
                    cn_tags.append(name)
        suggestion = review.get("suggestion", "")
        for a in review.get("case_analysis", []):
            if a.get("case_id") and a.get("similarity_reason"):
                reasons[a["case_id"]] = a["similarity_reason"]

    if get_settings().SUBMISSION_RISK_STYLE == "competition":
        names = llm_risk_names or [competition_name(rid) for rid in retrieval.predicted_risk_ids]
        risk_type = "；".join(dict.fromkeys(names))
    else:
        risk_type = format_submission_risk_type(
            cn_tags=cn_tags, competition_ids=retrieval.predicted_risk_ids,
        )

    return SubmissionResponse(
        question_id=req.question_id,
        risk_type=risk_type,
        retrieved_cases=[
            SubmissionCase(case_id=r.case_id, rank=i + 1,
                           reason=reasons.get(r.case_id, r.match_reason))
            for i, r in enumerate(retrieval.results)
        ],
        suggestion=suggestion,
    )


@router.post("/retrieve")
async def retrieve_similar_cases(
    req: RetrieveRequest,
    format: str | None = Query(None, description="submission 时输出比赛格式"),
    retriever=Depends(get_retriever),
    generator=Depends(get_generator),
    risk_predictor=Depends(get_risk_predictor),
):
    """相似处罚案例检索（核心）。format=submission 时输出比赛 jsonl schema。"""
    if format == "submission":
        return await _build_submission(req, retriever, generator, risk_predictor)

    retrieval = await retriever.retrieve(_to_search_query(req))
    return RetrieveResponse(
        query=retrieval.query,
        rewritten_query=retrieval.rewritten_query,
        predicted_risk_ids=retrieval.predicted_risk_ids,
        results=[
            CaseResult(
                rank=i + 1,
                case_id=r.case_id,
                party_name=r.party_name,
                penalty_doc_no=r.penalty_doc_no,
                violation_behavior=r.violation_behavior,
                penalty_content=r.penalty_content,
                regulator=r.regulator,
                risk_tags=r.risk_tags,
                score=round(r.score, 4),
                match_reason=r.match_reason,
                source_file=r.source_file,
                channels=r.channels,
            )
            for i, r in enumerate(retrieval.results)
        ],
        channel_stats=retrieval.channel_stats,
        took_ms=retrieval.took_ms,
    )


@router.post("/batch-submission")
async def batch_submission(
    file: UploadFile = File(...),
    top_k: int = 5,
    retriever=Depends(get_retriever),
    generator=Depends(get_generator),
    risk_predictor=Depends(get_risk_predictor),
):
    """读取 test_questions.jsonl 批量生成 submission.jsonl"""
    import time

    started = time.perf_counter()
    content = (await file.read()).decode("utf-8")
    questions = [json.loads(line) for line in content.splitlines() if line.strip()]
    if not questions:
        raise HTTPException(400, detail="empty test questions file")

    output = Path(get_settings().DATA_DIR) / "eval" / "submission.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as f:
        for q in questions:
            req = RetrieveRequest(
                query_text=q["query_text"],
                question_id=q.get("question_id"),
                scene=q.get("scene"),
                top_k=top_k,
            )
            try:
                submission = await _build_submission(req, retriever, generator, risk_predictor)
                f.write(submission.model_dump_json() + "\n")
            except Exception as e:  # noqa: BLE001 - 单条失败不中断批量
                logger.exception("Batch item failed: %s", q.get("question_id"))
                f.write(json.dumps({
                    "question_id": q.get("question_id"),
                    "risk_type": "",
                    "retrieved_cases": [],
                    "suggestion": "",
                    "error": str(e),
                }, ensure_ascii=False) + "\n")

    took_ms = int((time.perf_counter() - started) * 1000)
    return {"total": len(questions), "output_path": str(output), "took_ms": took_ms}
