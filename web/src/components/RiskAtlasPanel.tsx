import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Search,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { api } from "../api/client";
import type { CaseListItem } from "../api/types";
import { RISK_ATLAS, heatTone, type RiskMeta } from "../lib/riskAtlas";

type TimeRange = "30d" | "180d" | "365d" | "all";
type MetricMode = "count" | "growth" | "share";

const TIME_OPTIONS: { id: TimeRange; label: string }[] = [
  { id: "30d", label: "近30天" },
  { id: "180d", label: "近半年" },
  { id: "365d", label: "近一年" },
  { id: "all", label: "全部" },
];

const METRIC_OPTIONS: { id: MetricMode; label: string }[] = [
  { id: "count", label: "案例数量" },
  { id: "growth", label: "近期增幅" },
  { id: "share", label: "高风险占比" },
];

type Props = {
  distribution: Record<string, number>;
};

export function RiskAtlasPanel({ distribution }: Props) {
  const items = useMemo(() => {
    return RISK_ATLAS.map((meta) => ({
      meta,
      count: distribution[meta.id] ?? 0,
    }))
      .filter((x) => x.count > 0 || Object.keys(distribution).length === 0)
      .sort((a, b) => b.count - a.count);
  }, [distribution]);

  const displayItems = items.length
    ? items
    : RISK_ATLAS.map((meta) => ({ meta, count: 0 }));

  const maxCount = Math.max(1, ...displayItems.map((i) => i.count));
  const total = displayItems.reduce((s, i) => s + i.count, 0) || 1;

  const defaultId =
    displayItems.find((i) => i.meta.id === "R001")?.meta.id ||
    displayItems.find((i) => i.meta.id === "R002")?.meta.id ||
    displayItems[0]?.meta.id ||
    "R001";

  const [selectedId, setSelectedId] = useState(defaultId);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>("365d");
  const [metric, setMetric] = useState<MetricMode>("count");
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [loadingCases, setLoadingCases] = useState(false);

  useEffect(() => {
    if (!displayItems.some((i) => i.meta.id === selectedId) && displayItems[0]) {
      setSelectedId(displayItems[0].meta.id);
    }
  }, [displayItems, selectedId]);

  const selected = displayItems.find((i) => i.meta.id === selectedId) ?? displayItems[0];
  const selectedMeta = selected?.meta;

  useEffect(() => {
    if (!selectedMeta) return;
    let cancelled = false;
    setLoadingCases(true);
    api
      .listCases({
        page: 1,
        page_size: 3,
        risk_type: selectedMeta.id,
        is_insurance_related: true,
      })
      .then((res) => {
        if (!cancelled) setCases(res.items);
      })
      .catch(() => {
        if (!cancelled) setCases([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingCases(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedMeta?.id]);

  // 星系布局：中心最大，周围按角度排布
  const nodes = useMemo(() => {
    const sorted = [...displayItems].sort((a, b) => b.count - a.count);
    return sorted.map((item, i) => {
      if (i === 0) {
        return { ...item, x: 50, y: 48, isCenter: true as const };
      }
      const n = sorted.length - 1;
      const angle = ((i - 1) / Math.max(n, 1)) * Math.PI * 2 - Math.PI / 2;
      const radius = 28 + (i % 3) * 4;
      return {
        ...item,
        x: 50 + Math.cos(angle) * radius,
        y: 48 + Math.sin(angle) * radius,
        isCenter: false as const,
      };
    });
  }, [displayItems]);

  function bubbleSize(count: number, isCenter: boolean) {
    const ratio = count / maxCount;
    const base = isCenter ? 92 : 62;
    return base + ratio * (isCenter ? 42 : 48);
  }

  function metricValue(meta: RiskMeta, count: number) {
    if (metric === "growth") {
      const pct = Math.round(meta.trendHint * 1000) / 10;
      return `${pct > 0 ? "+" : ""}${pct}%`;
    }
    if (metric === "share") {
      return `${((count / total) * 100).toFixed(1)}%`;
    }
    return count.toLocaleString("zh-CN");
  }

  if (!selectedMeta || !selected) {
    return (
      <div className="surface rounded-2xl p-8 text-center text-sm text-muted-fg">
        暂无风险分布数据
      </div>
    );
  }

  const tone = heatTone(selectedMeta.heat);
  const recentNew = Math.max(0, Math.round(selected.count * Math.abs(selectedMeta.trendHint)));
  const highRiskShare = Math.min(68, Math.round(22 + selected.count / maxCount * 28));

  return (
    <section className="surface overflow-hidden rounded-3xl">
      {/* 标题 + 筛选 */}
      <div className="flex flex-col gap-4 border-b border-border/70 px-5 py-5 sm:flex-row sm:items-start sm:justify-between sm:px-6">
        <div>
          <h2 className="font-display text-2xl font-semibold sm:text-3xl">
            保险监管处罚风险版图
          </h2>
          <p className="mt-1 max-w-xl text-sm text-muted-fg">
            基于已入库处罚案例，展示高频风险类型、变化趋势与典型业务场景。
          </p>
        </div>
        <div className="flex flex-wrap gap-2" role="group" aria-label="版图筛选">
          {TIME_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              aria-pressed={timeRange === opt.id}
              onClick={() => setTimeRange(opt.id)}
              className={[
                "min-h-9 rounded-full px-3 text-xs font-semibold transition",
                timeRange === opt.id
                  ? "bg-primary text-white"
                  : "border border-border bg-white text-muted-fg hover:border-primary/40 hover:text-primary",
              ].join(" ")}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-border/50 px-5 py-3 sm:px-6">
        <span className="self-center text-xs text-muted-fg">展示指标</span>
        {METRIC_OPTIONS.map((opt) => (
          <button
            key={opt.id}
            type="button"
            aria-pressed={metric === opt.id}
            onClick={() => setMetric(opt.id)}
            className={[
              "min-h-9 rounded-lg px-3 text-xs font-medium transition",
              metric === opt.id
                ? "bg-muted text-primary ring-1 ring-primary/20"
                : "text-muted-fg hover:bg-muted/70",
            ].join(" ")}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <div className="grid lg:grid-cols-12">
        {/* 左侧气泡版图 — 主视觉占约 2/3 */}
        <div className="relative border-b border-border/70 p-4 sm:p-5 lg:col-span-8 lg:border-b-0 lg:border-r lg:p-6">
          <div
            className="relative mx-auto h-[min(56vh,520px)] w-full overflow-hidden rounded-2xl bg-[radial-gradient(ellipse_at_center,_#eef4fb_0%,_#f8fafc_55%,_#e8eef5_100%)]"
            role="list"
            aria-label="风险类型气泡版图"
          >
            {/* 连线 */}
            <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
              {nodes
                .filter((n) => !n.isCenter)
                .map((n) => (
                  <line
                    key={`line-${n.meta.id}`}
                    x1="50%"
                    y1="48%"
                    x2={`${n.x}%`}
                    y2={`${n.y}%`}
                    className={[
                      "transition duration-300",
                      hoveredId && hoveredId !== n.meta.id && hoveredId !== nodes[0]?.meta.id
                        ? "stroke-slate-200/40"
                        : selectedId === n.meta.id || hoveredId === n.meta.id
                          ? "stroke-primary/50"
                          : "stroke-slate-300/70",
                    ].join(" ")}
                    strokeWidth="1.5"
                    strokeDasharray="4 4"
                  />
                ))}
            </svg>

            {nodes.map((node) => {
              const size = bubbleSize(node.count, node.isCenter);
              const ht = heatTone(node.meta.heat);
              const active = selectedId === node.meta.id;
              const dim =
                hoveredId != null && hoveredId !== node.meta.id && selectedId !== node.meta.id;
              const Icon = node.meta.icon;
              const ringPct = Math.min(95, 35 + Math.abs(node.meta.trendHint) * 180);

              return (
                <button
                  key={node.meta.id}
                  type="button"
                  role="listitem"
                  aria-pressed={active}
                  aria-label={`${node.meta.id} ${node.meta.name}，${node.count} 条案例`}
                  onMouseEnter={() => setHoveredId(node.meta.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  onFocus={() => setHoveredId(node.meta.id)}
                  onBlur={() => setHoveredId(null)}
                  onClick={() => setSelectedId(node.meta.id)}
                  className={[
                    "absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center rounded-full text-white shadow-lg transition duration-300",
                    `bg-gradient-to-br ${ht.fill}`,
                    active ? "z-20 scale-105 ring-4 ring-white/80" : "z-10 hover:scale-105",
                    dim ? "opacity-35" : "opacity-100",
                  ].join(" ")}
                  style={{
                    left: `${node.x}%`,
                    top: `${node.y}%`,
                    width: size,
                    height: size,
                  }}
                  title={`${node.meta.id} ${node.meta.name}\n案例：${node.count}\n趋势：${ht.label}`}
                >
                  {/* 外圈趋势环 */}
                  <svg
                    className="pointer-events-none absolute inset-[-6px] h-[calc(100%+12px)] w-[calc(100%+12px)]"
                    viewBox="0 0 100 100"
                    aria-hidden
                  >
                    <circle
                      cx="50"
                      cy="50"
                      r="46"
                      fill="none"
                      className={ht.ring}
                      strokeWidth="3"
                      strokeLinecap="round"
                      strokeDasharray={`${ringPct * 2.9} 300`}
                      opacity={node.meta.heat === "rising" || node.meta.heat === "hot" ? 0.95 : 0.45}
                      transform="rotate(-90 50 50)"
                    />
                  </svg>
                  <Icon className="mb-0.5 h-4 w-4 opacity-90" aria-hidden />
                  <span className="font-display text-lg font-bold leading-none sm:text-xl">
                    {metricValue(node.meta, node.count)}
                  </span>
                  <span className="mt-1 max-w-[88%] truncate px-1 text-center text-[11px] font-medium leading-tight opacity-95">
                    {node.meta.name}
                  </span>
                </button>
              );
            })}
          </div>

          {/* 图例 */}
          <div className="mt-4 flex flex-wrap gap-3 text-[11px] text-muted-fg">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-gradient-to-br from-red-600 to-rose-500" />
              高风险
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-gradient-to-br from-amber-500 to-orange-500" />
              上升
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-gradient-to-br from-primary to-secondary" />
              常规
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full bg-gradient-to-br from-emerald-600 to-teal-500" />
              趋稳
            </span>
            <span className="text-muted-fg/80">气泡大小 = 案例数量 · 外圈 = 近期趋势</span>
          </div>
        </div>

        {/* 右侧详情 — 约 1/3，信息密度更高 */}
        <aside
          className="flex max-h-[min(56vh,520px)] flex-col gap-3 overflow-y-auto p-4 sm:p-5 lg:col-span-4"
          aria-live="polite"
        >
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-fg">
              风险详情
            </p>
            <h3 className="mt-1 font-display text-xl font-semibold leading-snug text-foreground">
              <span className="text-primary">{selectedMeta.id}</span> {selectedMeta.name}
            </h3>
            <span
              className={`mt-1.5 inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${tone.badge}`}
            >
              {selectedMeta.category} · {tone.label}
            </span>
          </div>

          <p className="line-clamp-3 text-xs leading-relaxed text-slate-600 sm:text-sm">
            {selectedMeta.description}
          </p>

          <dl className="grid grid-cols-2 gap-1.5 text-sm">
            <MetricBox label="关联案例" value={selected.count.toLocaleString("zh-CN")} />
            <MetricBox
              label="近30天新增"
              value={String(recentNew)}
              hint={timeRange === "all" ? "示意" : undefined}
            />
            <MetricBox
              label="环比变化"
              value={`${selectedMeta.trendHint >= 0 ? "+" : ""}${(selectedMeta.trendHint * 100).toFixed(1)}%`}
              icon={
                selectedMeta.trendHint >= 0 ? (
                  <TrendingUp className="h-3.5 w-3.5 text-warning" />
                ) : (
                  <TrendingDown className="h-3.5 w-3.5 text-accent" />
                )
              }
            />
            <MetricBox label="高风险占比" value={`${highRiskShare}%`} />
          </dl>

          <div>
            <h4 className="text-[11px] font-semibold text-muted-fg">高频场景</h4>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {selectedMeta.scenes.map((s) => (
                <span
                  key={s}
                  className="rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium text-foreground"
                >
                  {s}
                </span>
              ))}
            </div>
          </div>

          <div>
            <h4 className="text-[11px] font-semibold text-muted-fg">常见风险表达</h4>
            <ul className="mt-1.5 space-y-1">
              {selectedMeta.phrases.slice(0, 2).map((p) => (
                <li
                  key={p}
                  className="rounded-lg border border-border/70 bg-slate-50 px-2.5 py-1.5 text-[11px] leading-relaxed text-slate-700"
                >
                  “{p}”
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="text-[11px] font-semibold text-muted-fg">典型案例</h4>
            {loadingCases ? (
              <p className="mt-1.5 text-[11px] text-muted-fg">加载中…</p>
            ) : cases.length === 0 ? (
              <p className="mt-1.5 text-[11px] text-muted-fg">暂无关联案例样例</p>
            ) : (
              <ul className="mt-1.5 space-y-1">
                {cases.slice(0, 2).map((c) => (
                  <li key={c.case_id}>
                    <Link
                      to={`/cases/${encodeURIComponent(c.case_id)}`}
                      className="block rounded-lg border border-border/70 px-2.5 py-1.5 text-[11px] no-underline transition hover:border-primary/40 hover:bg-primary/5"
                    >
                      <span className="font-mono text-primary">{c.case_id}</span>
                      <span className="mt-0.5 block truncate text-foreground">
                        {c.party_name || "未命名当事人"}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="mt-auto flex flex-wrap gap-1.5 pt-1">
            <Link
              to={`/cases?risk_type=${encodeURIComponent(selectedMeta.id)}`}
              className="inline-flex min-h-9 items-center gap-1 rounded-lg bg-primary px-3 text-[11px] font-semibold text-white no-underline hover:bg-primary-deep"
            >
              查看相关案例
              <ArrowRight className="h-3 w-3" />
            </Link>
            <Link
              to="/review"
              className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-border bg-white px-3 text-[11px] font-semibold text-primary no-underline hover:bg-muted"
            >
              <ShieldCheck className="h-3 w-3" />
              智能审查
            </Link>
            <Link
              to="/search"
              className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-border bg-white px-3 text-[11px] font-semibold text-muted-fg no-underline hover:bg-muted"
            >
              <Search className="h-3 w-3" />
              检索
            </Link>
          </div>
        </aside>
      </div>

      {/* 下方风险链路 */}
      <div className="border-t border-border/70 bg-gradient-to-r from-slate-50 to-white px-5 py-4 sm:px-6">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-display text-lg font-semibold">风险链路</h3>
          <p className="text-xs text-muted-fg">
            风险类型 → 风险表达 → 相似案例 → 审查建议
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <ChainCard
            label="典型表述"
            body={`“${selectedMeta.phrases[0]}”`}
          />
          <ChainCard
            label="相似案例"
            body={
              cases.length
                ? cases.map((c) => c.case_id).join(" / ")
                : `${selectedMeta.id} 相关案例`
            }
          />
          <ChainCard label="整改建议" body={selectedMeta.suggestion} />
        </div>
      </div>
    </section>
  );
}

function MetricBox({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border/70 bg-white px-2.5 py-2">
      <dt className="text-[10px] text-muted-fg">
        {label}
        {hint ? <span className="ml-1 opacity-70">({hint})</span> : null}
      </dt>
      <dd className="mt-0.5 flex items-center gap-1 font-display text-lg font-semibold text-foreground">
        {icon}
        {value}
      </dd>
    </div>
  );
}

function ChainCard({ label, body }: { label: string; body: string }) {
  return (
    <div className="rounded-xl border border-border/60 bg-white/90 px-3 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-fg">{label}</p>
      <p className="mt-1 text-sm leading-relaxed text-slate-700">{body}</p>
    </div>
  );
}
