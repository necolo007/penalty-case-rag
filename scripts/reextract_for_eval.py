"""从金标 raw_text 规则重抽，产出 extracted_cases.jsonl（任务1前置）。

用法：python scripts/reextract_for_eval.py [--limit 100]
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
from engine.classification.insurance_filter import InsuranceFilter
from pipeline.extraction.extractor import ExtractorEngine
from pipeline.parser.base import ParseResult

_DEFAULT_COMP = Path(
    "docs/data/05-金融大模型与智能体赛道-基于知识增强检索的保险监管处罚案例知识库构建与合规审查智能匹配"
)


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _resolve_raw_text(file_id: str, dirs: list[Path]) -> str:
    for d in dirs:
        p = d / f"{file_id}.txt"
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="金标 raw_text 规则重抽")
    parser.add_argument("--gold", default="data/eval/gold_extraction_cases.jsonl")
    parser.add_argument("--output", default="data/eval/extracted_cases.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    gold_path = Path(args.gold)
    if not gold_path.is_absolute():
        gold_path = _ROOT / gold_path
    rows = _load_jsonl(gold_path)
    if args.limit:
        rows = rows[: args.limit]

    raw_dirs = [
        _ROOT / settings.DATA_DIR / "raw_text",
        _ROOT.parent / _DEFAULT_COMP / "raw_text",
    ]
    engine = ExtractorEngine(llm_client=None, use_llm_refine=False)
    filt = InsuranceFilter(dict_dir=_ROOT / settings.DATA_DIR / "dictionaries")

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = _ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = missing = 0
    with out_path.open("w", encoding="utf-8") as f:
        for item in rows:
            file_id = item.get("file_id") or ""
            case_id = item.get("case_id") or ""
            text = _resolve_raw_text(file_id, raw_dirs)
            if not text.strip():
                missing += 1
                continue
            parse = ParseResult(success=True, markdown=text, confidence=1.0)
            cases = engine.extract(parse, file_id=file_id, source_file=f"{file_id}.txt")
            if not cases:
                missing += 1
                continue
            case = cases[0]
            score = filt.score(case.party_name, case.violation_behavior, case.legal_basis)
            cand, _ = filt.is_candidate(case.party_name, case.violation_behavior, case.legal_basis)
            inst = case.institution_type
            inst_val = inst.value if hasattr(inst, "value") else str(inst)
            row = {
                "case_id": case_id,
                "file_id": file_id,
                "party_name": case.party_name,
                "penalty_doc_no": case.penalty_doc_no,
                "violation_behavior": case.violation_behavior,
                "penalty_content": case.penalty_content,
                "regulator": case.regulator,
                "institution_type": inst_val,
                "is_insurance_related": bool(score.is_insurance or cand),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1

    print(f"Wrote {written} extracted cases → {out_path} (missing_raw={missing})")


if __name__ == "__main__":
    main()
