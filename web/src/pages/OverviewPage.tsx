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
import { RiskAtlasPanel } from "../components/RiskAtlasPanel";

const CAPABILITY_PILLS = ["多源文档解析", "BGE-M3 多通道召回", "max_merge · CE · listwise", "证据可追溯"];

const CORE_CAPABILITIES = [
  {
    title: "相似案例检索",
    body: "输入风险表述，经改写/HyDE 与 BGE-M3 召回、精排返回可解释的相似处罚案例、文号与处罚结果，支撑合规判断。",
    to: "/search",
    cta: "进入相似案例检索",
  },
  {
    title: "智能审查",
    body: "上传或粘贴营销材料，定位风险原句并高亮，匹配风险类型、命中案例与整改建议，支持人工复核。",
    to: "/review",
    cta: "开始智能审查",
  },
  {
    title: "风险标签字典",
    body: "以真实案例统计呈现赛题 R001–R011 粗类体系，查看定义、典型表达与关联案例入口。",
    to: "/#risk-dict",
    cta: "查看标签字典",
  },
];

const HERO_SLIDES = [
  {
    id: "brand",
    image: "/hero-pipeline.png",
    imageAlt: "处罚案例知识库处理链路示意",
    eyebrow: "保险监管处罚案例知识库",
    title: "案库",
    subtitle: "让每一条合规判断，都有案例依据",
    body: "从监管处罚文件中提取结构化案例，智能识别风险表述并匹配相似处罚依据，帮助合规人员快速形成可解释、可追溯的审查意见。",
  },
  {
    id: "promo",
    image: "/hero-ai-hub.png",
    imageAlt: "智能审查与风险分析能力示意",
    eyebrow: "保险监管处罚案例知识库",
    title: "案有所据，审有所依",
    subtitle: "相似案例检索 · 智能审查 · 风险标签一体贯通",
    body: "文档解析入库、BGE-M3 多通道召回与精排归因，支撑整篇材料审查与单句风险研判，沉淀可追溯审查意见。",
  },
] as const;

export function OverviewPage() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
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
      setHeroIdx((i) => (i + 1) % HERO_SLIDES.length);
    }, 7000);
    return () => window.clearInterval(id);
  }, []);

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
                to="/search"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white no-underline shadow-lg transition duration-200 hover:bg-primary-deep"
              >
                <Search className="h-4 w-4" aria-hidden />
                相似案例检索
              </Link>
              <Link
                to="/review"
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-primary/20 bg-white/80 px-5 py-2.5 text-sm font-semibold text-primary no-underline backdrop-blur-sm transition duration-200 hover:bg-white"
              >
                <ShieldCheck className="h-4 w-4" aria-hidden />
                智能审查
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

      {/* 核心能力介绍 */}
      <section className="surface rounded-3xl p-6 sm:p-8">
        <h2 className="font-display text-2xl font-semibold">核心能力</h2>
        <p className="mt-1 text-sm text-muted-fg">
          检索在前、审查在后：先找相似处罚依据，再对材料做可定位、可复核的合规审查。
        </p>
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {CORE_CAPABILITIES.map((cap) => (
            <div
              key={cap.title}
              className="flex flex-col rounded-2xl border border-border/70 bg-white/80 p-5"
            >
              <h3 className="font-display text-lg font-semibold">{cap.title}</h3>
              <p className="mt-2 flex-1 text-sm leading-relaxed text-muted-fg">{cap.body}</p>
              <Link
                to={cap.to}
                className="mt-4 inline-flex text-sm font-semibold text-primary no-underline hover:underline"
              >
                {cap.cta} →
              </Link>
            </div>
          ))}
        </div>
      </section>

      {error ? <ErrorAlert message={error} /> : null}
      {!stats && !error ? <LoadingBlock label="加载驾驶舱数据…" /> : null}

      {stats ? (
        <>
          <section className="stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard icon={FileStack} label="处罚文档" value={stats.documents} meta="入库文档总量" />
            <StatCard icon={Database} label="结构化案例" value={stats.cases} meta="已抽取案例总量" />
            <StatCard
              icon={ShieldCheck}
              label="保险相关案例"
              value={stats.insurance_cases}
              meta="真实筛选口径"
            />
            <StatCard
              icon={Sparkles}
              label="已向量化"
              value={stats.embedded_cases}
              meta="可供语义检索"
            />
          </section>

          <div id="risk-dict">
            <RiskAtlasPanel
              distribution={stats.tag_distribution}
              tagTree={stats.tag_tree}
              insuranceCases={stats.insurance_cases}
              pendingReviewCount={stats.pending_review_count}
              tagCoverageRate={stats.tag_coverage_rate}
              entityNormalizeRate={stats.entity_normalize_rate}
            />
          </div>

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
  meta: string;
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
