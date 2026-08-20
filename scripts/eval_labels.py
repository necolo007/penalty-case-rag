"""任务2 完整评测：风险标签 + 案例摘要 + 关键词。

对齐赛题字段「风险标签、案例摘要、关键词」与指标
「标签准确率、宏平均 F1、人工抽查」。

用法：
  # 仅标签
  python scripts/eval_labels.py --gold data/eval/gold_task2_820_cleaned.jsonl

  # 标签 + 摘要 BERTScore + 关键词（需抽取结果含 case_summary）
  python scripts/eval_labels.py \\
    --gold data/eval/gold_task2_820_cleaned.jsonl \\
    --extracted data/eval/extracted_cases_hybrid_521.jsonl \\
    --output data/eval/label_eval_task2_820_cleaned.json

  # LLM 打标 + 导出逐案预测
  python scripts/eval_labels.py \\
    --gold data/eval/gold_task2_820_cleaned.jsonl \\
    --with-llm \\
    --predictions-out data/eval/predicted_risk_tags_820_llm.jsonl \\
    --output data/eval/label_eval_task2_820_llm.json
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.db import close_pool, create_pool
from engine.classification.competition_label_map import (
    CANONICAL_CN_TAGS,
    _merged_keyword_map,
    cn_tags_to_competition_ids,
    normalize_cn_tags,
    predict_cn_tags_by_keywords,
    refine_cn_tags,
)
from engine.classification.risk_tagger import RiskTagger, predict_cn_tags_with_llm

DEFAULT_BERT_MODEL = "bert-base-chinese"


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _postprocess_cn_tags(tags: list[str], violation_behavior: str) -> list[str]:
    """轻量对齐字典口径：具体形式补上位；电销场景去掉虚假宣传。"""
    return refine_cn_tags(tags, violation_behavior)


def _llm_predict_cn_tags(llm: Any, violation_behavior: str) -> list[str]:
    """用中文 27 类提示词直接预测 risk_tags（与入库 RiskTagger 共用）。"""
    return predict_cn_tags_with_llm(llm, violation_behavior)


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f1


def _norm_party(s: str) -> str:
    return (s or "").replace(" ", "").strip()


def _pair_party_score(pred: dict, gold: dict) -> float:
    pn_p, pn_g = _norm_party(pred.get("party_name") or ""), _norm_party(gold.get("party_name") or "")
    if not pn_p or not pn_g:
        return 0.0
    if pn_p == pn_g:
        return 3.0
    if pn_p in pn_g or pn_g in pn_p:
        return 1.5
    return 0.0


def _match_by_file(
    golds: list[dict], preds: list[dict]
) -> list[tuple[dict | None, dict | None]]:
    """按 file_id 分组后做当事人相似匹配（与任务一思路一致，简化版）。"""
    by_g: dict[str, list[dict]] = defaultdict(list)
    by_p: dict[str, list[dict]] = defaultdict(list)
    for g in golds:
        by_g[g.get("file_id") or ""].append(g)
    for p in preds:
        by_p[p.get("file_id") or ""].append(p)

    pairs: list[tuple[dict | None, dict | None]] = []
    fids = set(by_g) | set(by_p)
    for fid in fids:
        if not fid:
            continue
        gs, ps = by_g.get(fid, []), by_p.get(fid, [])
        if not gs:
            pairs.extend((None, p) for p in ps)
            continue
        if not ps:
            pairs.extend((g, None) for g in gs)
            continue
        n, m = len(gs), len(ps)
        scores = [[_pair_party_score(ps[j], gs[i]) for j in range(m)] for i in range(n)]
        best_total = -1.0
        best_assign: list[tuple[int, int]] = []
        k = min(n, m)
        for combo in itertools.permutations(range(m), k):
            if n <= m:
                assign = list(zip(range(n), combo))
            else:
                assign = list(zip(combo, range(m)))
            total = sum(scores[i][j] for i, j in assign)
            if total > best_total:
                best_total = total
                best_assign = assign
        matched_g = {i for i, _ in best_assign}
        matched_p = {j for _, j in best_assign}
        for i, j in best_assign:
            pairs.append((gs[i], ps[j]))
        for i, g in enumerate(gs):
            if i not in matched_g:
                pairs.append((g, None))
        for j, p in enumerate(ps):
            if j not in matched_p:
                pairs.append((None, p))
    return pairs


def _keywords_in_text(text: str, tags: list[str], kw_map: dict[str, list[str]]) -> set[str]:
    """金标/预测标签对应词典中、且实际出现在文本里的关键词。"""
    hits: set[str] = set()
    for tag in tags:
        for kw in kw_map.get(tag) or []:
            if kw and kw in text:
                hits.add(kw)
    return hits


def _char_overlap_f1(pred: str, truth: str) -> tuple[float, float, float]:
    if pred == truth:
        return 1.0, 1.0, 1.0
    if not pred or not truth:
        return 0.0, 0.0, 0.0
    pc: dict[str, int] = {}
    for ch in pred:
        pc[ch] = pc.get(ch, 0) + 1
    tc: dict[str, int] = {}
    for ch in truth:
        tc[ch] = tc.get(ch, 0) + 1
    overlap = sum(min(c, tc.get(ch, 0)) for ch, c in pc.items())
    precision = overlap / len(pred) if pred else 0.0
    recall = overlap / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _bert_score_batch(
    candidates: list[str],
    references: list[str],
    *,
    model_type: str,
    device: str | None,
    batch_size: int,
) -> list[tuple[float, float, float]]:
    if not candidates:
        return []
    try:
        from bert_score import score as bert_score_fn
    except ImportError as e:  # noqa: BLE001
        raise SystemExit(
            "案例摘要 BERTScore 需要：pip install -e \".[eval]\" 或 pip install bert-score。"
            "下载超时可设 HF_ENDPOINT=https://hf-mirror.com"
        ) from e

    kwargs: dict[str, Any] = {
        "model_type": model_type,
        "lang": "zh",
        "verbose": False,
        "batch_size": batch_size,
        "rescale_with_baseline": False,
    }
    if device:
        kwargs["device"] = device
    P, R, F = bert_score_fn(candidates, references, **kwargs)
    return [
        (float(P[i].item()), float(R[i].item()), float(F[i].item()))
        for i in range(len(candidates))
    ]


def _score_summaries(
    pairs: list[tuple[dict | None, dict | None]],
    *,
    use_bert: bool,
    bert_model: str,
    bert_device: str | None,
    bert_batch_size: int,
) -> dict[str, Any]:
    char_p = char_r = char_f = 0.0
    n = 0
    both_pred: list[str] = []
    both_ref: list[str] = []
    has_both: list[bool] = []
    empty_pred = empty_gold = 0

    unmatched_gold = 0
    for g, e in pairs:
        if g is None:
            continue
        gold_s = (g.get("case_summary") or "").strip()
        if e is None:
            unmatched_gold += 1
            continue
        pred_s = (e.get("case_summary") or "").strip()
        if not gold_s:
            empty_gold += 1
            continue
        if not pred_s:
            empty_pred += 1
            # 有配对但摘要为空：计 0 分
            n += 1
            has_both.append(False)
            continue
        n += 1
        p, r, f = _char_overlap_f1(pred_s, gold_s)
        char_p += p
        char_r += r
        char_f += f
        if use_bert:
            both_pred.append(pred_s)
            both_ref.append(gold_s)
            has_both.append(True)
        else:
            has_both.append(False)

    out: dict[str, Any] = {
        "n_scored": n,
        "empty_pred": empty_pred,
        "skipped_empty_gold": empty_gold,
        "unmatched_gold": unmatched_gold,
        "note": "仅对 file_id/当事人匹配成功的金标–预测对计摘要分；未匹配金标不计入分母",
        "char_overlap_precision": round(char_p / n, 4) if n else 0.0,
        "char_overlap_recall": round(char_r / n, 4) if n else 0.0,
        "char_overlap_f1": round(char_f / n, 4) if n else 0.0,
    }
    if not use_bert:
        out.update({
            "precision": out["char_overlap_precision"],
            "recall": out["char_overlap_recall"],
            "f1": out["char_overlap_f1"],
            "scoring": "char_overlap",
        })
        return out

    scored = _bert_score_batch(
        both_pred, both_ref, model_type=bert_model, device=bert_device, batch_size=bert_batch_size
    )
    bp = br = bf = 0.0
    bi = 0
    for ok in has_both:
        if ok:
            p, r, f = scored[bi]
            bi += 1
        else:
            p = r = f = 0.0
        bp += p
        br += r
        bf += f
    out.update({
        "precision": round(bp / n, 4) if n else 0.0,
        "recall": round(br / n, 4) if n else 0.0,
        "f1": round(bf / n, 4) if n else 0.0,
        "scoring": "bertscore",
        "bert_model": bert_model,
    })
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description="任务2：标签 + 案例摘要 + 关键词评测")
    parser.add_argument("--gold", default="data/eval/gold_extraction_cases.jsonl")
    parser.add_argument(
        "--extracted",
        default=None,
        help="任务一抽取结果 jsonl（含 case_summary）；提供后评摘要相似分",
    )
    parser.add_argument("--output", default="data/eval/label_eval_report.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-bert-score", action="store_true", help="摘要改用字符重叠")
    parser.add_argument("--bert-model", default=DEFAULT_BERT_MODEL)
    parser.add_argument("--bert-device", default=None)
    parser.add_argument("--bert-batch-size", type=int, default=32)
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="用中文风险标签 LLM 提示词预测 risk_tags（默认仅规则/词典）",
    )
    parser.add_argument(
        "--predictions-out",
        default=None,
        help="逐案预测结果 jsonl 路径（含 pred/gold risk_tags）",
    )
    args = parser.parse_args()

    gold_path = Path(args.gold)
    if not gold_path.is_absolute():
        gold_path = _ROOT / gold_path
    rows = _load_jsonl(gold_path)
    if args.limit:
        rows = rows[: args.limit]

    llm = None
    if args.with_llm:
        from core.config import get_settings
        from engine.llm.client import create_llm_client

        settings = get_settings()
        if not (settings.LLM_API_KEY or "").strip():
            raise SystemExit("--with-llm 需要配置 LLM_API_KEY")
        llm = create_llm_client(settings)

    pool = None
    tagger = None
    try:
        pool = await create_pool()
        tagger = RiskTagger(pool, llm_client=llm)
    except Exception as exc:  # noqa: BLE001
        if llm is None:
            raise
        print(f"warn: database unavailable ({exc}); --with-llm continues without rule fallback")
    kw_map = _merged_keyword_map()

    pred_out_path: Path | None = None
    pred_fh = None
    if args.predictions_out:
        pred_out_path = Path(args.predictions_out)
        if not pred_out_path.is_absolute():
            pred_out_path = _ROOT / pred_out_path
        pred_out_path.parent.mkdir(parents=True, exist_ok=True)
        pred_fh = pred_out_path.open("w", encoding="utf-8")

    exact = partial = 0
    jaccards: list[float] = []
    tag_tp: dict[str, int] = defaultdict(int)
    tag_fp: dict[str, int] = defaultdict(int)
    tag_fn: dict[str, int] = defaultdict(int)
    cid_tp = cid_fp = cid_fn = 0

    kw_tp = kw_fp = kw_fn = 0
    kw_cases_with_gold = 0
    llm_fail = 0

    total = len(rows)
    try:
        for i, item in enumerate(rows, 1):
            text = item.get("violation_behavior") or ""
            gold_tags = normalize_cn_tags(item.get("risk_tags") or [])
            gold_set = set(gold_tags)
            method = "rule_cn_dict"

            if llm is not None:
                try:
                    pred_tags = _llm_predict_cn_tags(llm, text)
                    method = "llm_cn"
                except Exception:  # noqa: BLE001
                    llm_fail += 1
                    if tagger is not None:
                        tags = await tagger.classify(text, prefer_llm=False)
                        pred_tags = refine_cn_tags(
                            list(tags.get("display_tags") or []), text
                        )
                        method = "rule_fallback"
                    else:
                        pred_tags = refine_cn_tags(
                            predict_cn_tags_by_keywords(text, max_tags=8), text
                        )
                        method = "keyword_fallback"
                pred_cids = set(cn_tags_to_competition_ids(pred_tags))
            else:
                if tagger is None:
                    raise SystemExit("规则打标需要数据库；请先启动 Postgres 或改用 --with-llm")
                tags = await tagger.classify(text)
                pred_tags = normalize_cn_tags(list(tags.get("display_tags") or []))
                pred_cids = set(tags.get("competition_ids") or []) | set(
                    cn_tags_to_competition_ids(pred_tags)
                )
                method = str(tags.get("method") or "rule_cn_dict")
            pred_set = set(pred_tags)

            if pred_fh is not None:
                pred_fh.write(
                    json.dumps(
                        {
                            "case_id": item.get("case_id"),
                            "file_id": item.get("file_id"),
                            "party_name": item.get("party_name"),
                            "violation_behavior": text,
                            "gold_risk_tags": gold_tags,
                            "pred_risk_tags": pred_tags,
                            "gold_competition_ids": sorted(cn_tags_to_competition_ids(gold_tags)),
                            "pred_competition_ids": sorted(pred_cids),
                            "exact_match": pred_set == gold_set,
                            "jaccard": (
                                len(pred_set & gold_set) / len(pred_set | gold_set)
                                if (pred_set | gold_set)
                                else 1.0
                            ),
                            "method": method,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

            if pred_set == gold_set:
                exact += 1
            if pred_set & gold_set:
                partial += 1
            union = pred_set | gold_set
            jaccards.append(len(pred_set & gold_set) / len(union) if union else 1.0)

            for t in pred_set:
                if t in gold_set:
                    tag_tp[t] += 1
                else:
                    tag_fp[t] += 1
            for t in gold_set:
                if t not in pred_set:
                    tag_fn[t] += 1

            gold_cids = set(cn_tags_to_competition_ids(gold_tags))
            cid_tp += len(pred_cids & gold_cids)
            cid_fp += len(pred_cids - gold_cids)
            cid_fn += len(gold_cids - pred_cids)

            # 关键词：标签词典中命中原文的词集合 P/R/F1
            gold_kws = _keywords_in_text(text, gold_tags, kw_map)
            pred_kws = _keywords_in_text(text, pred_tags, kw_map)
            if gold_kws or pred_kws:
                kw_cases_with_gold += 1
            kw_tp += len(pred_kws & gold_kws)
            kw_fp += len(pred_kws - gold_kws)
            kw_fn += len(gold_kws - pred_kws)

            if i % 20 == 0 or i == total:
                print(
                    f"  progress {i}/{total} exact={exact / i:.3f} llm_fail={llm_fail}",
                    flush=True,
                )
    finally:
        if pred_fh is not None:
            pred_fh.close()

    n = len(rows) or 1
    per_tag = {}
    f1s = []
    for tag in CANONICAL_CN_TAGS:
        if tag == "其他" and tag_tp[tag] + tag_fp[tag] + tag_fn[tag] == 0:
            continue
        p, r, f1 = _prf(tag_tp[tag], tag_fp[tag], tag_fn[tag])
        if tag_tp[tag] + tag_fp[tag] + tag_fn[tag] == 0:
            continue
        per_tag[tag] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "tp": tag_tp[tag],
            "fp": tag_fp[tag],
            "fn": tag_fn[tag],
        }
        f1s.append(f1)

    cp, cr, cf1 = _prf(cid_tp, cid_fp, cid_fn)
    kw_p, kw_r, kw_f1 = _prf(kw_tp, kw_fp, kw_fn)

    report: dict[str, Any] = {
        "evaluated": len(rows),
        "tagging_mode": "llm_cn" if args.with_llm else "rule_cn_dict",
        "llm_fail": llm_fail if args.with_llm else 0,
        "risk_tags": {
            "label_accuracy": round(exact / n, 4),
            "label_exact_match_accuracy": round(exact / n, 4),
            "label_partial_hit_rate": round(partial / n, 4),
            "label_mean_jaccard": round(sum(jaccards) / n, 4),
            "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
            "competition_id_macro_f1": round(cf1, 4),
            "competition_id_precision": round(cp, 4),
            "competition_id_recall": round(cr, 4),
            "per_tag": per_tag,
        },
        "keywords": {
            "precision": round(kw_p, 4),
            "recall": round(kw_r, 4),
            "f1": round(kw_f1, 4),
            "tp": kw_tp,
            "fp": kw_fp,
            "fn": kw_fn,
            "cases_with_any_keyword": kw_cases_with_gold,
            "note": "预测/金标标签各自词典关键词中、实际出现在 violation_behavior 的词集合 F1",
        },
        "case_summary": None,
        "manual_spot_check": {
            "note": "赛题「人工抽查」不自动打分；可抽查摘要噪声与标签合理性",
            "suggested_sample_size": min(30, len(rows)),
        },
        # 兼容旧字段（顶层）
        "label_exact_match_accuracy": round(exact / n, 4),
        "label_partial_hit_rate": round(partial / n, 4),
        "label_mean_jaccard": round(sum(jaccards) / n, 4),
        "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
        "competition_id_macro_f1": round(cf1, 4),
        "competition_id_precision": round(cp, 4),
        "competition_id_recall": round(cr, 4),
        "note": "任务2：风险标签 + 关键词 +（可选）案例摘要 BERTScore",
    }
    if pred_out_path is not None:
        report["predictions_out"] = str(pred_out_path)

    if args.extracted:
        ext_path = Path(args.extracted)
        if not ext_path.is_absolute():
            ext_path = _ROOT / ext_path
        preds = _load_jsonl(ext_path)
        pairs = _match_by_file(rows, preds)
        matched = sum(1 for g, e in pairs if g is not None and e is not None)
        report["case_summary"] = _score_summaries(
            pairs,
            use_bert=not args.no_bert_score,
            bert_model=args.bert_model,
            bert_device=args.bert_device,
            bert_batch_size=args.bert_batch_size,
        )
        report["case_summary"]["matched_pairs"] = matched
        report["case_summary"]["gold_cases"] = len(rows)
        report["case_summary"]["pred_cases"] = len(preds)
        report["case_summary"]["extracted"] = str(ext_path)
    else:
        report["case_summary"] = {
            "skipped": True,
            "reason": "未提供 --extracted；无法对比案例摘要",
        }

    out = Path(args.output)
    if not out.is_absolute():
        out = _ROOT / out
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "evaluated": report["evaluated"],
        "tagging_mode": report.get("tagging_mode"),
        "label_accuracy": report["risk_tags"]["label_accuracy"],
        "macro_f1": report["macro_f1"],
        "competition_id_macro_f1": report["competition_id_macro_f1"],
        "keywords_f1": report["keywords"]["f1"],
        "case_summary": {
            k: report["case_summary"].get(k)
            for k in ("f1", "precision", "recall", "scoring", "n_scored", "skipped", "reason")
            if k in report["case_summary"]
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report → {out}")
    if pred_out_path is not None:
        print(f"Predictions → {pred_out_path}")
    if pool is not None:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
