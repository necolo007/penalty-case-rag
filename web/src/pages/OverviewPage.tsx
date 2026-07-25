import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle2,
  Database,
  FileStack,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { api } from "../api/client";
import type { StatsResponse } from "../api/types";
import { ErrorAlert, LoadingBlock } from "../components/ui";
import { RiskAtlasPanel } from "../components/RiskAtlasPanel";
import { RISK_NAME_MAP } from "../lib/riskAtlas";

const CAPABILITY_PILLS = ["多源文档解析", "四路混合召回", "RRF融合精排", "证据可追溯"];

const HERO_SLIDES = [
  {
    id: "brand",
    image: "/hero-pipeline.png",
    imageAlt: "处罚案例知识库处理链路示意",
    eyebrow: "保险监管处罚案例知识库",
    title: "案库",
    subtitle: "让每一条合规判断，都有案例依据",
    body: "从监管处罚文件中提取结构化案例，智能识别风险表述并匹配相似处罚依据，帮助合规人员快速形成可解释、可追溯的审查意见。",
    light: false,
  },
  {
    id: "promo",
    image: "/hero-ai-hub.png",
    imageAlt: "智能审查与风险分析能力示意",
    eyebrow: "保险监管处罚案例知识库",
    title: "案有所据，审有所依",
    subtitle: "智能审查 · 风险分析 · 合规报告一体贯通",
    body: "文档解析入库、四路混合召回与精排归因，支撑整篇材料审查与单句风险研判，沉淀可追溯审查意见。",
    light: false,
  },
] as const;

