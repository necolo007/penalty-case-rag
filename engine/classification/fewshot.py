"""任务二动态 few-shot：词法/可选 dense 检索 + MMR + 长尾配额。"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from collections.abc import Iterable
from typing import Any, Protocol

from engine.classification.competition_label_map import (
    CANONICAL_CN_TAGS,
    normalize_cn_tags,
)

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

_PUNCT_RE = re.compile(
    r"[\s，。；、：,;:.!?！？()（）\[\]【】{}“”\"'’‘`~—\-_/\\|<>《》&*+=%$@^]+"
)
# 数字归一为 #（保留在归一化结果里，故 # 不在标点表内）：
# 金额/保单件数差异不该影响行为语义匹配
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
_NGRAM_SIZES = (2, 3)

# 决定书套话：出现在示例正文里对判定没有信息量，检索时降权
_STOP_GRAMS = frozenset({
    "公司", "支公司", "分公司", "中心支", "保险", "股份", "有限", "限公", "责任",
    "违法", "法违", "违规", "行为", "存在", "负有", "责任", "该公", "你公", "当事",
    "监管", "保监", "银保", "监局", "罚款", "警告", "改正", "处罚", "决定",
})


class SyncTextEncoder(Protocol):
    """同步文本编码器（engine.embedding.provider.BaseEmbeddingProvider 兼容）。"""

    def encode_documents(self, texts: list[str]) -> list[list[float]]: ...

    def encode_queries(self, texts: list[str]) -> list[list[float]]: ...


def normalize_for_match(text: str) -> str:
    """去标点、数字归一，避免金额/保单件数差异淹没行为语义。"""
    cleaned = _NUM_RE.sub("#", text or "")
    return _PUNCT_RE.sub("", cleaned)


def char_ngrams(text: str) -> Counter[str]:
    normalized = normalize_for_match(text)
    grams: Counter[str] = Counter()
    for size in _NGRAM_SIZES:
        if len(normalized) < size:
            continue
        for i in range(len(normalized) - size + 1):
            gram = normalized[i : i + size]
            if gram in _STOP_GRAMS:
                continue
            grams[gram] += 1
    return grams


@dataclass(frozen=True)
class FewShotExample:
    """一条 few-shot 示例：违法事实 + 金标标签 + 可选判定要点。"""

    example_id: str
    violation_behavior: str
    risk_tags: tuple[str, ...]
    case_id: str = ""
    typicality: float = 0.0
    note: str = ""
    source: str = ""

    @classmethod
    def from_dict(cls, row: dict[str, Any], *, fallback_id: str = "") -> FewShotExample | None:
        text = (row.get("violation_behavior") or "").strip()
        tags = tuple(normalize_cn_tags(row.get("risk_tags") or []))
        if not text or not tags:
            return None
        return cls(
            example_id=str(row.get("example_id") or row.get("case_id") or fallback_id),
            violation_behavior=text,
            risk_tags=tags,
            case_id=str(row.get("case_id") or ""),
            typicality=float(row.get("typicality") or 0.0),
            note=(row.get("note") or "").strip(),
            source=(row.get("source") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_id": self.example_id,
            "case_id": self.case_id,
            "violation_behavior": self.violation_behavior,
            "risk_tags": list(self.risk_tags),
            "typicality": round(self.typicality, 4),
            "note": self.note,
            "source": self.source,
        }


@dataclass(frozen=True)
class FewShotHit:
    example: FewShotExample
    score: float
    reason: str = "similar"  # similar | tag_quota


class _LexicalIndex:
    """字符 n-gram TF-IDF 倒排索引；余弦相似度，同步且无模型依赖。"""

    def __init__(self, docs: list[str]):
        tf_list = [char_ngrams(d) for d in docs]
        df: Counter[str] = Counter()
        for tf in tf_list:
            df.update(tf.keys())
        n = max(len(docs), 1)
        self._idf = {gram: math.log(1.0 + n / (1 + cnt)) for gram, cnt in df.items()}
        self._vectors: list[dict[str, float]] = []
        self._postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for idx, tf in enumerate(tf_list):
            vec = self._weight(tf)
            self._vectors.append(vec)
            for gram, weight in vec.items():
                self._postings[gram].append((idx, weight))

    def _weight(self, tf: Counter[str]) -> dict[str, float]:
        raw = {
            gram: (1.0 + math.log(cnt)) * self._idf.get(gram, 0.0)
            for gram, cnt in tf.items()
        }
        raw = {gram: w for gram, w in raw.items() if w > 0.0}
        norm = math.sqrt(sum(w * w for w in raw.values()))
        if norm <= 0.0:
            return {}
        return {gram: w / norm for gram, w in raw.items()}

    def encode(self, text: str) -> dict[str, float]:
        return self._weight(char_ngrams(text))

    def score_all(self, query_vec: dict[str, float]) -> dict[int, float]:
        scores: dict[int, float] = defaultdict(float)
        for gram, qw in query_vec.items():
            for idx, dw in self._postings.get(gram, ()):
                scores[idx] += qw * dw
        return scores

    def pair_similarity(self, i: int, j: int) -> float:
        a, b = self._vectors[i], self._vectors[j]
        if len(a) > len(b):
            a, b = b, a
        return sum(w * b.get(gram, 0.0) for gram, w in a.items())


class _DenseIndex:
    """可选向量通道：示例向量在构库时一次性编码，查询时按需编码。"""

    def __init__(self, docs: list[str], encoder: SyncTextEncoder):
        self._encoder = encoder
        self._doc_vecs = [_l2_normalize(v) for v in encoder.encode_documents(docs)]

    def score_all(self, text: str) -> dict[int, float]:
        query = _l2_normalize(self._encoder.encode_queries([text])[0])
        return {
            idx: sum(a * b for a, b in zip(query, vec))
            for idx, vec in enumerate(self._doc_vecs)
        }

    def pair_similarity(self, i: int, j: int) -> float:
        return sum(a * b for a, b in zip(self._doc_vecs[i], self._doc_vecs[j]))


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return list(vec)
    return [v / norm for v in vec]


class FewShotBank:
    """示例库：加载 → 索引 → 相似检索（MMR + 长尾配额）。"""

    def __init__(
        self,
        examples: list[FewShotExample],
        *,
        encoder: SyncTextEncoder | None = None,
        name: str = "",
    ):
        self.examples = list(examples)
        self.name = name
        self._by_tag: dict[str, list[int]] = defaultdict(list)
        for idx, ex in enumerate(self.examples):
            for tag in ex.risk_tags:
                self._by_tag[tag].append(idx)
        docs = [ex.violation_behavior for ex in self.examples]
        self._lexical = _LexicalIndex(docs) if docs else None
        self._dense: _DenseIndex | None = None
        if encoder is not None and docs:
            try:
                self._dense = _DenseIndex(docs, encoder)
            except Exception as exc:  # noqa: BLE001 - 向量通道是增强项，失败降级词法
                logger.warning("few-shot dense channel disabled: %s", exc)
        # 稀有度：示例最少的标签给更高权重，帮助长尾类别被召回
        counts = {tag: len(idxs) for tag, idxs in self._by_tag.items()}
        max_count = max(counts.values()) if counts else 1
        self._rarity = [
            max(
                (
                    1.0 - (counts.get(tag, 0) / max_count)
                    for tag in ex.risk_tags
                ),
                default=0.0,
            )
            for ex in self.examples
        ]

    def __len__(self) -> int:
        return len(self.examples)

    @property
    def covered_tags(self) -> frozenset[str]:
        """示例库实际覆盖的标签（用于「缺类走静态、有类才 few-shot」门控）。"""
        return frozenset(self._by_tag.keys())

    @classmethod
    def from_jsonl(
        cls,
        path: str | Path,
        *,
        encoder: SyncTextEncoder | None = None,
    ) -> FewShotBank:
        p = Path(path)
        if not p.is_absolute():
            p = _ROOT / p
        examples: list[FewShotExample] = []
        seen: set[str] = set()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            ex = FewShotExample.from_dict(json.loads(line), fallback_id=f"E{i:04d}")
            if ex is None or ex.example_id in seen:
                continue
            seen.add(ex.example_id)
            examples.append(ex)
        if not examples:
            raise ValueError(f"few-shot bank is empty: {p}")
        return cls(examples, encoder=encoder, name=p.name)

    def search(
        self,
        text: str,
        *,
        top_n: int = 4,
        min_score: float = 0.03,
        mmr_lambda: float = 0.7,
        rarity_boost: float = 0.15,
        dense_weight: float = 0.5,
        tag_hints: list[str] | None = None,
        pool_size: int = 40,
        exclude_case_ids: Iterable[str] | None = None,
        max_self_similarity: float = 0.995,
    ) -> list[FewShotHit]:
        """检索最相关示例。

        tag_hints（通常来自关键词初判）用于长尾配额：命中标签若未被相似检索
        覆盖，则从该标签的示例中补一条，避免长尾类别永远拿不到示例。

        exclude_case_ids / max_self_similarity 防止把待判案例自身（或其重复件）
        当成示例注入——那会让离线指标虚高而线上无效。
        """
        if not self.examples or top_n <= 0 or not (text or "").strip():
            return []

        relevance = self._relevance(text, dense_weight=dense_weight)
        relevance = self._drop_self_matches(
            relevance, exclude_case_ids=exclude_case_ids,
            max_self_similarity=max_self_similarity,
        )
        if not relevance:
            return []
        ranked = sorted(relevance.items(), key=lambda kv: kv[1], reverse=True)
        pool = [(idx, s) for idx, s in ranked[: max(pool_size, top_n)] if s >= min_score]
        selected = self._mmr(pool, top_n=top_n, mmr_lambda=mmr_lambda,
                             rarity_boost=rarity_boost)

        hits = [FewShotHit(self.examples[i], round(relevance[i], 4)) for i in selected]
        hits.extend(self._fill_tag_quota(
            tag_hints, relevance, selected, top_n=top_n, min_score=min_score,
        ))
        return hits

    def _relevance(self, text: str, *, dense_weight: float) -> dict[int, float]:
        lexical = self._lexical.score_all(self._lexical.encode(text)) if self._lexical else {}
        if self._dense is None:
            return dict(lexical)
        dense = self._dense.score_all(text)
        w = min(max(dense_weight, 0.0), 1.0)
        merged: dict[int, float] = {}
        for idx in set(lexical) | set(dense):
            merged[idx] = (1.0 - w) * lexical.get(idx, 0.0) + w * dense.get(idx, 0.0)
        return merged

    def _drop_self_matches(
        self,
        relevance: dict[int, float],
        *,
        exclude_case_ids: Iterable[str] | None,
        max_self_similarity: float,
    ) -> dict[int, float]:
        excluded = {str(c).strip() for c in (exclude_case_ids or ()) if str(c).strip()}
        threshold = min(max(max_self_similarity, 0.0), 1.0)
        return {
            idx: score
            for idx, score in relevance.items()
            if score < threshold
            and self.examples[idx].case_id not in excluded
            and self.examples[idx].example_id not in excluded
        }

    def pair_similarity(self, i: int, j: int) -> float:
        """示例间相似度（构库选样与 MMR 共用同一度量）。"""
        if self._dense is not None:
            return self._dense.pair_similarity(i, j)
        return self._lexical.pair_similarity(i, j) if self._lexical else 0.0

    def _mmr(
        self,
        pool: list[tuple[int, float]],
        *,
        top_n: int,
        mmr_lambda: float,
        rarity_boost: float,
    ) -> list[int]:
        """最大边际相关：相关性 + 稀有标签加权 - 与已选示例的冗余。"""
        lam = min(max(mmr_lambda, 0.0), 1.0)
        remaining = dict(pool)
        selected: list[int] = []
        while remaining and len(selected) < top_n:
            best_idx, best_score = None, -math.inf
            for idx, rel in remaining.items():
                adjusted = rel * (1.0 + rarity_boost * self._rarity[idx])
                redundancy = max(
                    (self.pair_similarity(idx, s) for s in selected), default=0.0
                )
                score = lam * adjusted - (1.0 - lam) * redundancy
                if score > best_score:
                    best_idx, best_score = idx, score
            if best_idx is None:
                break
            selected.append(best_idx)
            remaining.pop(best_idx)
        return selected

    def _fill_tag_quota(
        self,
        tag_hints: list[str] | None,
        relevance: dict[int, float],
        selected: list[int],
        *,
        top_n: int,
        min_score: float,
        clean_tag_limit: int = 5,
    ) -> list[FewShotHit]:
        hints = [t for t in normalize_cn_tags(tag_hints or []) if t != "其他"]
        if not hints:
            return []
        # 只有标签数适中的示例才算「有效覆盖」：被 9 标签杂案顺带覆盖的长尾标签
        # 在提示里学不到边界，仍应补一条更干净的示例
        covered = {
            tag
            for i in selected
            if len(self.examples[i].risk_tags) <= clean_tag_limit
            for tag in self.examples[i].risk_tags
        }
        chosen = set(selected)
        extra: list[FewShotHit] = []
        budget = max(1, top_n // 2)
        for tag in hints:
            if tag in covered or len(extra) >= budget:
                continue
            candidates = [i for i in self._by_tag.get(tag, ()) if i not in chosen]
            if not candidates:
                continue
            clean = [i for i in candidates if len(self.examples[i].risk_tags) <= clean_tag_limit]
            best = max(
                clean or candidates,
                key=lambda i: (relevance.get(i, 0.0), self.examples[i].typicality),
            )
            if relevance.get(best, 0.0) <= 0.0 and self.examples[best].typicality <= 0.0:
                continue
            chosen.add(best)
            covered.update(self.examples[best].risk_tags)
            extra.append(
                FewShotHit(self.examples[best], round(relevance.get(best, min_score), 4),
                           reason="tag_quota")
            )
        return extra

    def stats(self) -> dict[str, Any]:
        per_tag = {tag: len(self._by_tag.get(tag, ())) for tag in CANONICAL_CN_TAGS}
        covered = {t: c for t, c in per_tag.items() if c}
        return {
            "name": self.name,
            "examples": len(self.examples),
            "tags_covered": len(covered),
            "tags_missing": [t for t, c in per_tag.items() if not c],
            "dense_channel": self._dense is not None,
            "per_tag": per_tag,
            "avg_tags_per_example": (
                round(sum(len(e.risk_tags) for e in self.examples) / len(self.examples), 3)
                if self.examples else 0.0
            ),
        }


def format_fewshot_block(
    hits: list[FewShotHit],
    *,
    max_chars: int = 1800,
    max_behavior_chars: int = 420,
) -> str:
    """渲染为 Prompt 片段；空命中返回空串（调用方据此跳过整段）。"""
    if not hits:
        return ""
    lines: list[str] = []
    used = 0
    for i, hit in enumerate(hits, 1):
        behavior = " ".join(hit.example.violation_behavior.split())
        truncated = len(behavior) > max_behavior_chars
        if truncated:
            behavior = behavior[:max_behavior_chars] + "…"
        tags = "、".join(hit.example.risk_tags)
        block = f"[例{i}] 违法行为：{behavior}\n      正确标签：{tags}"
        if truncated:
            # 截断提示，避免少事实多标签
            block += "（示例原文过长已截断，标签依据完整原文）"
        if hit.example.note:
            block += f"\n      判定要点：{hit.example.note}"
        if used + len(block) > max_chars and lines:
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines)


@lru_cache(maxsize=4)
def _load_bank_cached(path: str, use_dense: bool) -> FewShotBank | None:
    encoder: SyncTextEncoder | None = None
    if use_dense:
        try:
            from engine.embedding.provider import create_embedding_provider

            encoder = create_embedding_provider()
        except Exception as exc:  # noqa: BLE001 - 无模型环境降级词法通道
            logger.warning("few-shot dense encoder unavailable, fallback lexical: %s", exc)
    try:
        bank = FewShotBank.from_jsonl(path, encoder=encoder)
    except FileNotFoundError:
        logger.warning(
            "few-shot bank not found: %s（先跑 scripts/import_excel_fewshot_bank.py 或 import_multilabel_fewshot_bank.py）", path
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("few-shot bank load failed (%s): %s", path, exc)
        return None
    logger.info(
        "few-shot bank loaded: %s examples=%d tags_covered=%d dense=%s",
        bank.name, len(bank), bank.stats()["tags_covered"], bank.stats()["dense_channel"],
    )
    return bank


def get_default_bank() -> FewShotBank | None:
    """按配置加载全局示例库；未启用或文件缺失时返回 None（自动退回纯规则 Prompt）。"""
    from core.config import get_settings

    settings = get_settings()
    if not getattr(settings, "FEWSHOT_ENABLED", False):
        return None
    path = (getattr(settings, "FEWSHOT_BANK_PATH", "") or "").strip()
    if not path:
        return None
    retriever = (getattr(settings, "FEWSHOT_RETRIEVER", "lexical") or "lexical").lower()
    return _load_bank_cached(path, retriever in ("hybrid", "dense", "embedding"))


def reset_default_bank() -> None:
    """清缓存：构库脚本重跑或热更新后调用。"""
    _load_bank_cached.cache_clear()


def fewshot_gate_allows(
    tag_hints: list[str] | None,
    bank: FewShotBank | None,
    *,
    require_covered_hint: bool = True,
) -> bool:
    """缺类走静态 Prompt：关键词初判未命中库内标签时不注入 few-shot。

    多标签场景下，只要初判里有任意一个「库内有示例」的标签，就允许动态 few-shot；
    库外长尾标签继续依赖 Prompt 里的消歧规则，避免被无关示例带偏。
    """
    if bank is None:
        return False
    if not require_covered_hint:
        return True
    covered = bank.covered_tags - {"其他"}
    if not covered:
        return False
    hints = [t for t in normalize_cn_tags(tag_hints or []) if t != "其他"]
    if not hints:
        # 无关键词线索时不做 few-shot，避免仅靠弱相似拉来大量「其他」噪声
        return False
    return any(h in covered for h in hints)


def retrieve_fewshot_hits(
    violation_behavior: str,
    *,
    bank: FewShotBank | None = None,
    tag_hints: list[str] | None = None,
    exclude_case_ids: Iterable[str] | None = None,
    top_n: int | None = None,
) -> list[FewShotHit]:
    """按配置检索示例；失败静默返回空列表（few-shot 不得影响打标主链路）。"""
    from core.config import get_settings

    bank = bank if bank is not None else get_default_bank()
    if bank is None:
        return []
    settings = get_settings()
    require_gate = bool(getattr(settings, "FEWSHOT_REQUIRE_COVERED_HINT", True))
    if not fewshot_gate_allows(tag_hints, bank, require_covered_hint=require_gate):
        return []
    # 配额只对库内标签生效，避免为缺类空转
    covered = bank.covered_tags
    gated_hints = [t for t in normalize_cn_tags(tag_hints or []) if t in covered]
    try:
        return bank.search(
            violation_behavior,
            top_n=int(top_n if top_n is not None else getattr(settings, "FEWSHOT_TOP_N", 4)),
            min_score=float(getattr(settings, "FEWSHOT_MIN_SCORE", 0.03)),
            mmr_lambda=float(getattr(settings, "FEWSHOT_MMR_LAMBDA", 0.7)),
            rarity_boost=float(getattr(settings, "FEWSHOT_RARITY_BOOST", 0.15)),
            dense_weight=float(getattr(settings, "FEWSHOT_DENSE_WEIGHT", 0.5)),
            tag_hints=gated_hints or None,
            exclude_case_ids=exclude_case_ids,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("few-shot retrieval failed, continue without examples: %s", exc)
        return []


def _parse_fixed_ids(raw: str | Iterable[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.replace(";", ",").split(",")
    else:
        parts = list(raw)
    return [p.strip() for p in parts if str(p).strip()]


def retrieve_fixed_fewshot_hits(
    *,
    bank: FewShotBank | None = None,
    fixed_ids: str | Iterable[str] | None = None,
) -> list[FewShotHit]:
    """按固定 ID 取示例；顺序与配置一致，缺失 ID 跳过。"""
    from core.config import get_settings

    bank = bank if bank is not None else get_default_bank()
    if bank is None:
        return []
    settings = get_settings()
    ids = _parse_fixed_ids(
        fixed_ids if fixed_ids is not None else getattr(settings, "FEWSHOT_FIXED_IDS", "")
    )
    if not ids:
        return []
    by_id = {ex.example_id: ex for ex in bank.examples}
    hits: list[FewShotHit] = []
    for eid in ids:
        ex = by_id.get(eid)
        if ex is None:
            logger.warning("fixed few-shot id not in bank: %s", eid)
            continue
        hits.append(FewShotHit(ex, 1.0, reason="fixed"))
    return hits


def build_fewshot_block(
    violation_behavior: str,
    *,
    bank: FewShotBank | None = None,
    tag_hints: list[str] | None = None,
    exclude_case_ids: Iterable[str] | None = None,
    mode: str | None = None,
    fixed_ids: str | Iterable[str] | None = None,
) -> str:
    """给定违法事实，返回可直接插入 Prompt 的示例段（无命中时为空串）。

    mode=dynamic：按案检索；mode=fixed：每案同一批固定示例。
    """
    from core.config import get_settings

    settings = get_settings()
    use_mode = (mode or getattr(settings, "FEWSHOT_MODE", "dynamic") or "dynamic").strip().lower()
    if use_mode == "fixed":
        hits = retrieve_fixed_fewshot_hits(bank=bank, fixed_ids=fixed_ids)
    else:
        hits = retrieve_fewshot_hits(
            violation_behavior,
            bank=bank,
            tag_hints=tag_hints,
            exclude_case_ids=exclude_case_ids,
        )
    if not hits:
        return ""
    return format_fewshot_block(
        hits,
        max_chars=int(getattr(settings, "FEWSHOT_MAX_CHARS", 1800)),
        max_behavior_chars=int(getattr(settings, "FEWSHOT_MAX_BEHAVIOR_CHARS", 420)),
    )
