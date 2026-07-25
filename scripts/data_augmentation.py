"""从处罚案例反向生成营销口语 query，构建检索训练对。

用法：python scripts/data_augmentation.py --limit 100
"""

import argparse
import asyncio
import json
from pathlib import Path

from core.config import get_settings
from core.db import close_pool, create_pool
from engine.llm.client import ThinkingMode, create_llm_client

REVERSE_GEN_PROMPT = """你是一个保险营销文案写手。以下是一条监管处罚案例的违法行为描述，请模拟违规营销场景，生成 2 条可能触发同类处罚的业务口语话术（如短信、朋友圈文案、直播话术）。

违法行为：{violation_behavior}

要求：
1. 使用口语化、营销化表述，不要出现法言法语
2. 每条一行，不要编号和其他说明

示例：
违法行为：给予投保人保险合同约定以外的其他利益
输出：
购买本产品即可领取价值1000元体检卡
投保就送500元加油卡，数量有限先到先得
"""


async def main():
    parser = argparse.ArgumentParser(description="检索训练样本增强")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", default="data/eval/retrieval_train_queries.jsonl")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.LLM_API_KEY:
        raise SystemExit("LLM_API_KEY required for data augmentation")

    llm = create_llm_client(settings)
    pool = await create_pool()
    rows = await pool.fetch(
        """
        SELECT case_id, violation_behavior, risk_type_ids
        FROM penalty_cases
        WHERE is_insurance_related AND violation_behavior != ''
        ORDER BY overall_confidence DESC
        LIMIT $1
        """,
        args.limit,
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    query_idx = 1
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            try:
                resp = llm.complete(
                    REVERSE_GEN_PROMPT.format(violation_behavior=row["violation_behavior"][:300]),
                    max_tokens=200,
                    temperature=0.7,
                    thinking=ThinkingMode.DISABLED,
                )
            except Exception as e:  # noqa: BLE001
                print(f"  skip {row['case_id']}: {e}")
                continue

            for line in resp.splitlines():
                text = line.strip()
                if len(text) < 8:
                    continue
                f.write(json.dumps({
                    "query_id": f"Q{query_idx:03d}",
                    "scene": "营销宣传材料/销售话术审核",
                    "query_text": text,
                    "expected_risk_type": (row["risk_type_ids"] or [None])[0],
                    "relevant_cases": [{
                        "case_id": row["case_id"],
                        "relevance": "strong",
                        "reason": f"该 query 由案例 {row['case_id']} 的违法行为反向生成。",
                    }],
                }, ensure_ascii=False) + "\n")
                query_idx += 1

    print(f"Generated {query_idx - 1} training queries → {output}")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
