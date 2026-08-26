import { cnTagMeta } from "./cnRiskTags";
import { RISK_ATLAS, RISK_NAME_MAP } from "./riskAtlas";

/** 同一风险大类（27 类 category / R00x）共用同一色系 */
const CATEGORY_TONES: Record<string, { bg: string; text: string; ring: string }> = {
  销售误导: { bg: "bg-sky-50", text: "text-sky-800", ring: "ring-sky-200" },
  营销违规: { bg: "bg-rose-50", text: "text-rose-800", ring: "ring-rose-200" },
  营销活动: { bg: "bg-violet-50", text: "text-violet-800", ring: "ring-violet-200" },
  售后违规: { bg: "bg-amber-50", text: "text-amber-900", ring: "ring-amber-200" },
  销售渠道: { bg: "bg-indigo-50", text: "text-indigo-800", ring: "ring-indigo-200" },
  财务违规: { bg: "bg-orange-50", text: "text-orange-800", ring: "ring-orange-200" },
  管理问题: { bg: "bg-teal-50", text: "text-teal-800", ring: "ring-teal-200" },
  合规问题: { bg: "bg-emerald-50", text: "text-emerald-800", ring: "ring-emerald-200" },
  其他: { bg: "bg-slate-50", text: "text-slate-700", ring: "ring-slate-200" },
  // R00x atlas 大类
  销售合规: { bg: "bg-sky-50", text: "text-sky-800", ring: "ring-sky-200" },
  宣传材料: { bg: "bg-violet-50", text: "text-violet-800", ring: "ring-violet-200" },
  费用财务: { bg: "bg-orange-50", text: "text-orange-800", ring: "ring-orange-200" },
  售后服务: { bg: "bg-teal-50", text: "text-teal-800", ring: "ring-teal-200" },
  信息合规: { bg: "bg-indigo-50", text: "text-indigo-800", ring: "ring-indigo-200" },
  产品合规: { bg: "bg-emerald-50", text: "text-emerald-800", ring: "ring-emerald-200" },
  内控培训: { bg: "bg-slate-50", text: "text-slate-800", ring: "ring-slate-200" },
  // 旧别名兼容
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
  const cn = cnTagMeta(riskIdOrTag);
  if (cn?.category && CATEGORY_TONES[cn.category]) {
    return CATEGORY_TONES[cn.category];
  }
  const id = riskIdOrTag.toUpperCase().match(/R0(0[1-9]|1[01])/)?.[0];
  if (id && ID_TO_CATEGORY[id]) {
    return CATEGORY_TONES[ID_TO_CATEGORY[id]] ?? FALLBACK_TONES[0];
  }
  let hash = 0;
  for (let i = 0; i < riskIdOrTag.length; i += 1) {
    hash = (hash * 31 + riskIdOrTag.charCodeAt(i)) >>> 0;
  }
  return FALLBACK_TONES[hash % FALLBACK_TONES.length];
}

export function riskLabel(idOrTag: string): string {
  if (cnTagMeta(idOrTag)) return idOrTag;
  const id = idOrTag.toUpperCase().match(/R0(0[1-9]|1[01])/)?.[0];
  if (id && RISK_NAME_MAP[id]) return RISK_NAME_MAP[id];
  return idOrTag;
}
