"""Few-shot 库：stats / preview / reload。"""

import logging

from fastapi import APIRouter, HTTPException

from api.dependencies import get_fewshot_bank, state
from api.schemas.models import (
    FewShotExampleOut,
    FewShotPreviewRequest,
    FewShotPreviewResponse,
)
from core.config import get_settings
from engine.classification.competition_label_map import predict_cn_tags_by_keywords
from engine.classification.fewshot import (
    format_fewshot_block,
    get_default_bank,
    reset_default_bank,
    retrieve_fewshot_hits,
)
from engine.classification.risk_tagger import build_cn_tag_user_prompt

logger = logging.getLogger(__name__)

router = APIRouter()


def _config_snapshot() -> dict:
    s = get_settings()
    return {
        "enabled": s.FEWSHOT_ENABLED,
        "bank_path": s.FEWSHOT_BANK_PATH,
        "retriever": s.FEWSHOT_RETRIEVER,
        "top_n": s.FEWSHOT_TOP_N,
        "min_score": s.FEWSHOT_MIN_SCORE,
        "mmr_lambda": s.FEWSHOT_MMR_LAMBDA,
        "rarity_boost": s.FEWSHOT_RARITY_BOOST,
        "max_chars": s.FEWSHOT_MAX_CHARS,
        "max_behavior_chars": s.FEWSHOT_MAX_BEHAVIOR_CHARS,
        "tag_hints": s.FEWSHOT_TAG_HINTS,
    }


@router.get("/stats")
async def fewshot_stats():
    """示例库规模、标签覆盖与当前生效配置。"""
    bank = get_fewshot_bank()
    config = _config_snapshot()
    if bank is None:
        return {
            "loaded": False,
            "reason": (
                "示例库未启用或文件缺失；执行 "
                "python scripts/import_excel_fewshot_bank.py 构库后调用 /reload"
            ),
            "config": config,
        }
    return {"loaded": True, "config": config, "stats": bank.stats()}


@router.post("/preview", response_model=FewShotPreviewResponse)
async def fewshot_preview(req: FewShotPreviewRequest):
    """给定违法事实，返回将注入 Prompt 的示例（含长尾配额补位标记）。"""
    settings = get_settings()
    bank = get_fewshot_bank()
    if bank is None:
        return FewShotPreviewResponse(enabled=False)

    tag_hints = (
        predict_cn_tags_by_keywords(
            req.violation_behavior, max_tags=settings.CN_TAG_PREDICT_MAX
        )
        if req.use_tag_hints and settings.FEWSHOT_TAG_HINTS
        else []
    )
    hits = retrieve_fewshot_hits(
        req.violation_behavior,
        bank=bank,
        tag_hints=tag_hints or None,
        exclude_case_ids=req.exclude_case_ids or None,
        top_n=req.top_n,
    )
    return FewShotPreviewResponse(
        enabled=True,
        bank=bank.name,
        tag_hints=tag_hints,
        examples=[
            FewShotExampleOut(
                example_id=h.example.example_id,
                case_id=h.example.case_id,
                risk_tags=list(h.example.risk_tags),
                violation_behavior=h.example.violation_behavior,
                score=h.score,
                typicality=h.example.typicality,
                reason=h.reason,
                note=h.example.note,
            )
            for h in hits
        ],
        prompt_block=format_fewshot_block(
            hits,
            max_chars=settings.FEWSHOT_MAX_CHARS,
            max_behavior_chars=settings.FEWSHOT_MAX_BEHAVIOR_CHARS,
        ),
        user_prompt=(
            build_cn_tag_user_prompt(
                req.violation_behavior,
                fewshot_bank=bank,
                exclude_case_ids=req.exclude_case_ids or None,
            )
            if req.include_prompt
            else None
        ),
    )


@router.post("/reload")
async def fewshot_reload():
    """重跑构库脚本后热加载新示例库。"""
    reset_default_bank()
    bank = get_default_bank()
    state.fewshot_bank = bank
    if bank is None:
        raise HTTPException(
            503,
            detail="示例库不可用：请检查 FEWSHOT_ENABLED 与 FEWSHOT_BANK_PATH",
        )
    logger.info("few-shot bank reloaded: %s examples=%d", bank.name, len(bank))
    return {"loaded": True, "stats": bank.stats()}
