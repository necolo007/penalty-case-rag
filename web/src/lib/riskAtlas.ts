import type { LucideIcon } from "lucide-react";
import {
  FileText,
  Gift,
  Megaphone,
  Shield,
  UserRound,
  Wallet,
  Building2,
  PhoneCall,
  Percent,
  GraduationCap,
  MoreHorizontal,
} from "lucide-react";

/** 业务类别色（仅表示类别，不表示风险高低） */
export type RiskCategoryTone =
  | "sales"
  | "promo"
  | "finance"
  | "consumer"
  | "governance"
  | "ops"
  | "other";

export interface RiskMeta {
  id: string;
  name: string;
  category: string;
  categoryTone: RiskCategoryTone;
  description: string;
  /** 典型表达 */
  phrases: string[];
  /** 业务口语 → 监管标准表述 */
  colloquialMap: Array<{ oral: string; standard: string }>;
  suggestion: string;
  icon: LucideIcon;
}

/** 赛题粗类 R001–R011（与 risk_type_dictionary.csv / 27 类细标签映射对齐） */
export const RISK_ATLAS: RiskMeta[] = [
  {
    id: "R001",
    name: "销售误导",
    category: "销售合规",
    categoryTone: "sales",
    description:
      "在保险销售过程中对产品进行误导性陈述，夸大收益、弱化风险或隐瞒重要信息，欺骗投保人、被保险人或受益人。",
    phrases: ["本产品稳赚不赔、保证收益", "收益远超银行存款", "风险极低几乎没有风险"],
    colloquialMap: [
      { oral: "稳赚不赔", standard: "欺骗投保人 / 夸大收益" },
      { oral: "保证收益", standard: "对不确定利益作出确定性承诺" },
    ],
    suggestion: "删除绝对化收益承诺，完整披露风险与除外责任，权益以合同约定为准。",
    icon: Megaphone,
  },
  {
    id: "R002",
    name: "合同外利益",
    category: "销售合规",
    categoryTone: "sales",
    description: "向投保人提供保险合同约定以外的利益，以促进投保或影响投保决策。",
    phrases: ["送体检卡", "返现", "加油卡", "补贴", "返佣"],
    colloquialMap: [
      { oral: "送体检卡", standard: "给予投保人合同约定以外的利益" },
      { oral: "投保送礼", standard: "以合同外利益诱导投保" },
    ],
    suggestion: "删除赠礼诱导表述，明确增值服务范围，不以合同外利益吸引投保。",
    icon: Gift,
  },
  {
    id: "R003",
    name: "宣传材料不真实",
    category: "宣传材料",
    categoryTone: "promo",
    description:
      "宣传材料、产品说明会或公开渠道存在虚假、夸大或引人误解的内容，损害消费者知情权。",
    phrases: ["行业第一、最高收益", "数据未经核实的对比宣传", "隐瞒关键限制条件"],
    colloquialMap: [{ oral: "行业第一", standard: "宣传材料不真实 / 引人误解" }],
    suggestion: "统一宣传口径审核，禁用无法证实的绝对化表述，保留可核验数据来源。",
    icon: FileText,
  },
  {
    id: "R004",
    name: "销售人员职业登记管理不规范",
    category: "销售合规",
    categoryTone: "sales",
    description:
      "销售人员未按规定执业登记、代理人管理不到位，或委托无资质机构销售。",
    phrases: ["无资质人员展业", "挂靠展业", "委托无资质机构"],
    colloquialMap: [{ oral: "挂靠展业", standard: "执业登记管理不规范" }],
    suggestion: "核验执业登记与展业区域，禁止无资质人员/机构销售，完善代理人台账。",
    icon: UserRound,
  },
  {
    id: "R005",
    name: "虚挂中介费用套取资金",
    category: "费用财务",
    categoryTone: "finance",
    description: "虚构或虚挂中介业务，通过虚假列支费用等方式套取资金，扰乱费用真实性。",
    phrases: ["虚构中介业务", "虚列费用套取资金", "虚假业务发票"],
    colloquialMap: [{ oral: "走中介套费用", standard: "虚构中介业务套取费用" }],
    suggestion: "核查中介业务真实性与费用凭证，杜绝虚挂套取，强化财务勾稽。",
    icon: Wallet,
  },
  {
    id: "R006",
    name: "编制虚假财务资料",
    category: "费用财务",
    categoryTone: "finance",
    description:
      "编制或提供虚假财务资料、报表或经营数据；无套取细节的虚列费用等也归此类（细标签常归一为「其他」）。",
    phrases: ["虚假财务报表", "业务财务数据不真实", "虚列费用无套取用途"],
    colloquialMap: [{ oral: "做假账", standard: "编制虚假财务资料" }],
    suggestion: "严格执行财务真实性要求，强化内审复核，禁止伪造变造资料。",
    icon: Building2,
  },
  {
    id: "R007",
    name: "售后服务违规",
    category: "售后服务",
    categoryTone: "consumer",
    description: "客户回访等售后环节存在误导、信息不实或阻碍回访等违规行为。",
    phrases: ["回访误导", "诱导肯定回答", "阻碍客户接受回访"],
    colloquialMap: [{ oral: "回访走过场", standard: "回访违规" }],
    suggestion: "按监管要求完成回访确认项，禁止诱导作答与阻碍回访，留存可追溯记录。",
    icon: PhoneCall,
  },
  {
    id: "R008",
    name: "客户信息与隐私违规",
    category: "信息合规",
    categoryTone: "ops",
    description: "客户信息记录虚假或不真实，如代签、回访造假、联系方式不实等。",
    phrases: ["客户资料不真实", "代签代答", "回访记录造假"],
    colloquialMap: [{ oral: "代客户签字", standard: "客户信息不真实" }],
    suggestion: "落实实名留痕与双录/回访真实性核验，禁止代签代答与虚假记录。",
    icon: Shield,
  },
  {
    id: "R009",
    name: "产品费率及合同执行违规",
    category: "产品合规",
    categoryTone: "ops",
    description: "未按监管批准/备案的费率、条款执行，擅自调减费率或变更条款内容。",
    phrases: ["保单费率调减", "优惠系数使用不当", "未按备案条款承保"],
    colloquialMap: [{ oral: "私自降费率", standard: "未按规定使用费率条款" }],
    suggestion: "严格按备案费率与条款承保，变更须履行报备程序。",
    icon: Percent,
  },
  {
    id: "R010",
    name: "内部管理与培训违规",
    category: "内控培训",
    categoryTone: "governance",
    description: "销售培训材料存在误导或违规内容，内部培训管理不到位。",
    phrases: ["培训 PPT 虚假宣传", "话术脚本误导", "培训材料含绝对化表述"],
    colloquialMap: [{ oral: "对内培训话术夸张", standard: "培训材料违规" }],
    suggestion: "审核培训课件与话术脚本，禁用误导性内容，与对外宣传口径一致。",
    icon: GraduationCap,
  },
  {
    id: "R011",
    name: "其他类型违规行为",
    category: "其他",
    categoryTone: "other",
    description:
      "有明确违规事实且无法归入上述细类时使用，如内控缺失、妨碍检查、任职资格、资金违规委托等。",
    phrases: ["拒绝或妨碍监督检查", "任职资格未核准却履职", "保险资金违规委托"],
    colloquialMap: [{ oral: "其他违规兜底", standard: "其他类型违规行为" }],
    suggestion: "逐项排除已有细类后再归入本类，并写明违反的管理/监管要求。",
    icon: MoreHorizontal,
  },
];

