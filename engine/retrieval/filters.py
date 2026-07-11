"""四路召回共享的 SQL 过滤条件构造。"""

from engine.retrieval.base import SearchQuery

# 各召回通道公用的查询字段（含来源文件名）
CASE_SELECT_FIELDS = """
    c.case_id,
    c.party_name,
    c.violation_behavior,
    c.penalty_content,
    c.regulator,
    c.risk_tags,
    c.risk_type_ids,
    c.penalty_doc_no,
    d.file_name AS source_file
"""

CASE_FROM = """
    penalty_cases c
    JOIN documents d ON c.file_id = d.file_id
"""


def build_filters(query: SearchQuery, params: list) -> str:
    """构建 WHERE 追加条件，参数写入 params，返回 SQL 片段（以 AND 开头）。"""
    clauses: list[str] = []

    if query.risk_type:
        params.append(query.risk_type)
        clauses.append(f"${len(params)} = ANY(c.risk_type_ids)")
    if query.regulator:
        params.append(query.regulator)
        clauses.append(f"c.regulator = ${len(params)}")
    if query.institution_type:
        params.append(query.institution_type)
        clauses.append(f"c.institution_type = ${len(params)}")
    if query.date_from:
        params.append(query.date_from)
        clauses.append(f"c.publish_date >= ${len(params)}::date")
    if query.date_to:
        params.append(query.date_to)
        clauses.append(f"c.publish_date <= ${len(params)}::date")

    if not clauses:
        return ""
    return " AND " + " AND ".join(clauses)
