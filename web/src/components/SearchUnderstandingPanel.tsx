import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import {
  extractRiskKeywords,
  inferBusinessScene,
  riskLabel,
} from "../lib/searchInsights";

type Step = {
  id: string;
  label: string;
  detail: string;
};

type Props = {
  active: boolean;
  query: string;
  predictedRiskIds: string[];
  predictedCnTags?: string[];
  resultCount: number | null;
  topK: number;
  finished: boolean;
};

function buildSteps(
  query: string,
  predictedRiskIds: string[],
  predictedCnTags: string[],
  resultCount: number | null,
  topK: number,
): Step[] {
  const scene = inferBusinessScene(query);
  const keywords = extractRiskKeywords(query);
  const risks =
    predictedCnTags.length > 0
      ? predictedCnTags.slice(0, 3).join(" · ")
      : predictedRiskIds.length > 0
        ? predictedRiskIds.slice(0, 3).map(riskLabel).join(" · ")
        : "合同外利益 · 销售误导 · 承诺收益";
  const pool = resultCount != null ? `${resultCount} 条相关案例` : "检索候选池";
  const top = Math.min(topK, resultCount ?? topK);

  return [
    { id: "scene", label: "识别业务场景", detail: scene },
    {
      id: "kw",
      label: "提取风险关键词",
      detail: keywords.length ? keywords.join(" · ") : "语义特征抽取中",
    },
    { id: "risk", label: "匹配风险类型（27类）", detail: risks },
    { id: "pool", label: "检索历史案例", detail: pool },
    { id: "rank", label: "精排完成", detail: `Top ${top} 结果` },
  ];
}

export function SearchUnderstandingPanel({
  active,
  query,
  predictedRiskIds,
  predictedCnTags = [],
  resultCount,
  topK,
  finished,
}: Props) {
  const steps = buildSteps(query, predictedRiskIds, predictedCnTags, resultCount, topK);
  const [visible, setVisible] = useState(0);

  useEffect(() => {
    if (!active) {
      setVisible(0);
      return;
    }
    setVisible(0);
    const timer = window.setInterval(() => {
      setVisible((v) => {
        if (v >= steps.length - 1) {
          window.clearInterval(timer);
          return steps.length - 1;
        }
        return v + 1;
      });
    }, 520);
    return () => window.clearInterval(timer);
  }, [active, query, steps.length]);

  if (!active && !finished) return null;

  return (
    <section
      className="surface rise-in rounded-2xl border border-primary/15 p-5 sm:p-6"
      aria-live="polite"
      aria-label="智能理解过程"
    >
      <div className="mb-4 flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
          {finished ? <Check className="h-4 w-4" aria-hidden /> : <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
        </span>
        <div>
          <h2 className="font-display text-lg font-semibold text-foreground">智能理解过程</h2>
          <p className="text-xs text-muted-fg">
            {finished ? "已完成语义解析与多路召回" : "正在解析输入并匹配监管案例…"}
          </p>
        </div>
      </div>

      <ol className="space-y-2.5">
        {steps.map((step, idx) => {
          const done = finished || idx < visible;
          const current = !finished && idx === visible;
          return (
            <li
              key={step.id}
              className={`flex items-start gap-3 rounded-xl px-3 py-2.5 transition ${
                current ? "bg-primary/5 ring-1 ring-primary/15" : done ? "opacity-100" : "opacity-40"
              }`}
            >
              <span
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                  done ? "bg-accent text-white" : "bg-muted text-muted-fg"
                }`}
                aria-hidden
              >
                {done ? "✓" : idx + 1}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-foreground">{step.label}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-slate-600">{step.detail}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
