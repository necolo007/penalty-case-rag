import type { CaseResult } from "../api/types";
import { CN_RISK_TAGS } from "./cnRiskTags";
import { RISK_ATLAS } from "./riskAtlas";

const SCENE_HINTS: Array<{ pattern: RegExp; label: string }> = [
  { pattern: /营销|宣传|话术|推介|礼品|奖品|赠送/, label: "保险销售宣传" },
  { pattern: /培训|说明会/, label: "培训与说明材料" },
  { pattern: /合同|条款|投保/, label: "销售签约场景" },
  { pattern: /费用|财务|中介/, label: "费用与财务场景" },
];

const BEHAVIOR_HINTS: Array<{ pattern: RegExp; label: string }> = [
  { pattern: /礼品|奖品|赠送|领取|体检卡|加油卡/, label: "买即送礼 / 额外赠送" },
  { pattern: /保本|保收益|收益稳定|无风险|稳赚/, label: "承诺收益 / 无风险表述" },
  { pattern: /夸大|虚假|隐瞒/, label: "夸大或隐瞒重要信息" },
  { pattern: /返佣|补贴|费用/, label: "费用或利益输送" },
];

const RISK_DESC_HINTS: Array<{ pattern: RegExp; label: string }> = [
  { pattern: /保本|保收益|收益稳定|无风险/, label: "承诺收益 / 无风险" },
  { pattern: /礼品|奖品|赠送/, label: "合同外利益输送" },
  { pattern: /虚假|夸大|误导/, label: "虚假宣传 / 销售误导" },
];

const KEYWORD_POOL = [
  "保本",
  "保收益",
  "无风险",
  "赠送",
  "礼品",
  "奖品",
  "返佣",
  "补贴",
  "夸大",
  "虚假",
  "误导",
  "体检卡",
  "加油卡",
  "收益稳定",
  "稳赚",
  "合同约定以外",
  "其他利益",
];

export type EvidenceMatchStatus = "high" | "partial" | "miss";

export type EvidenceRow = {
  queryElement: string;
  caseEvidence: string;
  status: EvidenceMatchStatus;
  note: string;
};

export function inferBusinessScene(query: string): string {
  const hit = SCENE_HINTS.find((s) => s.pattern.test(query));
  return hit?.label ?? "业务合规审查场景";
}

export function inferBehaviorElements(query: string): string[] {
  const hits = BEHAVIOR_HINTS.filter((s) => s.pattern.test(query)).map((s) => s.label);
  if (hits.length) return hits.slice(0, 3);
  const kws = extractRiskKeywords(query, 2);
  return kws.length ? kws : ["语义行为特征"];
}

export function inferRiskDescription(query: string): string {
  const hit = RISK_DESC_HINTS.find((s) => s.pattern.test(query));
  if (hit) return hit.label;
  const kws = extractRiskKeywords(query, 2);
  return kws.length ? kws.join(" / ") : "待解析风险表述";
}

export function extractRiskKeywords(query: string, max = 4): string[] {
  const found = KEYWORD_POOL.filter((k) => query.includes(k));
  if (found.length >= 2) return found.slice(0, max);

  const chunks = query
    .replace(/[，。；、！？\s]+/g, " ")
    .split(" ")
    .map((s) => s.trim())
    .filter((s) => s.length >= 2 && s.length <= 8);

  return [...new Set([...found, ...chunks])].slice(0, max);
}

export function riskLabel(id: string): string {
  const cn = CN_RISK_TAGS.find((t) => t.risk_tag === id);
  if (cn) return cn.risk_tag;
  const meta = RISK_ATLAS.find((r) => r.id === id);
  return meta ? `${id} ${meta.name}` : id;
}

export function expandQueryTerms(original: string, rewritten: string): string[] {
  const merged = `${original} ${rewritten}`;
  const terms = new Set<string>();
  for (const k of KEYWORD_POOL) {
    if (merged.includes(k)) terms.add(k);
  }
  for (const meta of RISK_ATLAS) {
    for (const p of meta.phrases) {
      if (merged.includes(p.slice(0, 6))) terms.add(p);
    }
    if (meta.name && merged.includes(meta.name.slice(0, 2))) {
      terms.add(meta.name);
    }
  }
  return [...terms].slice(0, 6);
}

/** 直接使用后端相关分（0~1），不做假下限抬升 */
export function relevancePercent(score: number): number {
  return Math.round(Math.min(100, Math.max(0, score * 100)) * 10) / 10;
}

export function relevanceTier(score: number): { label: string; tone: string } {
  const pct = relevancePercent(score);
  if (pct >= 70) return { label: "高度相关", tone: "text-accent" };
  if (pct >= 45) return { label: "相关", tone: "text-secondary" };
  return { label: "一般相关", tone: "text-muted-fg" };
}

export function countHighRelevance(results: CaseResult[], threshold = 0.7): number {
  return results.filter((r) => r.score >= threshold).length;
}

/** 解析后端可解释命中理由（按分号拆事实点，禁止模板套话） */
export function parseMatchFacts(reason: string): string[] {
  const cleaned = (reason || "")
    .replace(/行为目的一致|业务场景一致|高度近似|多路召回交叉验证/g, "")
    .trim();
  if (!cleaned) return [];
  return cleaned
    .split(/[；;。]/)
    .map((s) => s.trim())
    .filter((s) => s.length >= 4)
    .slice(0, 6);
}

