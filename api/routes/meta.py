"""元数据路由：标签字典 / 同义词词典 / 统计 / 健康检查。"""

from fastapi import APIRouter, Depends

from api.dependencies import get_pool

router = APIRouter()


@router.get("/tags")
async def list_tags(pool=Depends(get_pool)):
    """三级风险标签字典"""
    rows = await pool.fetch(
        """
        SELECT risk_type_id, competition_id, parent_id, level, risk_type_name,
               display_tags, keywords, description
        FROM risk_type_dict WHERE is_active
        ORDER BY risk_type_id
        """
    )
    return [dict(r) for r in rows]


@router.get("/dictionaries/synonyms")
async def list_synonyms(pool=Depends(get_pool)):
    """同义词词典"""
    rows = await pool.fetch(
        """
        SELECT synonym_id, business_term, standard_term, risk_type_id, weight
        FROM synonym_dictionary ORDER BY synonym_id
        """
    )
    return [dict(r) for r in rows]


@router.get("/stats")
async def get_stats(pool=Depends(get_pool)):
    """统计信息（案例数 / 标签分布 / 文档状态）"""
    total_docs = await pool.fetchval("SELECT COUNT(*) FROM documents")
    total_cases = await pool.fetchval("SELECT COUNT(*) FROM penalty_cases")
    insurance_cases = await pool.fetchval(
        "SELECT COUNT(*) FROM penalty_cases WHERE is_insurance_related"
    )
    embedded_cases = await pool.fetchval("SELECT COUNT(*) FROM case_embeddings")

    tag_distribution = await pool.fetch(
        """
        SELECT unnest(risk_type_ids) AS risk_type_id, COUNT(*) AS cnt
        FROM penalty_cases
        WHERE is_insurance_related
        GROUP BY 1 ORDER BY cnt DESC
        """
    )
    doc_status = await pool.fetch(
        "SELECT parse_status, COUNT(*) AS cnt FROM documents GROUP BY parse_status"
    )
    return {
        "documents": total_docs,
        "cases": total_cases,
        "insurance_cases": insurance_cases,
        "embedded_cases": embedded_cases,
        "tag_distribution": {r["risk_type_id"]: r["cnt"] for r in tag_distribution},
        "document_status": {r["parse_status"]: r["cnt"] for r in doc_status},
    }


@router.get("/health")
async def health(pool=Depends(get_pool)):
    db_ok = False
    try:
        await pool.fetchval("SELECT 1")
        db_ok = True
    except Exception:  # noqa: BLE001
        pass
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
