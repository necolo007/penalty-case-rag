import { RISK_ATLAS, RISK_NAME_MAP } from "./riskAtlas";

/** 同一风险大类共用同一色系 */
const CATEGORY_TONES: Record<string, { bg: string; text: string; ring: string }> = {
  销售合规类: { bg: "bg-sky-50", text: "text-sky-800", ring: "ring-sky-200" },
  宣传材料类: { bg: "bg-violet-50", text: "text-violet-800", ring: "ring-violet-200" },
  财务费用类: { bg: "bg-rose-50", text: "text-rose-800", ring: "ring-rose-200" },
  消费者权益类: { bg: "bg-amber-50", text: "text-amber-900", ring: "ring-amber-200" },
  内控治理类: { bg: "bg-emerald-50", text: "text-emerald-800", ring: "ring-emerald-200" },
};

const FALLBACK_TONES = [
  { bg: "bg-slate-50", text: "text-slate-700", ring: "ring-slate-200" },
  { bg: "bg-indigo-50", text: "text-indigo-800", ring: "ring-indigo-200" },
  { bg: "bg-teal-50", text: "text-teal-800", ring: "ring-teal-200" },
  { bg: "bg-orange-50", text: "text-orange-800", ring: "ring-orange-200" },
];

const ID_TO_CATEGORY = Object.fromEntries(RISK_ATLAS.map((r) => [r.id, r.category]));

export function riskTone(riskIdOrTag: string): { bg: string; text: string; ring: string } {
  const id = riskIdOrTag.toUpperCase().match(/R00[1-8]/)?.[0];
  if (id && ID_TO_CATEGORY[id]) {
    return CATEGORY_TONES[ID_TO_CATEGORY[id]] ?? FALLBACK_TONES[0];
  }
  // 按标签名哈希到稳定色
  let hash = 0;
  for (let i = 0; i < riskIdOrTag.length; i += 1) {
    hash = (hash * 31 + riskIdOrTag.charCodeAt(i)) >>> 0;
  }
  return FALLBACK_TONES[hash % FALLBACK_TONES.length];
}

export function riskLabel(idOrTag: string): string {
  const id = idOrTag.toUpperCase().match(/R00[1-8]/)?.[0];
  if (id && RISK_NAME_MAP[id]) return RISK_NAME_MAP[id];
  return idOrTag;
}
