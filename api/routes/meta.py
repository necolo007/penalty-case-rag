"""元数据路由：标签字典 / 同义词词典 / 统计 / 健康检查。"""

from fastapi import APIRouter, Depends

from api.dependencies import get_pool
from engine.classification.competition_label_map import load_cn_tag_catalog

router = APIRouter()


@router.get("/tags")
async def list_tags(pool=Depends(get_pool)):
    """三级风险标签字典（含 R00x，内部召回用）"""
    rows = await pool.fetch(
        """
        SELECT risk_type_id, competition_id, parent_id, level, risk_type_name,
               display_tags, keywords, description
        FROM risk_type_dict WHERE is_active
        ORDER BY risk_type_id
        """
    )
    return [dict(r) for r in rows]


@router.get("/tags/cn")
async def list_cn_tags():
    """配套 27 类中文风险标签（最终分类 / 提交用）"""
    return load_cn_tag_catalog()


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
    """统计信息（案例数 / 标签分布 / 文档状态 / 真实质量指标）。

    无数据时对应字段为 null，前端须显示「— / 暂无真实统计」，禁止写死默认数。
    """
    total_docs = await pool.fetchval("SELECT COUNT(*) FROM documents")
    total_cases = await pool.fetchval("SELECT COUNT(*) FROM penalty_cases")
    insurance_cases = await pool.fetchval(
        "SELECT COUNT(*) FROM penalty_cases WHERE is_insurance_related"
    )
    pending_insurance_cases = await pool.fetchval(
        """
        SELECT COUNT(*) FROM penalty_cases
        WHERE is_insurance_candidate = TRUE AND is_insurance_related = FALSE
        """
    )
    excluded_cases = await pool.fetchval(
        """
        SELECT COUNT(*) FROM penalty_cases
        WHERE is_insurance_related = FALSE AND is_insurance_candidate = FALSE
        """
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
    cn_tag_distribution = await pool.fetch(
        """
        SELECT unnest(risk_tags) AS risk_tag, COUNT(*) AS cnt
        FROM penalty_cases
        WHERE is_insurance_related
        GROUP BY 1 ORDER BY cnt DESC
        LIMIT 40
        """
    )
    doc_status = await pool.fetch(
        "SELECT parse_status, COUNT(*) AS cnt FROM documents GROUP BY parse_status"
    )

    # 待复核：材料审查未完成 + 审查日志尚未人工反馈
    pending_materials = await pool.fetchval(
        """
        SELECT COUNT(*) FROM material_reviews
        WHERE review_status IN ('pending', 'reviewing')
        """
    )
    pending_feedback = await pool.fetchval(
        """
        SELECT COUNT(*) FROM review_logs
        WHERE feedback IS NULL
        """
    )
    pending_review_count = int(pending_materials or 0) + int(pending_feedback or 0)

    # 标签覆盖率：保险相关案例中至少打了一个 risk_tags 的占比
    tagged_cases = await pool.fetchval(
        """
        SELECT COUNT(*) FROM penalty_cases
        WHERE is_insurance_related
          AND risk_tags IS NOT NULL AND cardinality(risk_tags) > 0
        """
    )
    tag_coverage_rate = (
        round(float(tagged_cases) / float(insurance_cases), 4)
        if insurance_cases and insurance_cases > 0
        else None
    )

    # 主体标准化完成率：至少有一条 subject_relations 记录的保险案例占比
    normalized_cases = await pool.fetchval(
        """
        SELECT COUNT(DISTINCT pc.case_id)
        FROM penalty_cases pc
        INNER JOIN subject_relations sr ON sr.case_id = pc.case_id
        WHERE pc.is_insurance_related
        """
    )
    entity_normalize_rate = (
        round(float(normalized_cases) / float(insurance_cases), 4)
        if insurance_cases and insurance_cases > 0
        else None
    )

    # 标签树节点案例数（供风险标签字典气泡）
    tag_tree_counts = await pool.fetch(
        """
        SELECT d.risk_type_id, d.parent_id, d.level, d.risk_type_name,
               COALESCE(c.cnt, 0)::int AS case_count
        FROM risk_type_dict d
        LEFT JOIN (
            SELECT unnest(risk_type_ids) AS risk_type_id, COUNT(*) AS cnt
            FROM penalty_cases WHERE is_insurance_related
            GROUP BY 1
        ) c ON c.risk_type_id = d.risk_type_id
        WHERE d.is_active
        ORDER BY d.level, d.risk_type_id
        """
    )

    return {
        "documents": total_docs,
        "cases": total_cases,
        "insurance_cases": insurance_cases,
        "confirmed_insurance_cases": insurance_cases,
        "pending_insurance_cases": pending_insurance_cases,
        "excluded_cases": excluded_cases,
        "embedded_cases": embedded_cases,
        "tag_distribution": {r["risk_type_id"]: r["cnt"] for r in tag_distribution},
        "cn_tag_distribution": {r["risk_tag"]: r["cnt"] for r in cn_tag_distribution},
        "document_status": {r["parse_status"]: r["cnt"] for r in doc_status},
        "pending_review_count": pending_review_count,
        "tag_coverage_rate": tag_coverage_rate,
        "entity_normalize_rate": entity_normalize_rate,
        "tag_tree": [
            {
                "risk_type_id": r["risk_type_id"],
                "parent_id": r["parent_id"],
                "level": r["level"],
                "risk_type_name": r["risk_type_name"],
                "case_count": r["case_count"],
            }
            for r in tag_tree_counts
        ],
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
