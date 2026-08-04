"""导出 penalty_content 待人工复核清单（CSV）。

优先覆盖：金标空、预测空、字符重叠 F1<0.5、仍含噪声标记的行。
每行附带原文片段，便于对照 raw_text 修正金标。

用法：
  python scripts/reextract_for_eval.py --gold data/eval/gold_extraction_cases.cleaned.jsonl
  python scripts/export_penalty_content_review.py \\
    --gold data/eval/gold_extraction_cases.cleaned.jsonl \\
    --extracted data/eval/extracted_cases.jsonl \\
    --output data/eval/penalty_content_review.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.clean_gold_extraction import (  # noqa: E402
    _DEFAULT_COMP,
    _is_penalty_content_dump,
    _is_penalty_content_no_action,
    _is_penalty_content_procedural,
    _resolve_raw_dirs,
    _read_raw,
)
from scripts.eval_extraction import (  # noqa: E402
    _char_overlap_f1,
    build_matched_pairs,
    load_jsonl,
    normalize,
)

_ACTION_HINT = re.compile(r"罚款|警告|责令|吊销|没收|决定给予|决定对")


def _issue_type(gold_pc: str, pred_pc: str, f1: float | None) -> str:
    g = (gold_pc or "").strip()
    p = (pred_pc or "").strip()
    if not g and p:
        return "gold_empty_pred_has"
    if g and not p:
        return "pred_empty_gold_has"
    if not g and not p:
        return "both_empty"
    if _is_penalty_content_dump(g):
        return "gold_dump"
    if _is_penalty_content_procedural(g):
        return "gold_procedural"
    if _is_penalty_content_no_action(g):
        return "gold_no_action"
    if f1 is not None and f1 < 0.3:
        return "low_f1_lt_0.3"
    if f1 is not None and f1 < 0.5:
        return "mid_f1_0.3_0.5"
    return "ok"


def _raw_snippet(text: str, max_chars: int = 240) -> str:
    if not text:
        return ""
    # 优先截取含处罚动作的窗口
    m = _ACTION_HINT.search(text)
    if m:
        start = max(0, m.start() - 40)
        end = min(len(text), m.start() + 200)
        return re.sub(r"\s+", " ", text[start:end]).strip()[:max_chars]
    return re.sub(r"\s+", " ", text[:max_chars]).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 penalty_content 人工复核 CSV")
    parser.add_argument("--gold", default="data/eval/gold_extraction_cases.cleaned.jsonl")
    parser.add_argument("--extracted", default="data/eval/extracted_cases.jsonl")
    parser.add_argument("--output", default="data/eval/penalty_content_review.csv")
    parser.add_argument("--all", action="store_true", help="导出全部匹配对（默认只导出需复核的）")
    parser.add_argument("--f1-threshold", type=float, default=0.5, help="低于该 F1 纳入复核")
    args = parser.parse_args()

    gold = load_jsonl(args.gold)
    extracted = load_jsonl(args.extracted)
    pairs = build_matched_pairs(extracted, gold)
    raw_dirs = _resolve_raw_dirs([
        _ROOT / "data" / "raw_text",
        _ROOT.parent / _DEFAULT_COMP / "raw_text",
    ])

    rows_out: list[dict] = []
    for g, e in pairs:
        if not g:
            continue
        gv = (g.get("penalty_content") or "").strip()
        pv = ((e or {}).get("penalty_content") or "").strip()
        f1: float | None = None
        if gv and pv:
            _, _, f1 = _char_overlap_f1(normalize(pv), normalize(gv))
        issue = _issue_type(gv, pv, f1)
        if not args.all:
            if issue == "ok" and (f1 is None or f1 >= args.f1_threshold):
                if gv and pv:
                    continue
        fid = g.get("file_id") or ""
        raw = _read_raw(fid, raw_dirs) if fid else ""
        rows_out.append({
            "case_id": g.get("case_id") or "",
            "file_id": fid,
            "issue": issue,
            "f1": "" if f1 is None else f"{f1:.3f}",
            "gold_penalty_content": gv,
            "pred_penalty_content": pv,
            "party_name": g.get("party_name") or "",
            "penalty_doc_no": g.get("penalty_doc_no") or "",
            "raw_snippet": _raw_snippet(raw),
            "suggested_fix": "",  # 人工填写
        })

    # 未匹配到预测的金标也列出（若 gold 有 penalty 或为空需补）
    matched_ids = {r["case_id"] for r in rows_out}
    # build_matched_pairs 已含 unmatched gold as (g, None)；上面已覆盖

    # 按严重程度排序
    order = {
        "both_empty": 0,
        "gold_empty_pred_has": 1,
        "gold_dump": 2,
        "gold_procedural": 3,
        "gold_no_action": 4,
        "low_f1_lt_0.3": 5,
        "pred_empty_gold_has": 6,
        "mid_f1_0.3_0.5": 7,
        "ok": 8,
    }
    rows_out.sort(key=lambda r: (order.get(r["issue"], 9), r["f1"] or "0", r["case_id"]))

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = _ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case_id", "file_id", "issue", "f1",
                "gold_penalty_content", "pred_penalty_content",
                "party_name", "penalty_doc_no", "raw_snippet", "suggested_fix",
            ],
        )
        writer.writeheader()
        writer.writerows(rows_out)

    from collections import Counter
    counts = Counter(r["issue"] for r in rows_out)
    print(f"Wrote {len(rows_out)} review rows → {out_path}")
    print("issue counts:")
    for k, v in counts.most_common():
        print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()
