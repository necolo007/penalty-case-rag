import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import type { CaseResult, CaseListItem } from "../api/types";
import { formatScore, truncate } from "../lib/format";
import { TagChip } from "./ui";

type CaseLike = CaseResult | CaseListItem;

function isResult(c: CaseLike): c is CaseResult {
  return "rank" in c && "score" in c;
}

export function CaseCard({ item }: { item: CaseLike }) {
  const id = item.case_id;
  const party = item.party_name || "未知当事人";
  const violation = item.violation_behavior;
  const tags = item.risk_tags ?? [];
  const regulator = item.regulator;

  return (
    <article className="surface group rounded-2xl p-5 transition duration-200 hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            {isResult(item) ? (
              <span className="rounded-md bg-primary px-2 py-0.5 text-xs font-semibold text-white">
                #{item.rank}
              </span>
            ) : null}
            <span className="font-mono text-xs text-muted-fg">{id}</span>
          </div>
          <h3 className="font-display text-xl font-semibold text-foreground">
            <Link
              to={`/cases/${encodeURIComponent(id)}`}
              className="text-inherit no-underline transition-colors hover:text-primary"
            >
              {party}
            </Link>
          </h3>
        </div>
        {isResult(item) ? (
          <div className="shrink-0 text-right">
            <div className="text-xs text-muted-fg">相关度</div>
            <div className="font-display text-2xl font-semibold text-primary">
              {formatScore(item.score)}
            </div>
          </div>
        ) : null}
      </div>

      <p className="mb-4 text-sm leading-relaxed text-slate-700">{truncate(violation, 220)}</p>

      <div className="mb-4 flex flex-wrap gap-1.5">
        {tags.slice(0, 6).map((t) => (
          <TagChip key={t}>{t}</TagChip>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/70 pt-3 text-xs text-muted-fg">
        <span>{regulator || "监管机构未知"}</span>
        {isResult(item) && item.channels?.length ? (
          <span>通道：{item.channels.join(" / ")}</span>
        ) : null}
        <Link
          to={`/cases/${encodeURIComponent(id)}`}
          className="inline-flex items-center gap-1 font-medium text-primary no-underline"
        >
          查看详情
          <ArrowUpRight className="h-3.5 w-3.5 transition group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
        </Link>
      </div>

      {isResult(item) && item.match_reason ? (
        <p className="mt-3 rounded-xl bg-muted/70 px-3 py-2 text-xs leading-relaxed text-slate-600">
          <span className="font-semibold text-primary">匹配理由：</span>
          {item.match_reason}
        </p>
      ) : null}
    </article>
  );
}
