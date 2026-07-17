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

export type RiskHeat = "hot" | "rising" | "stable" | "cool";

export interface RiskMeta {
  id: string;
  name: string;
  category: string;
  description: string;
  scenes: string[];
  phrases: string[];
  suggestion: string;
  heat: RiskHeat;
  /** 近30天相对增幅示意（UI 展示，无后端时按占比推算） */
  trendHint: number;
  icon: LucideIcon;
}

/** 竞赛 R001–R008 + 文档推荐展示名 */
export const RISK_ATLAS: RiskMeta[] = [
  {
    id: "R001",
    name: "销售误导",
    category: "销售合规类",
    description:
      "在保险销售过程中对产品进行误导性陈述，夸大收益、弱化风险或隐瞒重要信息，欺骗投保人、被保险人或受益人。",
    scenes: ["营销宣传", "销售话术", "产品说明会"],
    phrases: [
      "本产品稳赚不赔、保证收益",
      "收益远超银行存款",
      "风险极低几乎没有风险",
    ],
    suggestion: "删除绝对化收益承诺，完整披露风险与除外责任，权益以合同约定为准。",
    heat: "hot",
    trendHint: 0.14,
    icon: Megaphone,
  },
  {
    id: "R002",
    name: "合同外利益",
    category: "销售合规类",
    description:
      "以返佣、赠礼、补贴、体检卡、加油卡等方式诱导投保，属于保险合同约定以外的利益输送行为。",
    scenes: ["营销宣传", "销售话术", "增值服务推介"],
    phrases: [
      "购买本产品即可赠送体检卡",
      "投保可领取礼品补贴",
      "客户投保后可获加油卡",
      "签单即送增值权益",
    ],
    suggestion: "删除赠礼诱导表述，明确增值服务范围，不以合同外利益吸引投保。",
    heat: "rising",
    trendHint: 0.128,
    icon: Gift,
  },
  {
    id: "R003",
    name: "宣传材料不真实",
    category: "宣传材料类",
    description:
      "宣传材料、培训材料或产品说明存在虚假、夸大或引人误解的内容，损害消费者知情权。",
    scenes: ["产品宣传册", "培训材料", "线上广告"],
    phrases: [
      "行业第一、最高收益",
      "数据未经核实的对比宣传",
      "隐瞒关键限制条件",
    ],
    suggestion: "统一宣传口径审核，禁用无法证实的绝对化表述，保留可核验数据来源。",
    heat: "rising",
    trendHint: 0.09,
    icon: FileText,
  },
  {
    id: "R004",
    name: "执业登记管理不规范",
    category: "销售合规类",
    description:
      "销售人员未按规定执业登记、挂靠或跨区域展业，代理人管理不到位导致违规销售。",
    scenes: ["代理人管理", "渠道展业", "人员合规"],
    phrases: ["无资质人员展业", "挂靠展业", "超范围销售"],
    suggestion: "核验执业登记与展业区域，禁止无资质人员销售，完善代理人台账。",
    heat: "stable",
    trendHint: 0.03,
    icon: UserRound,
  },
  {
    id: "R005",
    name: "虚挂中介套取费用",
    category: "财务费用类",
    description:
      "虚构或虚挂中介业务，通过虚假列支费用等方式套取资金，扰乱费用真实性。",
    scenes: ["中介合作", "费用列支", "财务核算"],
    phrases: ["虚构中介业务", "虚列费用套取资金", "虚假业务发票"],
    suggestion: "核查中介业务真实性与费用凭证，杜绝虚挂套取，强化财务勾稽。",
    heat: "hot",
    trendHint: 0.11,
    icon: Wallet,
  },
  {
    id: "R006",
    name: "编制虚假财务资料",
    category: "财务费用类",
    description: "编制或提供虚假财务资料、报表或经营数据，影响监管判断与消费者权益。",
    scenes: ["财务报告", "信息披露", "内部审计"],
    phrases: ["虚假财务报表", "篡改经营数据", "隐瞒真实负债"],
    suggestion: "严格执行财务真实性要求，强化内审复核，禁止伪造变造资料。",
    heat: "cool",
    trendHint: -0.04,
    icon: Building2,
  },
  {
    id: "R007",
    name: "消费者权益保护",
    category: "消费者权益类",
    description:
      "侵害消费者知情权、选择权或公平交易权，回访、理赔或售后环节存在不当行为。",
    scenes: ["客户回访", "理赔服务", "投诉处理"],
    phrases: ["回访误导", "拖延理赔", "强制搭售"],
    suggestion: "完善消保机制与投诉闭环，回访话术合规，理赔时效可追踪。",
    heat: "stable",
    trendHint: 0.02,
    icon: Shield,
  },
  {
    id: "R008",
    name: "内部控制缺陷",
    category: "内控治理类",
    description: "内控制度缺失或执行不力，导致合规风险未能及时识别、报告与处置。",
    scenes: ["内控合规", "制度执行", "风险管理"],
    phrases: ["内控失效", "制度形同虚设", "风险未及时报告"],
    suggestion: "补强内控三道防线，明确岗位职责与问责，定期开展合规自查。",
    heat: "cool",
    trendHint: -0.02,
    icon: Scale,
  },
];

export const RISK_NAME_MAP: Record<string, string> = Object.fromEntries(
  RISK_ATLAS.map((r) => [r.id, r.name]),
);

export function heatTone(heat: RiskHeat): {
  fill: string;
  ring: string;
  label: string;
  badge: string;
} {
  switch (heat) {
    case "hot":
      return {
        fill: "from-red-600 to-rose-500",
        ring: "stroke-red-400",
        label: "高风险重点关注",
        badge: "bg-red-50 text-red-700 ring-red-200",
      };
    case "rising":
      return {
        fill: "from-amber-500 to-orange-500",
        ring: "stroke-amber-400",
        label: "近期快速上升",
        badge: "bg-amber-50 text-amber-800 ring-amber-200",
      };
    case "cool":
      return {
        fill: "from-emerald-600 to-teal-500",
        ring: "stroke-emerald-400",
        label: "下降或稳定",
        badge: "bg-emerald-50 text-emerald-800 ring-emerald-200",
      };
    default:
      return {
        fill: "from-primary to-secondary",
        ring: "stroke-sky-300",
        label: "常规高频",
        badge: "bg-sky-50 text-sky-800 ring-sky-200",
      };
  }
}
