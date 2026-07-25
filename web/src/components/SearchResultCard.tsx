import { useState } from "react";
import { ChevronDown, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import type { CaseResult } from "../api/types";
import {
  deriveScoreBreakdown,
  expandQueryTerms,
  parseMatchReason,
  riskLabel,
  riskLevelFromScore,
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

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-muted-fg">{label}</span>
        <span className="font-semibold tabular-nums text-foreground">{value.toFixed(1)}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-300 motion-reduce:transition-none"
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}

export function SearchResultCard({
  item,
  userQuery,
  rewrittenQuery,
  predictedRiskIds,
  predictedCnTags = [],
  onSearchExpanded,
}: Props) {
  const [scoreOpen, setScoreOpen] = useState(false);
  const [queryOpen, setQueryOpen] = useState(false);

  const breakdown = deriveScoreBreakdown(item, predictedRiskIds, predictedCnTags);
  const riskLevel = riskLevelFromScore(item.score);
  const match = parseMatchReason(item.match_reason, userQuery);
  const riskTypes = [
    ...new Set([
      ...(predictedCnTags.length ? predictedCnTags : predictedRiskIds.map(riskLabel)),
      ...item.risk_tags.slice(0, 3),
    ]),
  ].slice(0, 4);

  const evidence =
    truncate(item.penalty_content || item.violation_behavior, 180) ||
    "暂无处罚原文摘录";
  const source = item.penalty_doc_no || item.regulator || "监管处罚决定书";
  const expandedTerms = expandQueryTerms(userQuery, rewrittenQuery);

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
            </div>
            <h3 className="font-display text-xl font-semibold text-foreground">
              <Link
                to={`/cases/${encodeURIComponent(item.case_id)}`}
                className="text-inherit no-underline transition-colors hover:text-primary"
              >
                {item.party_name || "未知当事人"}
              </Link>
            </h3>
          </div>

          <button
            type="button"
            onClick={() => setScoreOpen((o) => !o)}
            className="shrink-0 rounded-xl border border-border bg-white px-3 py-2 text-left transition hover:border-primary/40 hover:bg-primary/5"
            aria-expanded={scoreOpen}
          >
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-muted-fg">综合匹配度</span>
              <ChevronDown
                className={`h-3.5 w-3.5 text-muted-fg transition ${scoreOpen ? "rotate-180" : ""}`}
                aria-hidden
              />
            </div>
            <p className="font-display text-2xl font-bold tabular-nums text-primary">
              {breakdown.overall.toFixed(1)}%
            </p>
          </button>
        </div>

        {scoreOpen ? (
          <div className="mt-4 grid gap-3 rounded-xl bg-muted/50 p-4 sm:grid-cols-2">
            <ScoreBar label="语义相似" value={breakdown.semantic} />
            <ScoreBar label="风险标签匹配" value={breakdown.tagMatch} />
            <ScoreBar label="业务场景匹配" value={breakdown.sceneMatch} />
            <ScoreBar label="处罚依据匹配" value={breakdown.legalMatch} />
            <p className="sm:col-span-2 text-[11px] leading-relaxed text-muted-fg">
              综合匹配度由多路召回通道（BM25 / 向量 / 标签 / 规则）交叉验证后经 RRF 融合与精排得出，便于评委复核可解释性。
            </p>
          </div>
        ) : null}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ${riskLevel.tone}`}>
            风险等级：{riskLevel.label}
          </span>
          <span className="text-xs text-muted-fg">
            风险类型：{riskTypes.join("；") || "—"}
          </span>
        </div>
      </header>

      <div className="space-y-4 px-5 py-4 sm:px-6">
        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-fg">命中原因</h4>
          <dl className="mt-2 space-y-2 text-sm">
            <div className="rounded-xl border border-border/70 bg-slate-50/80 px-3 py-2.5">
              <dt className="text-[11px] font-semibold text-primary">系统识别 · 用户输入</dt>
              <dd className="mt-1 text-foreground">「{match.userInput}」</dd>
            </div>
            <div className="rounded-xl border border-border/70 bg-slate-50/80 px-3 py-2.5">
              <dt className="text-[11px] font-semibold text-primary">案例行为</dt>
              <dd className="mt-1 text-slate-700">{match.caseBehavior}</dd>
            </div>
          </dl>
          <ul className="mt-2 flex flex-wrap gap-2">
            {match.checks.map((c) => (
              <li
                key={c}
                className="inline-flex items-center gap-1 rounded-md bg-accent-soft px-2 py-1 text-[11px] font-medium text-accent"
              >
                <span aria-hidden>✓</span> {c}
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-fg">原文证据</h4>
          <blockquote className="mt-2 border-l-2 border-primary/40 pl-3 text-sm leading-relaxed text-slate-700">
            处罚原文：「{evidence}」
          </blockquote>
          <p className="mt-2 text-xs text-muted-fg">
            来源：{source}
            {item.regulator ? ` · ${item.regulator}` : ""}
          </p>
          <Link
            to={`/cases/${encodeURIComponent(item.case_id)}`}
            className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-primary no-underline hover:underline"
          >
            查看原文
            <ExternalLink className="h-3 w-3" aria-hidden />
          </Link>
        </section>

        <section className="rounded-xl border border-dashed border-border bg-white/60">
          <button
            type="button"
            onClick={() => setQueryOpen((o) => !o)}
            className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
            aria-expanded={queryOpen}
          >
            <span className="text-sm font-semibold text-foreground">AI 理解后的查询</span>
            <ChevronDown
              className={`h-4 w-4 shrink-0 text-muted-fg transition ${queryOpen ? "rotate-180" : ""}`}
              aria-hidden
            />
          </button>
          {queryOpen ? (
            <div className="space-y-3 border-t border-border/70 px-4 py-3 text-sm">
              <div>
                <p className="text-[11px] font-semibold text-muted-fg">用户输入</p>
                <p className="mt-1 text-foreground">{userQuery}</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold text-muted-fg">系统扩展</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {expandedTerms.map((t) => (
                    <TagChip key={t}>{t}</TagChip>
                  ))}
                </div>
                {rewrittenQuery ? (
                  <p className="mt-2 text-xs leading-relaxed text-slate-600">
                    改写查询：{rewrittenQuery}
                  </p>
                ) : null}
              </div>
              {onSearchExpanded && rewrittenQuery ? (
                <button
                  type="button"
                  onClick={() => onSearchExpanded(rewrittenQuery)}
                  className="text-xs font-semibold text-primary underline-offset-2 hover:underline"
                >
                  基于扩展语义检索相关处罚案例
                </button>
              ) : null}
            </div>
          ) : null}
        </section>
      </div>

      <footer className="flex flex-wrap items-center gap-2 border-t border-border/70 px-5 py-3 text-xs text-muted-fg sm:px-6">
        {item.channels?.length ? <span>召回通道：{item.channels.join(" / ")}</span> : null}
        <div className="ml-auto flex flex-wrap gap-1">
          {item.risk_tags.slice(0, 4).map((t) => (
            <TagChip key={t}>{t}</TagChip>
          ))}
        </div>
      </footer>
    </article>
  );
}
