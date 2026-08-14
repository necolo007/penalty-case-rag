"""离线将 LLM 预测与正则预测按短字段策略合并，便于复评。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.extraction.extractor import ExtractorEngine
from pipeline.extraction.schema import ExtractedCase, FieldConfidence, InstitutionType


def _load(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _to_case(row: dict, *, default_method: str) -> ExtractedCase:
    inst_raw = row.get("institution_type") or "非保险"
    try:
        inst = InstitutionType(inst_raw)
    except ValueError:
        inst = InstitutionType.NON_INSURANCE
    case = ExtractedCase(
        file_id=row["file_id"],
        source_file=f"{row['file_id']}.txt",
        party_name=row.get("party_name") or "",
        penalty_doc_no=row.get("penalty_doc_no") or "",
        violation_behavior=row.get("violation_behavior") or "",
        penalty_content=row.get("penalty_content") or "",
        regulator=row.get("regulator") or "",
        institution_type=inst,
        extraction_method=row.get("extraction_method") or default_method,
        case_summary=row.get("case_summary") or "",
    )
    for field in (
        "party_name", "penalty_doc_no", "violation_behavior",
        "penalty_content", "regulator",
    ):
        case.field_confidences[field] = (
            FieldConfidence.HIGH.value if getattr(case, field) else FieldConfidence.LOW.value
        )
    return case


def main() -> None:
    llm_path = _ROOT / "data/eval/archive/extraction/extracted_cases_llm_n100.jsonl"
    reg_path = _ROOT / "data/eval/archive/extraction/extracted_cases_regex_n100.jsonl"
    out_path = _ROOT / "data/eval/extracted_cases_hybrid_n100.jsonl"

    llm_rows = _load(llm_path)
    reg_by = {
        (r["file_id"], r.get("pred_idx", 0)): r
        for r in _load(reg_path)
    }
    engine = ExtractorEngine(
        llm_client=None, use_llm_refine=False, extraction_mode="regex_first",
    )

    out: list[dict] = []
    changed_n = 0
    for row in llm_rows:
        key = (row["file_id"], row.get("pred_idx", 0))
        llm_case = _to_case(row, default_method="llm")
        rx_row = reg_by.get(key)
        if rx_row:
            rx_case = _to_case(rx_row, default_method="regex")
            if engine._merge_regex_short_fields(llm_case, rx_case):
                changed_n += 1
        inst = llm_case.institution_type
        out.append({
            "file_id": llm_case.file_id,
            "pred_idx": row.get("pred_idx", 0),
            "party_name": llm_case.party_name,
            "penalty_doc_no": llm_case.penalty_doc_no,
            "violation_behavior": llm_case.violation_behavior,
            "penalty_content": llm_case.penalty_content,
            "regulator": llm_case.regulator,
            "institution_type": inst.value if hasattr(inst, "value") else str(inst),
            "overall_confidence": row.get("overall_confidence", 0),
            "is_insurance_related": row.get("is_insurance_related", True),
            "extraction_method": llm_case.extraction_method,
        })

    out_path.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(out)} rows, short-field merges={changed_n} -> {out_path}")


if __name__ == "__main__":
    main()