export function penaltyHighlight(item: CaseResult): string {
  return (
    item.penalty_content?.trim() ||
    item.violation_behavior?.trim() ||
    "暂无处罚结果摘要"
  );
}

export function caseHeadline(item: CaseResult, max = 52): string {
  const raw = (item.violation_behavior || item.penalty_content || item.party_name || item.case_id).trim();
  const one = raw.split(/[。；;\n]/)[0]?.trim() || raw;
  return one.length > max ? `${one.slice(0, max)}…` : one;
}

function corpusOf(item: CaseResult): string {
  return [item.violation_behavior, item.penalty_content, item.match_reason, item.party_name]
    .filter(Boolean)
    .join("\n");
}

function snippetAround(text: string, term: string, radius = 28): string {
  const idx = text.indexOf(term);
  if (idx < 0) return "";
  const start = Math.max(0, idx - radius);
  const end = Math.min(text.length, idx + term.length + radius);
  let snip = text.slice(start, end).replace(/\s+/g, " ").trim();
  if (start > 0) snip = `…${snip}`;
  if (end < text.length) snip = `${snip}…`;
  return snip;
}

/** 查询要素 ↔ 案例证据对照表 */
export function buildEvidenceRows(query: string, item: CaseResult): EvidenceRow[] {
  const corpus = corpusOf(item);
  const elements = [
    ...inferBehaviorElements(query),
    ...extractRiskKeywords(query, 4),
  ];
  const uniq = [...new Set(elements)].slice(0, 5);
  const facts = parseMatchFacts(item.match_reason);
  const rows: EvidenceRow[] = [];

  for (const el of uniq) {
    const directHit = KEYWORD_POOL.filter((k) => el.includes(k) || k.includes(el)).find((k) =>
      corpus.includes(k),
    );
    const selfHit = corpus.includes(el) ? el : null;
    const hit = selfHit || directHit || null;

    if (hit) {
      rows.push({
        queryElement: el,
        caseEvidence: snippetAround(corpus, hit) || hit,
        status: selfHit ? "high" : "partial",
        note: selfHit ? "原文直接命中" : `语义对应「${hit}」`,
      });
      continue;
    }

    if (/礼品|奖品|赠送|利益/.test(el) && /约定以外|其他利益|给予.*利益|赠送|礼品/.test(corpus)) {
      const anchor = corpus.match(/约定以外[^。；]{0,20}|其他利益|给予投保人[^。；]{0,24}/)?.[0];
      rows.push({
        queryElement: el,
        caseEvidence: anchor || "给予合同约定以外的利益",
        status: "partial",
        note: "表述不同，同属合同外利益",
      });
      continue;
    }

    if (/收益|无风险|保本|保收益/.test(el) && /收益|保本|无风险|误导|夸大/.test(corpus)) {
      const anchor = corpus.match(/[^。；]{0,8}(?:收益|保本|无风险|夸大)[^。；]{0,16}/)?.[0];
      rows.push({
        queryElement: el,
        caseEvidence: anchor?.trim() || "相关收益/宣传表述",
        status: "partial",
        note: "部分语义重合",
      });
      continue;
    }

    rows.push({
      queryElement: el,
      caseEvidence: facts[0] || "案例未直接出现该表述",
      status: "miss",
      note: "未直接命中，供人工复核",
    });
  }

  if (!rows.length && facts.length) {
    rows.push({
      queryElement: "检索语义",
      caseEvidence: facts[0],
      status: "partial",
      note: "基于命中理由",
    });
  }
  return rows.slice(0, 4);
}

export function findMissedKeywords(query: string, item: CaseResult): string[] {
  const corpus = corpusOf(item);
  return extractRiskKeywords(query, 6).filter((k) => !corpus.includes(k)).slice(0, 3);
}

export function differenceNote(query: string, item: CaseResult): string {
  const missed = findMissedKeywords(query, item);
  if (missed.length) {
    return `查询含「${missed.join("、")}」，案例多用近义监管表述（如合同约定以外的利益），属部分匹配而非逐字命中。`;
  }
  const facts = parseMatchFacts(item.match_reason);
  if (facts[0]) return facts[0];
  return "匹配基于语义与风险标签，请结合原文复核差异点。";
}

export function statusLabel(status: EvidenceMatchStatus): string {
  if (status === "high") return "高匹配";
  if (status === "partial") return "部分匹配";
  return "未直接命中";
}

export function highlightTerms(text: string, terms: string[]): Array<{ text: string; hit: boolean }> {
  if (!text) return [];
  const usable = [...new Set(terms.filter((t) => t && t.length >= 2))].sort((a, b) => b.length - a.length);
  if (!usable.length) return [{ text, hit: false }];

  const parts: Array<{ text: string; hit: boolean }> = [];
  let rest = text;
  while (rest.length) {
    let best: { idx: number; term: string } | null = null;
    for (const term of usable) {
      const idx = rest.indexOf(term);
      if (idx >= 0 && (best == null || idx < best.idx)) best = { idx, term };
    }
    if (!best) {
      parts.push({ text: rest, hit: false });
      break;
    }
    if (best.idx > 0) parts.push({ text: rest.slice(0, best.idx), hit: false });
    parts.push({ text: best.term, hit: true });
    rest = rest.slice(best.idx + best.term.length);
  }
  return parts;
}
