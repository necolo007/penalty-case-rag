import { useState } from "react";
import { ChevronDown, Sparkles } from "lucide-react";
import { TagChip } from "./ui";
import {
  inferBehaviorElements,
  inferBusinessScene,
  inferRiskDescription,
  riskLabel,
} from "../lib/searchInsights";

type Props = {
  query: string;
  predictedRiskIds: string[];
  predictedCnTags?: string[];
};

export function SearchUnderstandingSummary({
  query,
  predictedRiskIds,
  predictedCnTags = [],
}: Props) {
  const [open, setOpen] = useState(false);
  const scene = inferBusinessScene(query);
  const behaviors = inferBehaviorElements(query);
  const riskDesc = inferRiskDescription(query);
  const tags =
    predictedCnTags.length > 0
      ? predictedCnTags.slice(0, 5)
      : predictedRiskIds.slice(0, 5).map(riskLabel);

  return (
    <section
      className="rise-in rounded-xl border border-border/70 bg-white/90 px-3 py-2 sm:px-4"
      aria-label="AI 查询理解"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex shrink-0 items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-primary" aria-hidden />
          <h2 className="text-xs font-semibold text-foreground">AI 查询理解</h2>
        </div>
        <dl className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <div className="inline-flex max-w-full items-baseline gap-1.5">
            <dt className="shrink-0 text-muted-fg">场景</dt>
            <dd className="truncate font-medium text-foreground">{scene}</dd>
          </div>
          <div className="inline-flex max-w-full items-baseline gap-1.5">
            <dt className="shrink-0 text-muted-fg">行为</dt>
            <dd className="truncate font-medium text-foreground">{behaviors.join("；")}</dd>
          </div>
          <div className="inline-flex max-w-full items-baseline gap-1.5">
            <dt className="shrink-0 text-muted-fg">风险</dt>
            <dd className="truncate font-medium text-foreground">{riskDesc}</dd>
          </div>
          <div className="inline-flex flex-wrap items-center gap-1.5">
            <dt className="shrink-0 text-muted-fg">标签</dt>
            <dd className="flex flex-wrap gap-1">
              {tags.length ? tags.slice(0, 4).map((t) => <TagChip key={t}>{t}</TagChip>) : (
                <span className="text-muted-fg">暂无</span>
              )}
            </dd>
          </div>
        </dl>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="inline-flex min-h-8 items-center gap-1 rounded-lg px-2 text-[11px] font-semibold text-muted-fg transition hover:bg-muted hover:text-foreground"
          aria-expanded={open}
        >
          {open ? "收起" : "详情"}
          <ChevronDown className={`h-3.5 w-3.5 transition ${open ? "rotate-180" : ""}`} aria-hidden />
        </button>
      </div>

      {open ? (
        <p className="mt-2 border-t border-border/60 pt-2 text-[11px] leading-relaxed text-slate-600">
          系统将查询拆解为场景、行为与风险要素后多路召回；标签来自分类模型，可用于核对检索方向是否偏离。
        </p>
      ) : null}
    </section>
  );
}
