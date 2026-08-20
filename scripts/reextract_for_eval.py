"""从金标 raw_text 重抽，产出 extracted_cases.jsonl（任务1前置）。

评测口径修正（六次优化）：不再对每条金标行只选「一条最优」候选并强占金标
case_id——这会在一份文书含多个当事人/多次处罚（一案两罚）时，把两条金标
都拿去和同一条预测比较，无法真实反映多案例拆分质量。

新做法：按 file_id 去重后，对每个原始文档只跑一次 extract()，把该文档
产出的**全部**候选案例原样落盘（不裁剪、不绑定金标 case_id），由
eval_extraction.py 按 file_id 做二分图匹配后再计算 P/R/F1。

用法：
  # 正则基线（默认，无 LLM）
  python scripts/reextract_for_eval.py --mode regex_first \\
    --gold data/eval/gold_extraction_cases.cleaned.jsonl

  # LLM 主抽（需配置 LLM_API_KEY）
  python scripts/reextract_for_eval.py --mode llm_first --with-llm \\
    --gold data/eval/gold_extraction_cases.cleaned.jsonl \\
    --output data/eval/extracted_cases_llm.jsonl --limit 100
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
    parser = argparse.ArgumentParser(description="金标 raw_text 重抽（按 file_id 输出全部候选案例）")
    parser.add_argument("--gold", default="data/eval/gold_extraction_521_cleaned.jsonl")
    parser.add_argument("--output", default="data/eval/extracted_cases_hybrid_521.jsonl")
    parser.add_argument("--limit", type=int, default=None, help="限制 file_id 数量（非金标行数）")
    parser.add_argument(
        "--mode",
        choices=("llm_first", "regex_first"),
        default="llm_first",
        help="抽取模式；默认 llm_first 与生产 EXTRACTION_MODE 对齐（需 --with-llm）",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="启用 LLM 客户端（llm_first 必需；也可用于 regex_first 低置信度纠错）",
    )
    parser.add_argument(
        "--llm-refine",
        action="store_true",
        help="regex_first 时启用低置信度 LLM 纠错（需 --with-llm）",
    )
    args = parser.parse_args()

    settings = get_settings()
    gold_path = Path(args.gold)
    if not gold_path.is_absolute():
        gold_path = _ROOT / gold_path
    gold_rows = _load_jsonl(gold_path)

    # 一份文书可能对应多条金标（一案两罚），按 file_id 去重后只抽取一次。
    file_ids: list[str] = []
    seen_fid: set[str] = set()
    for item in gold_rows:
        fid = item.get("file_id") or ""
        if fid and fid not in seen_fid:
            seen_fid.add(fid)
            file_ids.append(fid)
    if args.limit:
        file_ids = file_ids[: args.limit]

    raw_dirs = [
        _ROOT / settings.DATA_DIR / "raw_text",
        _ROOT.parent / _DEFAULT_COMP / "raw_text",
    ]

    llm = None
    if args.mode == "llm_first" and not args.with_llm:
        if (settings.LLM_API_KEY or "").strip():
            args.with_llm = True
            print("info: llm_first 自动启用 LLM（已配置 LLM_API_KEY）", flush=True)
        else:
            print("warn: 无 LLM_API_KEY，llm_first 回退为 regex_first", flush=True)
            args.mode = "regex_first"

    if args.with_llm:
        if not (settings.LLM_API_KEY or "").strip():
            raise SystemExit("--with-llm 需要配置 LLM_API_KEY")
        from engine.llm.client import create_llm_client

        llm = create_llm_client(settings)

    if args.mode == "llm_first" and llm is None:
        raise SystemExit("llm_first 需要同时传入 --with-llm 或配置 LLM_API_KEY")

    engine = ExtractorEngine(
        llm_client=llm,
        use_llm_refine=bool(args.llm_refine and llm is not None),
        extraction_mode=args.mode,
    )
    filt = InsuranceFilter(dict_dir=_ROOT / settings.DATA_DIR / "dictionaries")

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = _ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = missing = llm_n = regex_n = 0
    total = len(file_ids)
    with out_path.open("w", encoding="utf-8") as f:
        for i, file_id in enumerate(file_ids, 1):
            text = _resolve_raw_text(file_id, raw_dirs)
            if not text.strip():
                missing += 1
                continue
            parse = ParseResult(success=True, markdown=text, confidence=1.0)
            cases = engine.extract(parse, file_id=file_id, source_file=f"{file_id}.txt")
            if not cases:
                missing += 1
                continue
            for idx, case in enumerate(cases):
                score = filt.score(case.party_name, case.violation_behavior, case.legal_basis)
                cand, _ = filt.is_candidate(case.party_name, case.violation_behavior, case.legal_basis)
                inst = case.institution_type
                inst_val = inst.value if hasattr(inst, "value") else str(inst)
                method = case.extraction_method
                if method == "llm":
                    llm_n += 1
                elif method == "regex":
                    regex_n += 1
                row = {
                    "file_id": file_id,
                    "pred_idx": idx,
                    "party_name": case.party_name,
                    "penalty_doc_no": case.penalty_doc_no,
                    "violation_behavior": case.violation_behavior,
                    "penalty_content": case.penalty_content,
                    "regulator": case.regulator,
                    "institution_type": inst_val,
                    "overall_confidence": case.overall_confidence,
                    "is_insurance_related": bool(score.is_insurance or cand),
                    "extraction_method": method,
                    "case_summary": case.case_summary or "",
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
            if i % 10 == 0 or i == total:
                print(f"  progress {i}/{total} written={written} missing={missing}", flush=True)

    print(
        f"Wrote {written} extracted cases from {total} files → {out_path} "
        f"(missing_raw={missing}, method_llm={llm_n}, method_regex={regex_n}, mode={args.mode})"
    )


if __name__ == "__main__":
    main()
