"""任务3：LLM-as-Judge 评测检索结果是否「合理相关」。

读取已有 submission_*.jsonl + 查询文本，对 Top-K 打 0/1（1=相关，0=不相关），
并汇总 Judge 口径的 MRR / Recall@K / NDCG@K / Top-1。

用法：
  python scripts/eval_retrieval_judge.py \\
    --submission data/eval/submission_test_vb_summary_n30.jsonl \\
    --top-k 10 --limit 30

  # 仅从已有 Judge 报告重算指标（不调 LLM）
  python scripts/eval_retrieval_judge.py \\
    --from-report data/eval/judge_test_vb_summary_n30_listwise_top5.json \\
    --metrics-k 3 5 10

  # 对比多份提交
  python scripts/eval_retrieval_judge.py --compare \\
    data/eval/submission_test_vb_summary_n30.jsonl \\
    data/eval/submission_test_vb_summary_n30_listwise.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.config import get_settings
from core.db import close_pool, create_pool
from engine.llm.client import ThinkingMode, create_llm_client
from engine.llm.prompts import RETRIEVAL_JUDGE_PROMPT

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from eval_metrics import DEFAULT_K_VALUES, compute_judge_retrieval_metrics

logger = logging.getLogger(__name__)
_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _qid(item: dict) -> str:
    return item.get("question_id") or item.get("query_id") or ""


def _parse_judge(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK.search(text)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"judgements": [], "parse_error": True, "raw": text[:500]}


def _to_binary_score(raw_score) -> int:
    """1=相关，0=不相关。兼容旧 0/1/2 输出：≥1 视为相关。"""
    try:
        score = int(raw_score)
    except (TypeError, ValueError):
        return 0
    if score >= 2:
        return 1
    if score == 1:
        return 1
    return 0


def _normalize_judgements(data: dict, expected_ids: list[str]) -> list[dict]:
    raw_list = data.get("judgements") or data.get("judgments") or []
    by_id: dict[str, dict] = {}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("case_id") or "").strip()
        if not cid:
            continue
        score = _to_binary_score(item.get("score"))
        by_id[cid] = {
            "case_id": cid,
            "score": score,
            "reason": (item.get("reason") or "")[:200],
        }
    out: list[dict] = []
    for cid in expected_ids:
        if cid in by_id:
            out.append(by_id[cid])
        else:
            out.append({
                "case_id": cid,
                "score": 0,
                "reason": "模型未返回该 case 评分",
            })
    return out


async def _load_case_texts(case_ids: list[str]) -> dict[str, dict]:
    if not case_ids:
        return {}
    pool = await create_pool()
    try:
        rows = await pool.fetch(
            """
            SELECT case_id, party_name, violation_behavior, case_summary, risk_tags
            FROM penalty_cases
            WHERE case_id = ANY($1::text[])
            """,
            case_ids,
        )
        return {r["case_id"]: dict(r) for r in rows}
    finally:
        await close_pool()


def _cases_block(cases: list[dict], case_meta: dict[str, dict]) -> str:
    parts: list[str] = []
    for c in cases:
        cid = c.get("case_id") or ""
        meta = case_meta.get(cid) or {}
        vb = (meta.get("violation_behavior") or "").strip()
        if not vb:
            # submission reason 里常含「对照违法事实：…」
            reason = c.get("reason") or ""
            vb = reason[:220]
        summary = (meta.get("case_summary") or "").strip()[:120]
        tags = meta.get("risk_tags") or []
        tag_s = "、".join(tags[:6]) if tags else ""
        parts.append(
            f"[{c.get('rank', '?')}] case_id={cid}\n"
            f"违法事实：{vb[:280]}\n"
            f"摘要：{summary or '（无）'}\n"
            f"标签：{tag_s or '（无）'}"
        )
    return "\n\n".join(parts)


def _attach_judge_metrics(
    summary: dict,
    per_query: list[dict],
    k_values: list[int],
    *,
    graded_ndcg: bool = False,
) -> dict:
    """合并 Judge 口径的 Recall@K / NDCG@K / MRR / Top-1 等到 summary。"""
    metrics = compute_judge_retrieval_metrics(
        per_query,
        k_values=k_values,
        graded_ndcg=graded_ndcg,
    )
    for key, val in metrics.items():
        if key == "per_query":
            continue
        summary[key] = val
    summary["scoring_mode"] = "judge_graded_ndcg" if graded_ndcg else "judge_binary"
    summary["metrics_note"] = (
        "相关集来自 Judge 对已召回 Top-M 的标注；Recall@K 为 Judge 正例在 Top-K 的覆盖率"
    )
    return summary


def _metrics_from_report(report_path: Path, k_values: list[int], graded: bool) -> dict:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    per_query = data.get("per_query") or []
    if not per_query:
        raise SystemExit(f"报告中无 per_query: {report_path}")
    summary = {
        "evaluated": len(per_query),
        "top_k": data.get("top_k"),
        "submission": data.get("submission"),
        "from_report": str(report_path),
    }
    return _attach_judge_metrics(summary, per_query, k_values, graded_ndcg=graded)


def _agg(per_query: list[dict], top_k: int) -> dict:
    n = len(per_query) or 1
    hit_rel = sum(1 for q in per_query if q["hit_any_relevant"]) / n
    prec_rel = sum(q["precision_relevant"] for q in per_query) / n
    mrr_rel = sum(q["mrr_relevant"] for q in per_query) / n
    mean_rel_rate = sum(q["mean_relevant_rate"] for q in per_query) / n
    return {
        "evaluated": len(per_query),
        "top_k": top_k,
        "scoring": "binary_0_1",
        "mean_relevant_rate": round(mean_rel_rate, 4),
        "hit_any_relevant": round(hit_rel, 4),
        "precision_relevant": round(prec_rel, 4),
        "mrr_relevant": round(mrr_rel, 4),
        # 兼容旧报告字段名（语义已改为 1=相关）
        "mean_relevance": round(mean_rel_rate, 4),
        "hit_any_score>=2": round(hit_rel, 4),
        "precision_score>=2": round(prec_rel, 4),
        "mrr_score>=2": round(mrr_rel, 4),
    }


async def judge_submission(
    *,
    submission_path: Path,
    questions_path: Path,
    gold_path: Path | None,
    top_k: int,
    limit: int | None,
    out_path: Path,
) -> dict:
    settings = get_settings()
    if not (settings.LLM_API_KEY or "").strip():
        raise SystemExit("需要配置 LLM_API_KEY")

    questions = {_qid(x): x for x in _load_jsonl(questions_path)}
    subs = _load_jsonl(submission_path)
    if limit:
        subs = subs[:limit]

    gold_map: dict[str, set[str]] = {}
    if gold_path and gold_path.is_file():
        for item in _load_jsonl(gold_path):
            qid = _qid(item)
            ga = item.get("gold_answer") or item
            ids = {
                c.get("case_id")
                for c in (ga.get("relevant_cases") or [])
                if c.get("case_id")
            }
            # train 格式
            if not ids and item.get("relevant_cases"):
                ids = {
                    c.get("case_id")
                    for c in item["relevant_cases"]
                    if c.get("case_id")
                }
            gold_map[qid] = {x for x in ids if x}

    all_ids: list[str] = []
    prepared: list[tuple[str, str, list[dict]]] = []
    for row in subs:
        qid = _qid(row)
        qtext = (questions.get(qid) or {}).get("query_text") or ""
        if not qid or not qtext:
            continue
        cases = (row.get("retrieved_cases") or [])[:top_k]
        prepared.append((qid, qtext, cases))
        all_ids.extend(c.get("case_id") for c in cases if c.get("case_id"))

    case_meta = await _load_case_texts(sorted(set(all_ids)))
    llm = create_llm_client(settings)

    per_query: list[dict] = []
    detail_path = out_path.with_suffix(".jsonl")
    with detail_path.open("w", encoding="utf-8") as detail_f:
        for i, (qid, qtext, cases) in enumerate(prepared, 1):
            expected = [c.get("case_id") for c in cases if c.get("case_id")]
            prompt = RETRIEVAL_JUDGE_PROMPT.format(
                query_text=qtext,
                cases_block=_cases_block(cases, case_meta),
            )
            try:
                raw = llm.complete(
                    prompt,
                    max_tokens=900,
                    temperature=0.0,
                    json_mode=True,
                    thinking=ThinkingMode.DISABLED,
                )
                parsed = _parse_judge(raw)
            except Exception as e:  # noqa: BLE001
                logger.warning("judge failed %s: %s", qid, e)
                parsed = {"judgements": [], "error": str(e)}

            judgements = _normalize_judgements(parsed, expected)
            scores = [j["score"] for j in judgements]
            rel = [s == 1 for s in scores]
            mean_rel_rate = sum(scores) / len(scores) if scores else 0.0
            hit_any = any(rel)
            prec_rel = (sum(scores) / len(scores)) if scores else 0.0
            mrr_rel = 0.0
            for rank, s in enumerate(scores, 1):
                if s == 1:
                    mrr_rel = 1.0 / rank
                    break

            gset = gold_map.get(qid) or set()
            gold_in_topk = sorted(gset & set(expected))
            gold_best_rank = None
            for rank, cid in enumerate(expected, 1):
                if cid in gset:
                    gold_best_rank = rank
                    break

            rec = {
                "question_id": qid,
                "mean_relevant_rate": round(mean_rel_rate, 4),
                "hit_any_relevant": hit_any,
                "precision_relevant": round(prec_rel, 4),
                "mrr_relevant": round(mrr_rel, 4),
                "gold_case_ids": sorted(gset),
                "gold_in_topk": gold_in_topk,
                "gold_best_rank": gold_best_rank,
                "best_case_id": parsed.get("best_case_id"),
                "query_note": parsed.get("query_note") or "",
                "judgements": judgements,
            }
            per_query.append(rec)
            detail_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 5 == 0 or i == len(prepared):
                print(f"  [{submission_path.name}] {i}/{len(prepared)}", flush=True)

    summary = _agg(per_query, top_k)
    summary = _attach_judge_metrics(
        summary, per_query, k_values=DEFAULT_K_VALUES, graded_ndcg=False,
    )
    # 金标未命中但 Judge 认为合理的比例
    gold_miss_but_ok = [
        q for q in per_query
        if q["gold_case_ids"] and not q["gold_in_topk"] and q["hit_any_relevant"]
    ]
    summary["gold_miss_but_judge_ok"] = round(
        len(gold_miss_but_ok) / (len(per_query) or 1), 4,
    )
    summary["submission"] = str(submission_path)
    summary["per_query"] = per_query

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in summary.items() if k != "per_query"}
    payload["per_query"] = per_query
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics_path = out_path.with_suffix(".metrics.json")
    metrics_path.write_text(
        json.dumps({k: v for k, v in payload.items() if k != "per_query"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"Judge {submission_path.name}: n={summary['evaluated']} "
        f"top1_hit={summary.get('top1_hit')} "
        f"mrr={summary.get('mrr')} "
        f"recall@5={summary.get('recall@5')} "
        f"ndcg@5={summary.get('ndcg@5')} "
        f"hit_any={summary['hit_any_relevant']} "
        f"gold_miss_but_ok={summary['gold_miss_but_judge_ok']}"
    )
    print(f"  report → {out_path}")
    print(f"  metrics → {metrics_path}")
    print(f"  detail → {detail_path}")
    return summary


async def main_async(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    k_values = sorted(set(args.metrics_k or DEFAULT_K_VALUES))

    if args.from_report:
        report = Path(args.from_report)
        if not report.is_absolute():
            report = _ROOT / report
        summary = _metrics_from_report(report, k_values, graded=args.graded_ndcg)
        out = Path(args.output) if args.output else report.with_suffix(".metrics.json")
        if not out.is_absolute():
            out = _ROOT / out
        out.write_text(
            json.dumps({k: v for k, v in summary.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Judge metrics (from report) n={summary.get('evaluated')}")
        for key in ["top1_hit", "mrr"]:
            if key in summary:
                print(f"  {key}: {summary[key]}")
        for k in k_values:
            for prefix in ("recall", "ndcg"):
                mk = f"{prefix}@{k}"
                if mk in summary:
                    print(f"  {mk}: {summary[mk]}")
        print(f"Metrics → {out}")
        return

    questions = Path(args.questions)
    if not questions.is_absolute():
        questions = _ROOT / questions
    gold = Path(args.gold) if args.gold else None
    if gold and not gold.is_absolute():
        gold = _ROOT / gold

    paths: list[Path] = []
    if args.compare:
        paths = [Path(p) for p in args.compare]
    elif args.submission:
        paths = [Path(args.submission)]
    else:
        raise SystemExit("请指定 --submission 或 --compare")

    summaries = []
    for p in paths:
        if not p.is_absolute():
            p = _ROOT / p
        stem = p.stem.replace("submission_", "judge_")
        out = Path(args.output) if args.output and len(paths) == 1 else (
            _ROOT / "data" / "eval" / f"{stem}_top{args.top_k}.json"
        )
        if not out.is_absolute():
            out = _ROOT / out
        s = await judge_submission(
            submission_path=p,
            questions_path=questions,
            gold_path=gold,
            top_k=args.top_k,
            limit=args.limit,
            out_path=out,
        )
        summaries.append({
            "submission": p.name,
            **{k: v for k, v in s.items() if k != "per_query"},
        })

    if len(summaries) > 1:
        cmp_path = _ROOT / "data" / "eval" / f"judge_compare_top{args.top_k}.json"
        cmp_path.write_text(
            json.dumps(summaries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Compare → {cmp_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="LLM-as-Judge 检索合理性评测")
    p.add_argument("--submission", default=None, help="单份 submission jsonl")
    p.add_argument(
        "--compare",
        nargs="+",
        default=None,
        help="多份 submission 对比",
    )
    p.add_argument("--questions", default="data/eval/test_questions.jsonl")
    p.add_argument(
        "--gold",
        default="data/eval/quarantine/test_gold_labels.jsonl",
        help="可选金标，用于对照 gold_miss_but_judge_ok",
    )
    p.add_argument("--top-k", type=int, default=10,
                   help="Judge 评分的召回条数；算 Recall@10 需至少 10")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--output", default=None, help="单提交时的报告路径")
    p.add_argument(
        "--from-report",
        default=None,
        help="从已有 Judge JSON 重算指标（不调 LLM）",
    )
    p.add_argument(
        "--metrics-k",
        nargs="+",
        type=int,
        default=None,
        help="Judge 指标 K 列表，默认 3 5 10",
    )
    p.add_argument(
        "--graded-ndcg",
        action="store_true",
        help="NDCG 使用 Judge 0/1/2 分值（否则二值相关）",
    )
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
