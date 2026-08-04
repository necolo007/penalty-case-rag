import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import type { CaseResult } from "../api/types";
import {
  parseMatchFacts,
  penaltyHighlight,
  relevancePercent,
  riskLabel,
} from "../lib/searchInsights";
import { truncate } from "../lib/format";
import { TagChip } from "./ui";

type Props = {
  item: CaseResult;
  userQuery: string;
  rewrittenQuery: string;
  predictedRiskIds: string[];
  predictedCnTags?: string[];
  onSearchExpanded?: (query: string) => void;
};

export function SearchResultCard({
  item,
  predictedRiskIds,
  predictedCnTags = [],
}: Props) {
  const pct = relevancePercent(item.score);
  const facts = parseMatchFacts(item.match_reason);
  const riskTypes = [
    ...new Set([
      ...(predictedCnTags.length ? predictedCnTags : predictedRiskIds.map(riskLabel)),
      ...item.risk_tags.slice(0, 3),
    ]),
  ].slice(0, 4);

  const penalty = truncate(penaltyHighlight(item), 160);
  const violation = truncate(item.violation_behavior || "", 120);

  return (
    <article className="surface overflow-hidden rounded-2xl transition duration-200 hover:shadow-[var(--shadow-lift)]">
      <header className="border-b border-border/70 px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-primary px-2 py-0.5 text-xs font-semibold text-white">
                #{item.rank}
              </span>
              <span className="font-mono text-xs text-muted-fg">{item.case_id}</span>
              {item.penalty_doc_no ? (
                <span className="text-xs text-muted-fg">{item.penalty_doc_no}</span>
              ) : null}
            </div>
            <h3 className="font-display text-xl font-semibold text-foreground">
              <Link
                to={`/cases/${encodeURIComponent(item.case_id)}`}
                className="text-inherit no-underline transition-colors hover:text-primary"
              >
                {item.party_name || "未知当事人"}
              </Link>
            </h3>
            {item.regulator ? (
              <p className="mt-1 text-xs text-muted-fg">{item.regulator}</p>
            ) : null}
          </div>

          <div className="shrink-0 rounded-xl border border-border bg-white px-3 py-2 text-right">
            <p className="text-[11px] text-muted-fg">相关度</p>
            <p className="font-display text-2xl font-bold tabular-nums text-primary">
              {pct.toFixed(1)}%
            </p>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-fg">
            风险类型：{riskTypes.join("；") || "—"}
          </span>
        </div>
      </header>

      <div className="space-y-4 px-5 py-4 sm:px-6">
        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-fg">
            处罚结果
          </h4>
          <p className="mt-2 text-sm leading-relaxed text-foreground">{penalty}</p>
        </section>

        {violation ? (
          <section>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-fg">
              违法事实摘要
            </h4>
            <p className="mt-2 text-sm leading-relaxed text-slate-700">{violation}</p>
          </section>
        ) : null}

        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-fg">
            为何相关
          </h4>
          {facts.length ? (
            <ul className="mt-2 space-y-1.5">
              {facts.map((f) => (
                <li
                  key={f}
                  className="rounded-lg border border-border/70 bg-slate-50/80 px-3 py-2 text-sm text-slate-800"
                >
                  {f}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted-fg">
              {item.match_reason || "暂无更细的命中证据，请查看案例原文核对。"}
            </p>
          )}
        </section>

        <Link
          to={`/cases/${encodeURIComponent(item.case_id)}`}
          className="inline-flex items-center gap-1 text-xs font-semibold text-primary no-underline hover:underline"
        >
          查看完整案例
          <ExternalLink className="h-3 w-3" aria-hidden />
        </Link>
      </div>

      {item.risk_tags.length ? (
        <footer className="flex flex-wrap gap-1 border-t border-border/70 px-5 py-3 sm:px-6">
          {item.risk_tags.slice(0, 4).map((t) => (
            <TagChip key={t}>{t}</TagChip>
          ))}
        </footer>
      ) : null}
    </article>
  );
}
