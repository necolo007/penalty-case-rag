"""评测路由（任务5）：检索指标 Recall@K / MRR / NDCG@K / Top-1。"""

import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.dependencies import get_retriever
from engine.retrieval.base import SearchQuery
from scripts.eval_metrics import compute_retrieval_metrics

router = APIRouter()


@router.post("/retrieval")
async def eval_retrieval(
    gold_file: UploadFile = File(..., description="test_gold_labels.jsonl"),
    submission_file: UploadFile = File(..., description="submission.jsonl"),
    k_values: str = "5,10",
):
    """离线评测：对比 submission 与 gold 标签"""
    gold_lines = (await gold_file.read()).decode("utf-8").splitlines()
    sub_lines = (await submission_file.read()).decode("utf-8").splitlines()
    gold = [json.loads(l) for l in gold_lines if l.strip()]
    submission = [json.loads(l) for l in sub_lines if l.strip()]
    if not gold or not submission:
        raise HTTPException(400, detail="empty gold or submission file")

    ks = [int(k) for k in k_values.split(",")]
    return compute_retrieval_metrics(submission, gold, k_values=ks)


@router.post("/run")
async def eval_run(
    queries_file: UploadFile = File(..., description="retrieval_train_queries.jsonl"),
    top_k: int = 10,
    retriever=Depends(get_retriever),
):
    """一键在线评测：对训练 query 直接执行检索并计算指标"""
    lines = (await queries_file.read()).decode("utf-8").splitlines()
    queries = [json.loads(l) for l in lines if l.strip()]
    if not queries:
        raise HTTPException(400, detail="empty queries file")

    submission, gold = [], []
    for q in queries:
        retrieval = await retriever.retrieve(
            SearchQuery(query_text=q["query_text"], scene=q.get("scene"), top_k=top_k)
        )
        submission.append({
            "question_id": q.get("query_id"),
            "retrieved_cases": [
                {"case_id": r.case_id, "rank": i + 1}
                for i, r in enumerate(retrieval.results)
            ],
        })
        gold.append({
            "question_id": q.get("query_id"),
            "relevant_cases": q.get("relevant_cases", []),
        })

    metrics = compute_retrieval_metrics(submission, gold, k_values=[5, 10])
    return {"total_queries": len(queries), "metrics": metrics}
