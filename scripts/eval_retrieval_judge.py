"""任务3：LLM-as-Judge 评测检索结果是否「合理相关」。

读取已有 submission_*.jsonl + 查询文本，可选补全库内违法事实，对 Top-K 打 0/1/2。
用于辅助诊断（金标噪声时）；不替代 MRR/Recall@K。

用法：
  python scripts/eval_retrieval_judge.py \\
    --submission data/eval/submission_test_vb_summary_n30.jsonl \\
    --top-k 5 --limit 30

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


def _normalize_judgements(data: dict, expected_ids: list[str]) -> list[dict]:
    raw_list = data.get("judgements") or data.get("judgments") or []
    by_id: dict[str, dict] = {}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("case_id") or "").strip()
        if not cid:
            continue
        try:
            score = int(item.get("score"))
        except (TypeError, ValueError):
            score = 0
        score = max(0, min(2, score))
        by_id[cid] = {
            "case_id": cid,
            "score": score,
            "same_risk_type": bool(item.get("same_risk_type")),
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
                "same_risk_type": False,
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


def _agg(per_query: list[dict], top_k: int) -> dict:
    n = len(per_query) or 1
    mean_at_k = sum(q["mean_score"] for q in per_query) / n
    any2 = sum(1 for q in per_query if q["any_score_ge_2"]) / n
    any1 = sum(1 for q in per_query if q["any_score_ge_1"]) / n
    precision2 = sum(q["precision_ge_2"] for q in per_query) / n
    mrr_ge2 = sum(q["mrr_ge_2"] for q in per_query) / n
    return {
        "evaluated": len(per_query),
        "top_k": top_k,
        "mean_relevance": round(mean_at_k, 4),
        "hit_any_score>=2": round(any2, 4),
        "hit_any_score>=1": round(any1, 4),
        "precision_score>=2": round(precision2, 4),
        "mrr_score>=2": round(mrr_ge2, 4),
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
            mean_score = sum(scores) / len(scores) if scores else 0.0
            any2 = any(s >= 2 for s in scores)
            any1 = any(s >= 1 for s in scores)
            prec2 = (sum(1 for s in scores if s >= 2) / len(scores)) if scores else 0.0
            mrr2 = 0.0
            for rank, s in enumerate(scores, 1):
                if s >= 2:
                    mrr2 = 1.0 / rank
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
                "mean_score": round(mean_score, 4),
                "any_score_ge_2": any2,
                "any_score_ge_1": any1,
                "precision_ge_2": round(prec2, 4),
                "mrr_ge_2": round(mrr2, 4),
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
    # 金标未命中但 Judge 认为合理的比例
    gold_miss_but_ok = [
        q for q in per_query
        if q["gold_case_ids"] and not q["gold_in_topk"] and q["any_score_ge_2"]
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
    print(
        f"Judge {submission_path.name}: n={summary['evaluated']} "
        f"mean_rel={summary['mean_relevance']} "
        f"hit@2={summary['hit_any_score>=2']} "
        f"prec@2={summary['precision_score>=2']} "
        f"mrr@2={summary['mrr_score>=2']} "
        f"gold_miss_but_ok={summary['gold_miss_but_judge_ok']}"
    )
    print(f"  report → {out_path}")
    print(f"  detail → {detail_path}")
    return summary


async def main_async(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
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
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--output", default=None, help="单提交时的报告路径")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