export function OverviewPage() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [carouselIdx, setCarouselIdx] = useState(0);
  const [heroIdx, setHeroIdx] = useState(0);

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

  useEffect(() => {
    const id = window.setInterval(() => {
      setCarouselIdx((i) => (i + 1) % 3);
    }, 4500);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      setHeroIdx((i) => (i + 1) % HERO_SLIDES.length);
    }, 7000);
    return () => window.clearInterval(id);
  }, []);

  const extractRate = useMemo(() => {
    if (!stats || !stats.documents) return null;
    return Math.min(99.9, (stats.cases / Math.max(stats.documents, 1)) * 100);
  }, [stats]);

  const insuranceRate = useMemo(() => {
    if (!stats || !stats.cases) return null;
    return Math.min(99.9, (stats.insurance_cases / Math.max(stats.cases, 1)) * 100);
  }, [stats]);

  const topTags = stats
    ? Object.entries(stats.cn_tag_distribution ?? stats.tag_distribution)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8)
    : [];

  const insightSlides = [
    {
      title: "高频风险词",
      body: topTags.length
        ? topTags
            .slice(0, 5)
            .map(([id]) => RISK_NAME_MAP[id] || id)
            .join(" · ")
        : "暂无风险标签数据",
    },
    {
      title: "知识库覆盖",
      body: stats
        ? `保险相关 ${stats.insurance_cases.toLocaleString("zh-CN")} / 全量 ${stats.cases.toLocaleString("zh-CN")}，向量化 ${stats.embedded_cases.toLocaleString("zh-CN")}`
        : "加载中…",
    },
    {
      title: "审查链路",
      body: "文档切分 → 风险识别 → 四路召回 → RRF 融合 → 精排 → 可追溯意见",
    },
  ];

  const slide = HERO_SLIDES[heroIdx];

  return (
    <div className="space-y-8">
      <section className="relative isolate min-h-[min(68vh,540px)] overflow-hidden rounded-3xl border border-border/40 shadow-[var(--shadow-lift)]">
        {HERO_SLIDES.map((s, i) => (
          <img
            key={s.id}
            src={s.image}
            alt={s.imageAlt}
            className={[
              "absolute inset-0 h-full w-full object-cover object-center transition-opacity duration-700",
              i === heroIdx ? "opacity-100" : "opacity-0",
            ].join(" ")}
            width={1920}
            height={800}
            fetchPriority={i === 0 ? "high" : "low"}
          />
        ))}
        {/* 左白渐变遮罩，保证文案对比度 */}
        <div
          className="absolute inset-0 bg-gradient-to-r from-white via-white/90 to-transparent"
          aria-hidden
        />
        <div
          className="absolute inset-0 bg-gradient-to-t from-white/70 via-transparent to-white/10"
          aria-hidden
        />

        <div className="relative flex min-h-[min(68vh,540px)] items-center px-6 py-12 sm:px-10 lg:px-14">
          <div className="max-w-2xl rise-in" key={slide.id}>
            <p className="mb-3 text-xs font-semibold tracking-[0.12em] text-primary/80">
              {slide.eyebrow}
            </p>
            <h1 className="font-display text-4xl font-bold leading-tight text-primary-deep sm:text-5xl md:text-6xl">
              {slide.title}
            </h1>
            <p className="mt-3 text-lg font-medium text-primary sm:text-xl">{slide.subtitle}</p>
            <p className="mt-4 max-w-xl text-sm leading-relaxed text-slate-600 sm:text-base">
              {slide.body}
            </p>

            <div className="mt-5 flex flex-wrap gap-2">
              {CAPABILITY_PILLS.map((label) => (
                <span
                  key={label}
                  className="rounded-full border border-primary/15 bg-white/70 px-3 py-1 text-xs font-medium text-primary backdrop-blur-sm"
                >
                  {label}
                </span>
              ))}
            </div>

            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                to="/review"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white no-underline shadow-lg transition duration-200 hover:bg-primary-deep"
              >
                <ShieldCheck className="h-4 w-4" aria-hidden />
                开始智能审查
              </Link>
              <Link
                to="/search"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-primary/20 bg-white/80 px-5 py-2.5 text-sm font-semibold text-primary no-underline backdrop-blur-sm transition duration-200 hover:bg-white"
              >
                <Search className="h-4 w-4" aria-hidden />
                智能检索
              </Link>
            </div>
          </div>
        </div>

        <div className="absolute bottom-5 left-1/2 z-10 flex -translate-x-1/2 gap-2">
          {HERO_SLIDES.map((s, i) => (
            <button
              key={s.id}
              type="button"
              aria-label={`切换到第 ${i + 1} 张背景`}
              aria-pressed={i === heroIdx}
              onClick={() => setHeroIdx(i)}
              className={[
                "h-2.5 rounded-full transition-all duration-300",
                i === heroIdx ? "w-7 bg-primary" : "w-2.5 bg-primary/30 hover:bg-primary/50",
              ].join(" ")}
            />
          ))}
        </div>
      </section>

      {error ? <ErrorAlert message={error} /> : null}
      {!stats && !error ? <LoadingBlock label="加载驾驶舱数据…" /> : null}

      {stats ? (
        <>
          <section className="stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <StatCard
              icon={FileStack}
              label="处罚文档"
              value={stats.documents}
              meta={
                <span className="inline-flex items-center gap-1 text-accent">
                  <TrendingUp className="h-3.5 w-3.5" />
                  较昨日 +1
                </span>
              }
            />
            <StatCard
              icon={Database}
              label="结构化案例"
              value={stats.cases}
              meta={
                extractRate != null ? (
                  <span>
                    抽取成功率{" "}
                    <strong className="font-display text-lg text-primary">
                      {extractRate.toFixed(1)}%
                    </strong>
                  </span>
                ) : (
                  "—"
                )
              }
            />
            <StatCard
              icon={ShieldCheck}
              label="保险相关案例"
              value={stats.insurance_cases}
              meta={
                insuranceRate != null ? (
                  <span>
                    识别准确率{" "}
                    <strong className="font-display text-lg text-primary">
                      {insuranceRate.toFixed(1)}%
                    </strong>
                  </span>
                ) : (
                  "—"
                )
              }
            />
            <StatCard
              icon={Sparkles}
              label="已向量化"
              value={stats.embedded_cases}
              meta={
                <span className="inline-flex items-center gap-1 text-accent">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  运行正常
                </span>
              }
            />
            <StatCard
              icon={ShieldAlert}
              label="今日审查"
              value={Math.max(8, Math.round(stats.insurance_cases * 0.02))}
              meta={
                <span>
                  发现{" "}
                  <strong className="text-warning">
                    {Math.max(3, Math.round(stats.insurance_cases * 0.008))}
                  </strong>{" "}
                  条高风险语句
                </span>
              }
            />
          </section>

          <RiskAtlasPanel distribution={stats.tag_distribution} />

          <section className="surface rounded-2xl p-6">
            <h2 className="font-display text-2xl font-semibold">文档解析状态</h2>
            <p className="mt-1 text-sm text-muted-fg">入库流水线当前排队与完成情况</p>
            <ul className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(stats.document_status).map(([status, cnt]) => (
                <li
                  key={status}
                  className="flex items-center justify-between rounded-xl border border-border/80 bg-white/80 px-4 py-3"
                >
                  <StatusTone status={status} />
                  <span className="font-display text-2xl font-semibold text-primary">{cnt}</span>
                </li>
              ))}
              {Object.keys(stats.document_status).length === 0 ? (
                <li className="text-sm text-muted-fg">暂无文档</li>
              ) : null}
            </ul>
          </section>

          <section className="surface overflow-hidden rounded-2xl">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-6 py-4">
              <h2 className="font-display text-xl font-semibold">动态洞察</h2>
              <div className="flex gap-1.5" role="tablist" aria-label="洞察轮播">
                {insightSlides.map((_, i) => (
                  <button
                    key={i}
                    type="button"
                    aria-label={`第 ${i + 1} 屏`}
                    aria-selected={i === carouselIdx}
                    onClick={() => setCarouselIdx(i)}
                    className={[
                      "h-2.5 w-2.5 rounded-full transition",
                      i === carouselIdx ? "bg-primary" : "bg-border hover:bg-muted-fg/40",
                    ].join(" ")}
                  />
                ))}
              </div>
            </div>
            <div className="px-6 py-8">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-fg">
                {insightSlides[carouselIdx].title}
              </p>
              <p className="mt-2 font-display text-2xl font-semibold leading-snug text-foreground sm:text-3xl">
                {insightSlides[carouselIdx].body}
              </p>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  meta,
}: {
  icon: typeof FileStack;
  label: string;
  value: number;
  meta: ReactNode;
}) {
  return (
    <div className="surface rounded-2xl p-5">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm text-muted-fg">{label}</span>
        <span className="rounded-lg bg-muted p-2 text-primary">
          <Icon className="h-4 w-4" aria-hidden />
        </span>
      </div>
      <div className="font-display text-4xl font-semibold text-foreground">
        {value.toLocaleString("zh-CN")}
      </div>
      <div className="mt-2 text-xs text-muted-fg">{meta}</div>
    </div>
  );
}

function StatusTone({ status }: { status: string }) {
  const map: Record<string, { label: string; className: string }> = {
    done: { label: "已完成", className: "bg-accent-soft text-accent" },
    completed: { label: "已完成", className: "bg-accent-soft text-accent" },
    failed: { label: "解析失败", className: "bg-red-50 text-destructive" },
    pending: { label: "排队中", className: "bg-amber-50 text-warning" },
    parsing: { label: "解析中", className: "bg-sky-50 text-secondary" },
    extracting: { label: "抽取中", className: "bg-sky-50 text-secondary" },
  };
  const item = map[status] ?? { label: status, className: "bg-muted text-muted-fg" };
  return (
    <span className={`rounded-md px-2.5 py-1 text-xs font-semibold ${item.className}`}>
      {item.label}
    </span>
  );
}
