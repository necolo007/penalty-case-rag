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
      <section className="relative isolate min-h-[min(72vh,560px)] overflow-hidden rounded-3xl border border-border/50 shadow-[var(--shadow-lift)]">
        <img
          src="/hero-insurance-office.jpg"
          alt="保险业务办公场景：顾问与客户审阅保单与合规材料"
          className="absolute inset-0 h-full w-full object-cover object-[center_35%]"
          width={1920}
          height={1080}
          fetchPriority="high"
        />
        <div
          className="absolute inset-0 bg-gradient-to-r from-[#0c1a2e]/88 via-[#12253d]/55 to-transparent"
          aria-hidden
        />
        <div
          className="absolute inset-0 bg-gradient-to-t from-[#0c1a2e]/65 via-transparent to-black/10"
          aria-hidden
        />

        <div className="relative flex min-h-[min(72vh,560px)] items-end px-6 py-10 sm:px-10 sm:py-14">
          <div className="max-w-2xl rise-in rounded-2xl bg-[#0c1a2e]/25 p-1 backdrop-blur-[2px] sm:bg-transparent sm:p-0 sm:backdrop-blur-none">
            <p className="mb-3 text-xs font-semibold uppercase tracking-[0.22em] text-white/80 drop-shadow">
              Insurance Penalty Knowledge Base
            </p>
            <h1 className="font-display text-5xl font-bold leading-none text-white drop-shadow-md sm:text-6xl md:text-7xl">
              案库
            </h1>
            <p className="mt-5 max-w-xl text-base leading-relaxed text-white/95 drop-shadow sm:text-lg">
              面向保险监管合规场景的处罚案例检索与审查工作台。四路混合召回，可解释匹配，沉淀可追溯审查意见。
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                to="/search"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white no-underline shadow-lg transition duration-200 hover:brightness-110"
              >
                <Search className="h-4 w-4" aria-hidden />
                开始检索
              </Link>
              <Link
                to="/documents"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-white/35 bg-white/12 px-5 py-2.5 text-sm font-semibold text-white no-underline backdrop-blur-sm transition duration-200 hover:bg-white/22"
              >
                上传文档
              </Link>
            </div>
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
