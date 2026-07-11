"""高危词规则：风险句定位第一重判断。

场景（scene）可调整规则严格度：短信/直播话术适用更严格口径。
"""

import re
from dataclasses import dataclass

HIGH_RISK_PATTERNS: list[tuple[str, str, str]] = [
    # (正则, 赛题风险 ID, 严重度)
    (r"保证.*收益|稳赚|无风险|零风险|绝对.*安全", "R001", "high"),
    (r"送.*卡|返佣|返现|补贴|赠礼|领取.*礼品|赠送.*(卡|礼品|权益)", "R002", "high"),
    (r"最高.*收益|年化.*\d+(\.\d+)?%|收益.*\d+(\.\d+)?%", "R001", "medium"),
    (r"无需.*关注.*风险|不用担心|忽略.*风险|没有.*风险", "R001", "medium"),
    (r"限时.*抢购|最后.*名额|即将.*停售", "R003", "medium"),
    (r"虚列.*费用|虚假.*报表", "R006", "high"),
    (r"虚挂.*中介|虚构.*中介|套取.*手续费", "R005", "high"),
]

# 严格场景：中危规则升级为高危
STRICT_SCENES = {"营销宣传材料/销售话术审核"}


@dataclass
class RuleHit:
    pattern: str
    risk_type_id: str
    severity: str
    matched_text: str


def match_risk_rules(sentence: str, scene: str | None = None) -> list[RuleHit]:
    hits: list[RuleHit] = []
    strict = scene in STRICT_SCENES if scene else False
    for pattern, risk_id, severity in HIGH_RISK_PATTERNS:
        m = re.search(pattern, sentence)
        if m:
            effective = "high" if (strict and severity == "medium") else severity
            hits.append(RuleHit(
                pattern=pattern, risk_type_id=risk_id,
                severity=effective, matched_text=m.group(0),
            ))
    return hits
