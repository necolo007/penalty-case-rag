"""导出 few-shot 库 / 固定三样本 / 动态检索样例，供人工审查。

用法：
  python scripts/dump_fewshot_human_review.py
  python scripts/dump_fewshot_human_review.py --gold-limit 10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import get_settings
from engine.classification.competition_label_map import predict_cn_tags_by_keywords
from engine.classification.fewshot import (
    FewShotBank,
    format_fewshot_block,
    retrieve_fewshot_hits,
    retrieve_fixed_fewshot_hits,
)


def _join_tags(tags: list[str]) -> str:
    return "、".join(tags)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 few-shot 人工审查材料")
    parser.add_argument("--bank", default=None, help="示例库 jsonl，默认读配置")
    parser.add_argument("--gold", default="data/eval/gold_task2_822_cleaned.jsonl")
    parser.add_argument("--gold-limit", type=int, default=8)
    parser.add_argument(
        "--out-md",
        default="data/fewshot/HUMAN_REVIEW_fewshot_fixed_dynamic.md",
    )
    parser.add_argument(
        "--out-json",
        default="data/fewshot/HUMAN_REVIEW_fewshot_fixed_dynamic.json",
    )
    args = parser.parse_args()

    settings = get_settings()
    bank_path = args.bank or settings.FEWSHOT_BANK_PATH
    bank = FewShotBank.from_jsonl(bank_path)
    fixed_ids = settings.FEWSHOT_FIXED_IDS
    fixed = retrieve_fixed_fewshot_hits(bank=bank, fixed_ids=fixed_ids)

    cases: list[dict[str, str]] = [
        {
            "case_id": "DEMO-太保洗车券",
            "violation_behavior": (
                "2018年1月至10月，太保财险重庆分公司在微信公众号、车点点等网络平台，"
                "向投保车险的客户赠送洗车券，共计结算86117张，涉及金额2448866元。"
            ),
        }
    ]
    gold_path = _ROOT / args.gold
    if gold_path.is_file():
        with gold_path.open(encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= args.gold_limit:
                    break
                row = json.loads(line)
                vb = (row.get("violation_behavior") or "").strip()
                if not vb:
                    continue
                cases.append(
                    {
                        "case_id": str(row.get("case_id") or f"ROW-{i}"),
                        "violation_behavior": vb,
                    }
                )

    dyn: list[dict] = []
    for c in cases:
        vb = c["violation_behavior"]
        hints = predict_cn_tags_by_keywords(vb, max_tags=5)
        hits = retrieve_fewshot_hits(vb, bank=bank, tag_hints=hints)
        dyn.append(
            {
                "case_id": c["case_id"],
                "violation_behavior": vb[:400],
                "tag_hints": hints,
                "injected": len(hits),
                "hits": [
                    {
                        "rank": i + 1,
                        "example_id": h.example.example_id,
                        "score": round(float(h.score), 4),
                        "reason": getattr(h, "reason", ""),
                        "risk_tags": h.example.risk_tags,
                        "violation_behavior": h.example.violation_behavior,
                    }
                    for i, h in enumerate(hits)
                ],
            }
        )

    lines: list[str] = [
        "# 任务二 Few-shot 抽取记录（人工审查）",
        "",
        "生成用途：核对示例库内容、固定三样本、动态检索注入是否合理。",
        "",
        "## 0. 配置快照",
        "",
        f"- 示例库：`{bank_path}`",
        f"- 默认模式：`{settings.FEWSHOT_MODE}`（线上默认 dynamic；fixed 用下方三样本）",
        f"- 固定三样本 ID：`{fixed_ids}`",
        (
            f"- TOP_N={settings.FEWSHOT_TOP_N}，RETRIEVER={settings.FEWSHOT_RETRIEVER}，"
            f"REQUIRE_COVERED_HINT={settings.FEWSHOT_REQUIRE_COVERED_HINT}"
        ),
        f"- 库规模：{len(bank)} 条，标签覆盖 {len(bank.covered_tags)}/27",
        "",
        "完整库清单（导入时生成）：`data/fewshot/risk_tag_fewshot_bank_multilabel.review.md`",
        "机器可读库：`data/fewshot/risk_tag_fewshot_bank_multilabel.jsonl`",
        "单次 Prompt 样例（动态）：`data/fewshot/example.txt`",
        "",
        "## 1. Few-shot 示例库（抽取全量）",
        "",
        "| ID | 标签 | 违法行为（全文） |",
        "|---|---|---|",
    ]
    for ex in bank.examples:
        lines.append(
            f"| `{ex.example_id}` | {_join_tags(ex.risk_tags)} | {_md_escape(ex.violation_behavior)} |"
        )

    lines.extend(
        [
            "",
            "## 2. 固定三样本（FEWSHOT_MODE=fixed）",
            "",
            "每案注入同一批示例，不随待判文本变化。",
            "",
        ]
    )
    for i, h in enumerate(fixed, 1):
        e = h.example
        lines.extend(
            [
                f"### 固定例{i} `{e.example_id}`",
                "",
                f"- **标签**：{_join_tags(e.risk_tags)}",
                f"- **来源**：{e.source or '-'}",
                f"- **违法行为**：{e.violation_behavior}",
                "",
            ]
        )
    lines.extend(
        [
            "### 固定模式注入块预览",
            "",
            "```",
            format_fewshot_block(fixed),
            "```",
            "",
            "## 3. 动态样本（FEWSHOT_MODE=dynamic，按案检索 TOP_N）",
            "",
            "流程：关键词初判 tag_hints → 门控（初判须命中库内标签）→ lexical/MMR 检索 TOP_N。",
            "",
        ]
    )
    for sample in dyn:
        hints = sample["tag_hints"]
        hint_txt = "（无）" if not hints else _join_tags(hints)
        lines.extend(
            [
                f"### 待判 `{sample['case_id']}`",
                "",
                f"- **违法行为**：{sample['violation_behavior']}",
                f"- **关键词初判**：{hint_txt}",
                f"- **注入条数**：{sample['injected']}",
            ]
        )
        if not sample["hits"]:
            lines.append("- **结果**：未注入（无初判线索 / 门控未通过 / 检索无命中）")
        else:
            for h in sample["hits"]:
                lines.append(
                    f"- **例{h['rank']}** `{h['example_id']}` score={h['score']} "
                    f"[{_join_tags(h['risk_tags'])}] {h['violation_behavior']}"
                )
        lines.append("")

    out_md = _ROOT / args.out_md
    out_json = _ROOT / args.out_json
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines), encoding="utf-8")
    payload = {
        "config": {
            "bank": bank_path,
            "mode_default": settings.FEWSHOT_MODE,
            "fixed_ids": fixed_ids,
            "top_n": settings.FEWSHOT_TOP_N,
            "retriever": settings.FEWSHOT_RETRIEVER,
            "require_covered_hint": settings.FEWSHOT_REQUIRE_COVERED_HINT,
        },
        "bank_count": len(bank),
        "fixed": [
            {
                "example_id": h.example.example_id,
                "risk_tags": h.example.risk_tags,
                "violation_behavior": h.example.violation_behavior,
                "source": h.example.source,
            }
            for h in fixed
        ],
        "dynamic_samples": dyn,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    hit_n = sum(1 for s in dyn if s["injected"] > 0)
    print(f"wrote {out_md}")
    print(f"wrote {out_json}")
    print(f"bank={len(bank)} fixed={len(fixed)} dynamic_cases={len(dyn)} with_hits={hit_n}")


if __name__ == "__main__":
    main()
