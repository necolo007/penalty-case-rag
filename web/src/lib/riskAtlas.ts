import type { LucideIcon } from "lucide-react";
import {
  FileText,
  Gift,
  Megaphone,
  Shield,
  UserRound,
  Wallet,
  Building2,
  Scale,
} from "lucide-react";

/** 业务类别色（仅表示类别，不表示风险高低） */
export type RiskCategoryTone = "sales" | "promo" | "finance" | "consumer" | "governance";

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

/** 竞赛 R001–R008 知识卡内容（层级/案例数由 /stats.tag_tree 动态提供） */
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
    description:
      "向投保人提供保险合同约定以外的利益，以促进投保或影响投保决策。",
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
      "宣传材料、培训材料或产品说明存在虚假、夸大或引人误解的内容，损害消费者知情权。",
    phrases: ["行业第一、最高收益", "数据未经核实的对比宣传", "隐瞒关键限制条件"],
    colloquialMap: [
      { oral: "行业第一", standard: "宣传材料不真实 / 引人误解" },
    ],
    suggestion: "统一宣传口径审核，禁用无法证实的绝对化表述，保留可核验数据来源。",
    icon: FileText,
  },
  {
    id: "R004",
    name: "执业登记管理不规范",
    category: "销售合规",
    categoryTone: "sales",
    description:
      "销售人员未按规定执业登记、挂靠或跨区域展业，代理人管理不到位导致违规销售。",
    phrases: ["无资质人员展业", "挂靠展业", "超范围销售"],
    colloquialMap: [
      { oral: "挂靠展业", standard: "执业登记管理不规范" },
    ],
    suggestion: "核验执业登记与展业区域，禁止无资质人员销售，完善代理人台账。",
    icon: UserRound,
  },
  {
    id: "R005",
    name: "虚挂中介套取费用",
    category: "费用财务",
    categoryTone: "finance",
    description:
      "虚构或虚挂中介业务，通过虚假列支费用等方式套取资金，扰乱费用真实性。",
    phrases: ["虚构中介业务", "虚列费用套取资金", "虚假业务发票"],
    colloquialMap: [
      { oral: "走中介套费用", standard: "虚构中介业务套取费用" },
    ],
    suggestion: "核查中介业务真实性与费用凭证，杜绝虚挂套取，强化财务勾稽。",
    icon: Wallet,
  },
  {
    id: "R006",
    name: "编制虚假财务资料",
    category: "费用财务",
    categoryTone: "finance",
    description: "编制或提供虚假财务资料、报表或经营数据，影响监管判断与消费者权益。",
    phrases: ["虚假财务报表", "篡改经营数据", "隐瞒真实负债"],
    colloquialMap: [
      { oral: "做假账", standard: "编制虚假财务资料" },
    ],
    suggestion: "严格执行财务真实性要求，强化内审复核，禁止伪造变造资料。",
    icon: Building2,
  },
  {
    id: "R007",
    name: "消费者权益保护",
    category: "消费者权益",
    categoryTone: "consumer",
    description:
      "侵害消费者知情权、选择权或公平交易权，回访、理赔或售后环节存在不当行为。",
    phrases: ["回访误导", "拖延理赔", "强制搭售"],
    colloquialMap: [
      { oral: "回访走过场", standard: "未有效保护消费者知情权" },
    ],
    suggestion: "完善消保机制与投诉闭环，回访话术合规，理赔时效可追踪。",
    icon: Shield,
  },
  {
    id: "R008",
    name: "内部控制缺陷",
    category: "内控治理",
    categoryTone: "governance",
    description: "内控制度缺失或执行不力，导致合规风险未能及时识别、报告与处置。",
    phrases: ["内控失效", "制度形同虚设", "风险未及时报告"],
    colloquialMap: [
      { oral: "制度没落地", standard: "内部控制缺陷" },
    ],
    suggestion: "补强内控三道防线，明确岗位职责与问责，定期开展合规自查。",
    icon: Scale,
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
    default:
      return {
        fill: "from-slate-600 to-slate-500",
        ring: "stroke-slate-400",
        badge: "bg-slate-50 text-slate-800 ring-slate-200",
      };
  }
}

/** @deprecated 保留兼容旧引用；颜色不再表示风险高低 */
export function heatTone(_heat?: string) {
  return categoryToneClass("sales");
}
