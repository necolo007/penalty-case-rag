import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Database,
  FileStack,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { api } from "../api/client";
import type { StatsResponse } from "../api/types";
import { ErrorAlert, LoadingBlock } from "../components/ui";

export function OverviewPage() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .stats()
      .then((s) => {
        if (!cancelled) setStats(s);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const cards = stats
    ? [
        { label: "文档总数", value: stats.documents, icon: FileStack },
        { label: "案例总数", value: stats.cases, icon: Database },
        { label: "保险相关", value: stats.insurance_cases, icon: ShieldCheck },
        { label: "已向量化", value: stats.embedded_cases, icon: Sparkles },
      ]
    : [];

  const topTags = stats
    ? Object.entries(stats.tag_distribution)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8)
    : [];

  return (
    <div className="space-y-10">
      <section className="relative overflow-hidden rounded-3xl border border-border/70 bg-gradient-to-br from-primary via-primary to-primary-deep px-6 py-12 text-white shadow-[var(--shadow-lift)] sm:px-10 sm:py-16">
        <div
          className="pointer-events-none absolute inset-0 opacity-30"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.08) 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
          aria-hidden
        />
        <div className="relative max-w-3xl rise-in">
          <p className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-white/70">
            Insurance Penalty Knowledge Base
          </p>
          <h1 className="font-display text-4xl font-bold leading-tight sm:text-5xl">
            案库
          </h1>
          <p className="mt-4 max-w-xl text-base leading-relaxed text-white/85 sm:text-lg">
            面向保险监管合规场景的处罚案例检索与审查工作台。四路混合召回，可解释匹配，沉淀可追溯审查意见。
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              to="/search"
              className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white no-underline shadow-lg transition hover:brightness-110"
            >
              <Search className="h-4 w-4" aria-hidden />
              开始检索
            </Link>
            <Link
              to="/documents"
              className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-white/30 bg-white/10 px-5 py-2.5 text-sm font-semibold text-white no-underline backdrop-blur transition hover:bg-white/20"
            >
              上传文档
            </Link>
          </div>
        </div>
      </section>

      {error ? <ErrorAlert message={error} /> : null}
      {!stats && !error ? <LoadingBlock label="加载知识库统计…" /> : null}

      {stats ? (
        <>
          <section className="stagger grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {cards.map(({ label, value, icon: Icon }) => (
              <div key={label} className="surface rounded-2xl p-5">
                <div className="mb-4 flex items-center justify-between">
                  <span className="text-sm text-muted-fg">{label}</span>
                  <span className="rounded-lg bg-muted p-2 text-primary">
                    <Icon className="h-4 w-4" aria-hidden />
                  </span>
                </div>
                <div className="font-display text-4xl font-semibold text-foreground">
                  {value.toLocaleString("zh-CN")}
                </div>
              </div>
            ))}
          </section>

          <section className="grid gap-6 lg:grid-cols-2">
            <div className="surface rounded-2xl p-6">
              <h2 className="font-display text-2xl font-semibold">风险标签分布</h2>
              <p className="mt-1 text-sm text-muted-fg">保险相关案例的风险类型 Top 标签</p>
              <ul className="mt-5 space-y-3">
                {topTags.length === 0 ? (
                  <li className="text-sm text-muted-fg">暂无标签统计</li>
                ) : (
                  topTags.map(([id, cnt]) => {
                    const max = topTags[0]?.[1] || 1;
                    const pct = Math.round((cnt / max) * 100);
                    return (
                      <li key={id}>
                        <div className="mb-1 flex justify-between text-sm">
                          <span className="font-medium text-foreground">{id}</span>
                          <span className="text-muted-fg">{cnt}</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-primary to-secondary transition-all duration-500"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </li>
                    );
                  })
                )}
              </ul>
            </div>

            <div className="surface rounded-2xl p-6">
              <h2 className="font-display text-2xl font-semibold">文档解析状态</h2>
              <p className="mt-1 text-sm text-muted-fg">入库流水线当前排队与完成情况</p>
              <ul className="mt-5 grid gap-3 sm:grid-cols-2">
                {Object.entries(stats.document_status).map(([status, cnt]) => (
                  <li
                    key={status}
                    className="rounded-xl border border-border/80 bg-white/70 px-4 py-3"
                  >
                    <div className="text-xs uppercase tracking-wide text-muted-fg">{status}</div>
                    <div className="mt-1 font-display text-3xl font-semibold text-primary">
                      {cnt}
                    </div>
                  </li>
                ))}
                {Object.keys(stats.document_status).length === 0 ? (
                  <li className="text-sm text-muted-fg">暂无文档</li>
                ) : null}
              </ul>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
