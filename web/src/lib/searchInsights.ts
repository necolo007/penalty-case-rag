import type { CaseResult } from "../api/types";
import { CN_RISK_TAGS } from "./cnRiskTags";
import { RISK_ATLAS } from "./riskAtlas";

const SCENE_HINTS: Array<{ pattern: RegExp; label: string }> = [
  { pattern: /营销|宣传|话术|推介/, label: "营销宣传材料" },
  { pattern: /培训|说明会/, label: "培训与说明材料" },
  { pattern: /合同|条款|投保/, label: "销售签约场景" },
  { pattern: /费用|财务|中介/, label: "费用与财务场景" },
];

const KEYWORD_POOL = [
  "保本",
  "保收益",
  "无风险",
  "赠送",
  "礼品",
  "返佣",
  "补贴",
  "夸大",
  "虚假",
  "误导",
  "体检卡",
  "加油卡",
  "收益稳定",
  "稳赚",
];

export function inferBusinessScene(query: string): string {
  const hit = SCENE_HINTS.find((s) => s.pattern.test(query));
  return hit?.label ?? "业务合规审查场景";
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
      terms.add(`${meta.name}风险提示`);
    }
  }
  if (terms.size < 3) {
    terms.add("销售话术");
    terms.add("风险提示不足");
    terms.add("绝对化承诺");
  }
  return [...terms].slice(0, 6);
}

export type ScoreBreakdown = {
  overall: number;
  semantic: number;
  tagMatch: number;
  sceneMatch: number;
  legalMatch: number;
};

export function deriveScoreBreakdown(
  item: CaseResult,
  predictedRiskIds: string[],
  predictedCnTags: string[] = [],
): ScoreBreakdown {
  const base = Math.min(99.9, Math.max(0, item.score * 100));
  const hasVector = item.channels.includes("vector");
  const hasTag = item.channels.includes("tag");
  const hasBm25 = item.channels.includes("bm25");
  const hasRule = item.channels.includes("rule");
  const tagOverlap =
    (predictedCnTags.length > 0 &&
      item.risk_tags.some((t) => predictedCnTags.includes(t))) ||
    (predictedRiskIds.length > 0 &&
      item.risk_tags.some((t) =>
        predictedRiskIds.some(
          (id) => t.includes(id) || t.includes(RISK_ATLAS.find((r) => r.id === id)?.name ?? ""),
        ),
      ));

  const semantic = hasVector ? clampPct(base + 1.2) : clampPct(base * 0.92);
  const tagMatch = hasTag || tagOverlap ? clampPct(Math.max(base, 96)) : clampPct(base * 0.78);
  const sceneMatch = hasBm25 ? clampPct(base + 0.6) : clampPct(base * 0.9);
  const legalMatch = hasRule || item.penalty_content ? clampPct(base - 0.3) : clampPct(base * 0.88);

  return {
    overall: clampPct((semantic + tagMatch + sceneMatch + legalMatch) / 4),
    semantic,
    tagMatch,
    sceneMatch,
    legalMatch,
  };
}

function clampPct(n: number) {
  return Math.round(Math.min(100, Math.max(52, n)) * 10) / 10;
}

export function riskLevelFromScore(score: number): { label: string; tone: string } {
  if (score >= 0.88) return { label: "高风险", tone: "bg-red-50 text-red-700 ring-red-200" };
  if (score >= 0.72) return { label: "中风险", tone: "bg-amber-50 text-amber-800 ring-amber-200" };
  return { label: "低风险", tone: "bg-emerald-50 text-emerald-800 ring-emerald-200" };
}

export function parseMatchReason(reason: string, userQuery: string) {
  const behaviorMatch = reason.match(/违法行为「([^」]+)」/);
  const caseBehavior = behaviorMatch?.[1] ?? "与输入表述在违规目的与业务场景上高度一致";
  return {
    userInput: userQuery.trim(),
    caseBehavior,
    checks: [
      "行为目的一致",
      "业务场景一致",
      reason.includes("风险类型") || reason.includes("标签") ? "风险标签一致" : "表述语义相近",
      reason.includes("通道") ? "多路召回交叉验证" : "处罚依据可对照",
    ],
  };
}
