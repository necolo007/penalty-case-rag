import { ExternalLink, FileText, Scale } from "lucide-react";
import { Link } from "react-router-dom";
import type { CaseResult } from "../api/types";
import {
  buildEvidenceRows,
  caseHeadline,
  differenceNote,
  extractRiskKeywords,
  highlightTerms,
  penaltyHighlight,
  relevancePercent,
  statusLabel,
} from "../lib/searchInsights";
import { truncate } from "../lib/format";
import { TagChip } from "./ui";

type Props = {
  item: CaseResult;
  userQuery: string;
  predictedCnTags?: string[];
};

function statusTone(status: string): string {
  if (status === "high") return "bg-accent-soft text-accent ring-accent/20";
  if (status === "partial") return "bg-amber-50 text-amber-800 ring-amber-200/80";
  return "bg-slate-100 text-slate-600 ring-slate-200";
}

export function SearchCaseDetailPanel({ item, userQuery, predictedCnTags = [] }: Props) {
  const rows = buildEvidenceRows(userQuery, item);
  const terms = extractRiskKeywords(userQuery, 6);
  const excerpt = item.violation_behavior || item.penalty_content || item.match_reason || "";
  const highlighted = highlightTerms(truncate(excerpt, 420), [
    ...terms,
    "约定以外",
    "其他利益",
    "保本",
    "收益",
  ]);
  const reviewPrefill = [userQuery, item.violation_behavior].filter(Boolean).join("\n").slice(0, 800);

  return (
    <article
      className="surface flex h-full min-h-0 flex-col overflow-hidden rounded-xl"
      aria-label="选中案例详情"
    >
      <header className="shrink-0 border-b border-border/70 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold text-muted-fg">
              #{item.rank} · 相关度 {relevancePercent(item.score).toFixed(1)}
            </p>
            <h2 className="mt-0.5 font-display text-lg font-semibold leading-snug text-foreground">
              {caseHeadline(item, 56)}
            </h2>
            <p className="mt-1 truncate text-xs text-muted-fg">
              {item.party_name || "未知当事人"}
              {item.regulator ? ` · ${item.regulator}` : ""}
            </p>
          </div>
          <div className="max-w-[12rem] rounded-lg border border-warning/25 bg-amber-50/80 px-2.5 py-1.5">
            <p className="text-[10px] font-semibold text-warning">处罚结果</p>
            <p className="mt-0.5 text-xs font-semibold leading-snug text-foreground">
              {truncate(penaltyHighlight(item), 64)}
            </p>
          </div>
        </div>
        {item.risk_tags.length || predictedCnTags.length ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {(predictedCnTags.length ? predictedCnTags : item.risk_tags).slice(0, 4).map((t) => (
              <TagChip key={t}>{t}</TagChip>
            ))}
          </div>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        <section>
          <h3 className="text-xs font-semibold text-foreground">为何匹配（证据对照）</h3>
          <div className="mt-2 overflow-x-auto rounded-lg border border-border/80">
            <table className="w-full min-w-[480px] text-left text-[11px]">
              <thead className="bg-muted/50 text-muted-fg">
                <tr>
                  <th className="px-2.5 py-2 font-semibold">查询要素</th>
                  <th className="px-2.5 py-2 font-semibold">案例证据摘录</th>
                  <th className="px-2.5 py-2 font-semibold">匹配</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.queryElement} className="border-t border-border/60 align-top">
                    <td className="px-2.5 py-2 font-medium text-foreground">{row.queryElement}</td>
                    <td className="px-2.5 py-2 leading-relaxed text-slate-700">{row.caseEvidence}</td>
                    <td className="px-2.5 py-2">
                      <span
                        className={`inline-flex rounded-md px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${statusTone(row.status)}`}
                      >
                        {statusLabel(row.status)}
                      </span>
                      <p className="mt-0.5 text-[10px] text-muted-fg">{row.note}</p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 rounded-lg border border-border/70 bg-slate-50/80 px-2.5 py-2 text-[11px] leading-relaxed text-slate-700">
            <span className="font-semibold text-foreground">差异说明：</span>
            {differenceNote(userQuery, item)}
          </p>
        </section>

        <section>
          <h3 className="text-xs font-semibold text-foreground">处罚原文摘录</h3>
          <div className="mt-1.5 rounded-lg border border-border/80 bg-white px-3 py-2 text-xs leading-relaxed text-slate-800">
            {highlighted.length ? (
              highlighted.map((p, i) =>
                p.hit ? (
                  <mark key={i} className="rounded bg-accent-soft px-0.5 text-foreground">
                    {p.text}
                  </mark>
                ) : (
                  <span key={i}>{p.text}</span>
                ),
              )
            ) : (
              <span className="text-muted-fg">暂无原文片段</span>
            )}
          </div>
        </section>
      </div>

      <footer className="flex shrink-0 flex-wrap items-center gap-2 border-t border-border/70 px-4 py-2.5">
        <Link
          to={`/cases/${encodeURIComponent(item.case_id)}`}
          className="inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-border bg-white px-3 text-xs font-semibold text-foreground no-underline transition hover:bg-muted"
        >
          <FileText className="h-3.5 w-3.5" aria-hidden />
          查看原文案例
          <ExternalLink className="h-3 w-3 text-muted-fg" aria-hidden />
        </Link>
        <Link
          to={`/review?prefill=${encodeURIComponent(reviewPrefill)}`}
          className="inline-flex min-h-10 items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-semibold text-white no-underline transition hover:brightness-95"
        >
          <Scale className="h-3.5 w-3.5" aria-hidden />
          加入审查报告
        </Link>
      </footer>
    </article>
  );
}