export const RISK_NAME_MAP: Record<string, string> = Object.fromEntries(
  RISK_ATLAS.map((r) => [r.id, r.name]),
);

export function categoryToneClass(tone: RiskCategoryTone): {
  fill: string;
  ring: string;
  badge: string;
} {
  switch (tone) {
    case "sales":
      return {
        fill: "from-sky-600 to-cyan-500",
        ring: "stroke-sky-400",
        badge: "bg-sky-50 text-sky-800 ring-sky-200",
      };
    case "promo":
      return {
        fill: "from-violet-600 to-indigo-500",
        ring: "stroke-violet-400",
        badge: "bg-violet-50 text-violet-800 ring-violet-200",
      };
    case "finance":
      return {
        fill: "from-amber-600 to-orange-500",
        ring: "stroke-amber-400",
        badge: "bg-amber-50 text-amber-900 ring-amber-200",
      };
    case "consumer":
      return {
        fill: "from-teal-600 to-emerald-500",
        ring: "stroke-teal-400",
        badge: "bg-teal-50 text-teal-800 ring-teal-200",
      };
    case "ops":
      return {
        fill: "from-indigo-600 to-blue-500",
        ring: "stroke-indigo-400",
        badge: "bg-indigo-50 text-indigo-800 ring-indigo-200",
      };
    case "governance":
      return {
        fill: "from-slate-600 to-slate-500",
        ring: "stroke-slate-400",
        badge: "bg-slate-50 text-slate-800 ring-slate-200",
      };
    default:
      return {
        fill: "from-stone-600 to-stone-500",
        ring: "stroke-stone-400",
        badge: "bg-stone-50 text-stone-800 ring-stone-200",
      };
  }
}

/** @deprecated 保留兼容旧引用；颜色不再表示风险高低 */
export function heatTone(_heat?: string) {
  return categoryToneClass("sales");
}
