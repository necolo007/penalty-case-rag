import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, Scale, Search } from "lucide-react";
import type { StatsResponse } from "../api/types";
import {
  RISK_ATLAS,
  RISK_NAME_MAP,
  categoryToneClass,
  type RiskMeta,
} from "../lib/riskAtlas";

type TagTreeNode = NonNullable<StatsResponse["tag_tree"]>[number];

type Props = {
  distribution: Record<string, number>;
  tagTree?: StatsResponse["tag_tree"];
  insuranceCases?: number | null;
  pendingReviewCount?: number | null;
  tagCoverageRate?: number | null;
  entityNormalizeRate?: number | null;
};

function formatRate(rate: number | null | undefined): string {
  if (rate == null || Number.isNaN(rate)) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

function formatCount(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("zh-CN");
}

export function RiskAtlasPanel({
  distribution,
  tagTree = [],
  insuranceCases,
  pendingReviewCount,
  tagCoverageRate,
  entityNormalizeRate,
}: Props) {
  const hasRealCounts = Object.values(distribution).some((c) => c > 0)
    || (tagTree?.some((t) => t.case_count > 0) ?? false);

  const level1 = useMemo(() => {
    const fromTree = (tagTree || []).filter((t) => t.level === 1 || /^R00[1-8]$/.test(t.risk_type_id));
    const ids = RISK_ATLAS.map((m) => m.id);
    return ids.map((id) => {
      const meta = RISK_ATLAS.find((m) => m.id === id)!;
      const node = fromTree.find((t) => t.risk_type_id === id);
      const count = node?.case_count ?? distribution[id] ?? 0;
      return { meta, count, node };
    });
  }, [distribution, tagTree]);

  const childrenOf = useMemo(() => {
    const map = new Map<string, TagTreeNode[]>();
    for (const n of tagTree || []) {
      if (!n.parent_id) continue;
      const list = map.get(n.parent_id) || [];
      list.push(n);
      map.set(n.parent_id, list);
    }
    return map;
  }, [tagTree]);

  const [selectedId, setSelectedId] = useState("R001");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [searchParams] = useSearchParams();

  useEffect(() => {
    const prefill = searchParams.get("risk_type");
    if (prefill && RISK_NAME_MAP[prefill]) setSelectedId(prefill);
  }, [searchParams]);

  const selectedMeta: RiskMeta =
    RISK_ATLAS.find((m) => m.id === selectedId) || RISK_ATLAS[0];
  const selectedCount =
    level1.find((i) => i.meta.id === selectedId)?.count ?? distribution[selectedId] ?? 0;
  const selectedChildren = childrenOf.get(selectedId) || [];
  const tone = categoryToneClass(selectedMeta.categoryTone);

  const maxCount = Math.max(1, ...level1.map((i) => i.count));
  const totalClassified = level1.reduce((s, i) => s + i.count, 0);

  function bubblePx(count: number, isRoot = false) {
    // 保证中文全称可换行完整显示：一级最小约 108px，根节点约 128px
    if (!hasRealCounts) return isRoot ? 128 : 108;
    const ratio = Math.sqrt(count / maxCount);
    const min = isRoot ? 124 : 104;
    const max = isRoot ? 148 : 128;
    return min + ratio * (max - min);
  }

  function onBubbleClick(id: string) {
    setSelectedId(id);
    setExpandedId((prev) => (prev === id ? null : id));
  }

  const reviewPrefill = encodeURIComponent(
    `${selectedMeta.name}：${selectedMeta.phrases[0] || selectedMeta.description.slice(0, 40)}`,
  );

  // 轨道半径（百分比）：略放大，减少与中心气泡重叠
  const orbit = 36;

  return (
    <section className="surface overflow-hidden rounded-3xl">
      <div className="border-b border-border/70 px-5 py-5 sm:px-6">
        <h2 className="font-display text-2xl font-semibold sm:text-3xl">风险标签字典</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-fg">
          真实分类信息与案例证据。色彩表示业务类别，气泡大小表示真实案例数，连线表示标签层级。
        </p>
      </div>

      {/* 四项真实统计 */}
      <div className="grid gap-3 border-b border-border/50 px-5 py-4 sm:grid-cols-2 lg:grid-cols-4 sm:px-6">
        <MetricTile
          label="保险相关案例数"
          value={formatCount(insuranceCases)}
          hint={insuranceCases == null ? "暂无真实统计" : undefined}
        />
        <MetricTile
          label="待复核候选数"
          value={formatCount(pendingReviewCount)}
          hint={pendingReviewCount == null ? "暂无真实统计" : undefined}
        />
        <MetricTile
          label="标签覆盖率"
          value={formatRate(tagCoverageRate)}
          hint={tagCoverageRate == null ? "暂无真实统计" : undefined}
        />
        <MetricTile
          label="主体标准化完成率"
          value={formatRate(entityNormalizeRate)}
          hint={entityNormalizeRate == null ? "暂无真实统计" : undefined}
        />
      </div>

      <div className="grid lg:grid-cols-12">
        {/* 气泡树 */}
        <div className="relative border-b border-border/70 bg-gradient-to-b from-slate-50/80 to-white p-4 sm:p-5 lg:col-span-7 lg:border-b-0 lg:border-r lg:p-6">
          {!hasRealCounts ? (
            <p className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
              待接入案例统计：当前气泡使用统一尺寸，不展示编造数字。
            </p>
          ) : null}
          <div className="relative mx-auto aspect-square w-full max-w-[34rem] min-h-[320px]">
            <svg viewBox="0 0 100 100" className="absolute inset-0 h-full w-full" aria-hidden>
              {level1.map((item, i) => {
                const angle = (i / level1.length) * Math.PI * 2 - Math.PI / 2;
                const x = 50 + Math.cos(angle) * orbit;
                const y = 50 + Math.sin(angle) * orbit;
                return (
                  <line
                    key={`line-${item.meta.id}`}
                    x1={50}
                    y1={50}
                    x2={x}
                    y2={y}
                    className="stroke-slate-300/80"
                    strokeWidth={0.4}
                    strokeLinecap="round"
                  />
                );
              })}
              {expandedId
                ? (childrenOf.get(expandedId) || []).slice(0, 6).map((child, i) => {
                    const parent = level1.findIndex((x) => x.meta.id === expandedId);
                    const pAngle = (parent / level1.length) * Math.PI * 2 - Math.PI / 2;
                    const px = 50 + Math.cos(pAngle) * orbit;
                    const py = 50 + Math.sin(pAngle) * orbit;
                    const cAngle = pAngle + (i - 2.5) * 0.28;
                    const cx = px + Math.cos(cAngle) * 16;
                    const cy = py + Math.sin(cAngle) * 16;
                    return (
                      <line
                        key={`cline-${child.risk_type_id}`}
                        x1={px}
                        y1={py}
                        x2={cx}
                        y2={cy}
                        className="stroke-slate-300/70"
                        strokeWidth={0.3}
                        strokeLinecap="round"
                      />
                    );
                  })
                : null}
            </svg>

            {/* 中心根节点 */}
            <button
              type="button"
              onClick={() => {
                setSelectedId("R001");
                setExpandedId(null);
              }}
              className="absolute left-1/2 top-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 cursor-pointer flex-col items-center justify-center rounded-full bg-gradient-to-br from-primary to-secondary px-3 text-center text-white shadow-[0_10px_28px_rgba(15,23,42,0.18)] ring-4 ring-white transition duration-200 hover:scale-[1.03] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transition-none"
              style={{
                width: bubblePx(totalClassified, true),
                height: bubblePx(totalClassified, true),
              }}
              aria-label={`保险监管处罚标签，共 ${hasRealCounts ? totalClassified : "未知"} 例`}
            >
              <span className="text-[11px] font-semibold leading-snug tracking-wide text-white/95">
                保险监管
              </span>
              <span className="text-[11px] font-semibold leading-snug tracking-wide text-white/95">
                处罚标签
              </span>
              <span className="mt-1 rounded-full bg-white/20 px-2 py-0.5 font-display text-xs font-bold tabular-nums backdrop-blur-sm">
                {hasRealCounts ? `${totalClassified} 例` : "—"}
              </span>
            </button>

            {level1.map((item, i) => {
              const angle = (i / level1.length) * Math.PI * 2 - Math.PI / 2;
              const x = 50 + Math.cos(angle) * orbit;
              const y = 50 + Math.sin(angle) * orbit;
              const size = bubblePx(item.count);
              const selected = selectedId === item.meta.id;
              const expanded = expandedId === item.meta.id;
              const cat = categoryToneClass(item.meta.categoryTone);
              return (
                <button
                  key={item.meta.id}
                  type="button"
                  onClick={() => onBubbleClick(item.meta.id)}
                  className={[
                    "absolute z-20 flex -translate-x-1/2 -translate-y-1/2 cursor-pointer flex-col items-center justify-center rounded-full bg-gradient-to-br px-2.5 text-center text-white shadow-[0_8px_22px_rgba(15,23,42,0.16)] ring-2 ring-white/90 transition duration-200 hover:scale-[1.05] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transition-none",
                    cat.fill,
                    selected || expanded
                      ? "z-30 scale-[1.06] ring-4 ring-primary/45"
                      : "",
                  ].join(" ")}
                  style={{ left: `${x}%`, top: `${y}%`, width: size, height: size }}
                  aria-pressed={selected}
                  aria-label={`${item.meta.id} ${item.meta.name}，${hasRealCounts ? `${item.count}例` : "暂无统计"}`}
                  title={`${item.meta.id} ${item.meta.name}`}
                >
                  <span className="rounded-full bg-black/15 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white/95">
                    {item.meta.id}
                  </span>
                  <span className="mt-1 w-full px-0.5 text-[12px] font-semibold leading-snug text-white [overflow-wrap:anywhere]">
                    {item.meta.name}
                  </span>
                  <span className="mt-1 text-[11px] font-medium tabular-nums text-white/90">
                    {hasRealCounts ? `${item.count}例` : "—"}
                  </span>
                </button>
              );
            })}

            {expandedId
              ? (childrenOf.get(expandedId) || []).slice(0, 6).map((child, i) => {
                  const parent = level1.findIndex((x) => x.meta.id === expandedId);
                  const pAngle = (parent / level1.length) * Math.PI * 2 - Math.PI / 2;
                  const px = 50 + Math.cos(pAngle) * orbit;
                  const py = 50 + Math.sin(pAngle) * orbit;
                  const cAngle = pAngle + (i - 2.5) * 0.28;
                  const cx = px + Math.cos(cAngle) * 16;
                  const cy = py + Math.sin(cAngle) * 16;
                  const shortName =
                    child.risk_type_name.length > 6
                      ? `${child.risk_type_name.slice(0, 5)}…`
                      : child.risk_type_name;
                  return (
                    <button
                      key={child.risk_type_id}
                      type="button"
                      onClick={() => setSelectedId(expandedId)}
                      className="absolute z-30 flex min-h-11 min-w-11 -translate-x-1/2 -translate-y-1/2 cursor-pointer flex-col items-center justify-center rounded-full bg-white px-1.5 text-center shadow-md ring-1 ring-slate-200/90 transition duration-200 hover:scale-105 hover:ring-primary/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transition-none"
                      style={{ left: `${cx}%`, top: `${cy}%`, width: 56, height: 56 }}
                      title={`${child.risk_type_id} ${child.risk_type_name}`}
                      aria-label={`${child.risk_type_name}，${hasRealCounts ? `${child.case_count}例` : "暂无统计"}`}
                    >
                      <span className="max-w-full text-[10px] font-semibold leading-tight text-slate-800">
                        {shortName}
                      </span>
                      <span className="mt-0.5 text-[10px] tabular-nums text-slate-500">
                        {hasRealCounts ? child.case_count : "·"}
                      </span>
                    </button>
                  );
                })
              : null}
          </div>
          <p className="mt-3 text-center text-xs text-muted-fg">
            点击一级标签展开子级；再次点击可收起。气泡内完整显示标签名称。
          </p>
        </div>

        {/* 标签知识卡 */}
        <aside className="lg:col-span-5 p-5 sm:p-6">
          <div className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${tone.badge}`}>
            {selectedMeta.category}
          </div>
          <h3 className="mt-3 font-display text-xl font-semibold">
            {selectedMeta.id}｜{selectedMeta.name}
          </h3>
          <p className="mt-1 text-xs text-muted-fg">
            关联案例 {hasRealCounts ? `${selectedCount} 例` : "待接入案例统计"}
          </p>

          <dl className="mt-5 space-y-4 text-sm">
            <div>
              <dt className="text-xs font-semibold text-muted-fg">标签定义</dt>
              <dd className="mt-1 leading-relaxed text-foreground">{selectedMeta.description}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold text-muted-fg">典型表达</dt>
              <dd className="mt-1 flex flex-wrap gap-1.5">
                {selectedMeta.phrases.map((p) => (
                  <span key={p} className="rounded-md bg-muted px-2 py-0.5 text-xs">
                    {p}
                  </span>
                ))}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold text-muted-fg">业务口语 → 监管标准表述</dt>
              <dd className="mt-1 space-y-1">
                {selectedMeta.colloquialMap.map((m) => (
                  <p key={m.oral} className="text-xs leading-relaxed">
                    <span className="text-muted-fg">{m.oral}</span>
                    <span className="mx-1 text-muted-fg">→</span>
                    <span className="font-medium">{m.standard}</span>
                  </p>
                ))}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold text-muted-fg">标签层级</dt>
              <dd className="mt-1 text-xs leading-relaxed">
                {selectedChildren.length
                  ? selectedChildren
                      .map((c) => `${c.risk_type_id} ${c.risk_type_name}`)
                      .join(" · ")
                  : "一级标签（下级由字典 parent_id 动态加载；当前无下级或未入库）"}
              </dd>
            </div>
          </dl>

          <div className="mt-6 flex flex-col gap-2">
            <Link
              to={`/cases?risk_type=${encodeURIComponent(selectedMeta.id)}`}
              className="inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white no-underline transition duration-200 hover:bg-primary-deep focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              <Search className="h-4 w-4" aria-hidden />
              查看关联案例
              <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
            <Link
              to={`/review?prefill=${reviewPrefill}&risk_type=${encodeURIComponent(selectedMeta.id)}`}
              className="inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-xl border border-primary/25 bg-white px-4 text-sm font-semibold text-primary no-underline transition duration-200 hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              <Scale className="h-4 w-4" aria-hidden />
              用于智能审查
            </Link>
          </div>
        </aside>
      </div>
    </section>
  );
}

function MetricTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-border/70 bg-white/80 px-3 py-3">
      <p className="text-xs text-muted-fg">{label}</p>
      <p className="mt-1 font-display text-2xl font-semibold text-foreground">{value}</p>
      {hint ? <p className="mt-0.5 text-[11px] text-muted-fg">{hint}</p> : null}
    </div>
  );
}
