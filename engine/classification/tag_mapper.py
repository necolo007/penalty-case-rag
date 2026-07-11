"""内外双轨标签映射：内部三级标签 ↔ 赛题扁平 R001–R008。"""

COMPETITION_TAGS = {
    "R001": "欺骗投保人/销售误导",
    "R002": "给予保险合同约定以外利益",
    "R003": "宣传材料或产品说明会数据资料不真实",
    "R004": "销售人员执业登记管理不规范",
    "R005": "虚构/虚挂中介业务套取费用",
    "R006": "编制虚假财务资料",
    "R007": "保险代理人侵害消费者权益",          # 命题方样例补充
    "R008": "利用开展保险业务牟取不正当利益",    # 命题方样例补充
}


def map_internal_to_competition(internal_tag_id: str) -> str:
    """内部三级 ID（R002-01-01）→ 赛题扁平 ID（R002）"""
    root = internal_tag_id.split("-")[0]
    return root if root in COMPETITION_TAGS else ""


def to_submission_risk_types(internal_tag_ids: list[str]) -> str:
    """多个赛题标签用中文分号拼接，对齐 submission.jsonl 的 risk_type 字段"""
    competition_ids = {
        cid for cid in (map_internal_to_competition(t) for t in internal_tag_ids) if cid
    }
    names = [COMPETITION_TAGS[cid] for cid in sorted(competition_ids)]
    return "；".join(names)


def competition_name(competition_id: str) -> str:
    return COMPETITION_TAGS.get(competition_id, competition_id)
