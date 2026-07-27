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
from engine.classification.competition_label_map import (
    format_submission_risk_type,
    normalize_cn_tags,
    resolve_final_cn_tags,
)
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


def _finalize_cn_tags(req: RetrieveRequest, retrieval, llm_risk_names: list[str] | None = None) -> list[str]:
    """最终对外分类：27 类中文标签；R00x 仅兜底。"""
    from core.config import get_settings
    settings = get_settings()
    case_tags = [
        t for r in retrieval.results[: settings.TAG_BACKFILL_TOP_CASES]
        for t in (r.risk_tags or [])
    ]
    return resolve_final_cn_tags(
        query_text=req.query_text,
        keyword_tags=getattr(retrieval, "predicted_cn_tags", None),
        case_tags=case_tags,
        llm_tags=llm_risk_names,
        competition_ids=retrieval.predicted_risk_ids,
        max_tags=settings.CN_TAG_FINAL_MAX,
    )


async def _build_submission(req: RetrieveRequest, retriever, generator,
                            risk_predictor) -> SubmissionResponse:
    """改写 → 四路检索 → 多风险类型判断 → 审查建议生成，输出 submission schema"""
    retrieval = await retriever.retrieve(_to_search_query(req))

    suggestion = ""
    reasons = {r.case_id: r.match_reason for r in retrieval.results}
    llm_risk_names: list[str] = []

    if generator is not None and retrieval.results:
        review = generator.generate(req.query_text, retrieval.results)
        if review.get("risk_types"):
            llm_risk_names = normalize_cn_tags(list(review["risk_types"]))
        suggestion = review.get("suggestion", "")
        for a in review.get("case_analysis", []):
            if a.get("case_id") and a.get("similarity_reason"):
                reasons[a["case_id"]] = a["similarity_reason"]

    cn_tags = _finalize_cn_tags(req, retrieval, llm_risk_names)
    # 始终以 27 类中文标签提交；competition 风格仅影响是否允许 LLM 长描述，最终仍归一化
    risk_type = format_submission_risk_type(
        cn_tags=cn_tags,
        competition_ids=retrieval.predicted_risk_ids,
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
    cn_tags = _finalize_cn_tags(req, retrieval)
    return RetrieveResponse(
        query=retrieval.query,
        rewritten_query=retrieval.rewritten_query,
        predicted_risk_ids=retrieval.predicted_risk_ids,
        predicted_cn_tags=cn_tags,
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
    """读取 test_questions.jsonl，生成 retrieval_submission.jsonl（失败写入 submission_errors.jsonl）。"""
    import time

    started = time.perf_counter()
    content = (await file.read()).decode("utf-8")
    questions = [json.loads(line) for line in content.splitlines() if line.strip()]
    if not questions:
        raise HTTPException(400, detail="empty test questions file")

    eval_dir = Path(get_settings().DATA_DIR) / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    output = eval_dir / "retrieval_submission.jsonl"
    errors_out = eval_dir / "submission_errors.jsonl"

    ok_rows: list[str] = []
    err_rows: list[str] = []
    seen_ids: set[str] = set()

    for q in questions:
        qid = str(q.get("question_id") or "").strip()
        req = RetrieveRequest(
            query_text=q["query_text"],
            question_id=qid or None,
            scene=q.get("scene"),
            top_k=top_k,
        )
        try:
            if not qid:
                raise ValueError("missing question_id")
            if qid in seen_ids:
                raise ValueError(f"duplicate question_id: {qid}")
            seen_ids.add(qid)

            submission = await _build_submission(req, retriever, generator, risk_predictor)
            payload = submission.model_dump()
            # 禁止空 risk_type / 空 retrieved_cases / 额外字段进入最终提交
            if not (payload.get("risk_type") or "").strip():
                raise ValueError("empty risk_type")
            if not payload.get("retrieved_cases"):
                raise ValueError("empty retrieved_cases")
            # 严格四字段
            clean = {
                "question_id": payload["question_id"],
                "risk_type": payload["risk_type"],
                "retrieved_cases": payload["retrieved_cases"],
                "suggestion": payload.get("suggestion") or "",
            }
            ok_rows.append(json.dumps(clean, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001 - 单条失败不中断批量
            logger.exception("Batch item failed: %s", qid)
            err_rows.append(json.dumps({
                "question_id": qid,
                "error": str(e),
                "query_text": (q.get("query_text") or "")[:200],
            }, ensure_ascii=False))

    output.write_text("\n".join(ok_rows) + ("\n" if ok_rows else ""), encoding="utf-8")
    errors_out.write_text("\n".join(err_rows) + ("\n" if err_rows else ""), encoding="utf-8")

    took_ms = int((time.perf_counter() - started) * 1000)
    return {
        "total": len(questions),
        "submitted": len(ok_rows),
        "failed": len(err_rows),
        "unique_question_ids": len(seen_ids),
        "output_path": str(output),
        "errors_path": str(errors_out),
        "took_ms": took_ms,
        "schema_ok": len(ok_rows) == len(questions) and len(err_rows) == 0,
    }
