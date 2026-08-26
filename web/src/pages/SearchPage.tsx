import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  Bookmark,
  ChevronDown,
  FileText,
  History,
  Loader2,
  Scale,
  ScanSearch,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { SearchCaseDetailPanel } from "../components/SearchCaseDetailPanel";
import { SearchResultListItem } from "../components/SearchResultListItem";
import { SearchUnderstandingPanel } from "../components/SearchUnderstandingPanel";
import { SearchUnderstandingSummary } from "../components/SearchUnderstandingSummary";
import { EmptyState, ErrorAlert, TagChip } from "../components/ui";
import {
  formatHistoryAge,
  loadSearchHistory,
  type SearchHistoryItem,
} from "../lib/searchHistory";
import { countHighRelevance } from "../lib/searchInsights";
import { searchSession, useSearchSession } from "../lib/searchSession";
import { RISK_ATLAS } from "../lib/riskAtlas";

const CAPABILITY_TAGS = ["语义改写", "BGE-M3 召回", "CE / listwise", "证据追溯"];

const SUGGESTIONS = [
  { label: "销售误导", query: "向客户承诺保本保收益，夸大产品收益" },
  { label: "合同外利益", query: "购买产品即可领取礼品，收益稳定无风险" },
  { label: "虚假宣传", query: "宣传材料存在虚假夸大表述，隐瞒重要信息" },
  { label: "费用违规", query: "虚构业务套取费用、虚列费用" },
] as const;

const CAPABILITIES = [
  { icon: FileText, title: "文档理解", desc: "解析监管处罚文件" },
  { icon: ScanSearch, title: "语义搜索", desc: "理解业务表达" },
  { icon: Scale, title: "案例匹配", desc: "匹配历史处罚" },
  { icon: Bookmark, title: "证据追溯", desc: "定位处罚依据" },
] as const;

export function SearchPage() {
  const s = useSearchSession();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<SearchHistoryItem[]>([]);
  const historyRef = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const hasResults = Boolean(s.data?.results.length);

  useEffect(() => {
    setHistory(loadSearchHistory());
  }, [s.data, s.loading]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) {
        setHistoryOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  // 有缓存结果但 selected 失效时回填首条
  useEffect(() => {
    if (!s.data?.results.length) return;
    const exists = s.data.results.some((r) => r.case_id === s.selectedCaseId);
    if (!exists) {
      searchSession.setSelectedCaseId(s.data.results[0].case_id);
    }
  }, [s.data, s.selectedCaseId]);

  const selected = useMemo(
    () => s.data?.results.find((r) => r.case_id === s.selectedCaseId) ?? null,
    [s.data, s.selectedCaseId],
  );

  const highCount = s.data ? countHighRelevance(s.data.results) : 0;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void searchSession.runSearch(s.query);
  }

  function selectCase(id: string) {
    searchSession.setSelectedCaseId(id);
    if (window.matchMedia("(max-width: 1023px)").matches) {
      window.setTimeout(() => {
        detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 50);
    }
  }

  const showEmptyLanding = !s.data && !s.loading && !s.understanding && !s.understandingDone;
  const workspaceMode = hasResults || (s.understandingDone && Boolean(s.data));

  return (
    <div
      className={
        workspaceMode
          ? "flex min-h-0 flex-col gap-2 lg:h-[calc(100dvh-6.75rem)] lg:overflow-hidden"
          : "space-y-6"
      }
    >
      {!hasResults && !s.loading && !s.understandingDone ? (
        <header className="rise-in max-w-3xl">
          <h1 className="font-display text-4xl font-bold text-foreground sm:text-5xl">相似案例检索</h1>
          <p className="mt-3 text-base leading-relaxed text-muted-fg">
            输入业务场景、营销话术或违规描述，系统自动识别风险特征，并匹配历史监管处罚案例，为合规审查提供可追溯依据。
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {CAPABILITY_TAGS.map((tag, i) => (
              <span key={tag} className="inline-flex items-center text-xs font-medium text-muted-fg">
                {i > 0 ? <span className="mx-1.5 text-border">+</span> : null}
                <TagChip>{tag}</TagChip>
              </span>
            ))}
          </div>
        </header>
      ) : (
        <header className="rise-in flex shrink-0 flex-wrap items-baseline justify-between gap-2">
          <h1 className="font-display text-xl font-bold text-foreground sm:text-2xl">相似案例检索</h1>
          {s.data ? (
            <p className="text-xs text-muted-fg">
              召回 <span className="font-semibold text-foreground">{s.data.results.length}</span> 条
              {highCount > 0 ? (
                <>
                  · 高度相关 <span className="font-semibold text-accent">{highCount}</span>
                </>
              ) : null}
              · {(s.data.took_ms / 1000).toFixed(2)}s
            </p>
          ) : (
            <p className="text-xs text-muted-fg">改写 / HyDE · BGE-M3 · 证据可追溯</p>
          )}
        </header>
      )}

      <form
        onSubmit={onSubmit}
        className={[
          "surface rise-in rounded-xl p-3 sm:p-4",
          hasResults ? "shrink-0" : "",
        ].join(" ")}
        aria-label="案例检索表单"
      >
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start">
          <div className="min-w-0 flex-1">
            <label htmlFor="query" className="sr-only">
              检索内容
            </label>
            <textarea
              id="query"
              rows={hasResults || s.understandingDone ? 1 : 3}
              value={s.query}
              onChange={(e) => searchSession.setQuery(e.target.value)}
              placeholder='输入营销话术或违规描述，例如："购买产品即可领取礼品，收益稳定无风险"'
              className={[
                "w-full resize-y rounded-xl border border-border bg-white px-3 py-2.5 text-sm leading-relaxed text-foreground outline-none transition focus:border-primary focus:ring-4 focus:ring-primary/15",
                hasResults || s.understandingDone ? "min-h-11 max-h-24" : "",
              ].join(" ")}
            />
          </div>
          <div className="flex shrink-0 flex-wrap gap-2 lg:flex-col">
            <button
              type="submit"
              disabled={s.loading}
              className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-primary px-5 text-sm font-semibold text-white transition hover:bg-primary-deep disabled:cursor-not-allowed disabled:opacity-60 lg:flex-none lg:min-w-[8.5rem]"
            >
              {s.loading ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Sparkles className="h-4 w-4" aria-hidden />
              )}
              {s.loading ? "检索中…" : "检索"}
            </button>
            <button
              type="button"
              onClick={() => searchSession.toggleAdvancedOpen()}
              className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-border bg-white px-4 text-sm font-semibold text-foreground transition hover:bg-muted"
              aria-expanded={s.advancedOpen}
            >
              <SlidersHorizontal className="h-4 w-4 text-primary" aria-hidden />
              高级
              <ChevronDown
                className={`h-3.5 w-3.5 text-muted-fg transition ${s.advancedOpen ? "rotate-180" : ""}`}
                aria-hidden
              />
            </button>
          </div>
        </div>

        {!hasResults && !s.understandingDone ? (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {SUGGESTIONS.map((item) => (
              <button
                key={item.label}
                type="button"
                onClick={() => searchSession.setQuery(item.query)}
                className="rounded-lg border border-border bg-white px-3 py-1.5 text-xs font-semibold text-foreground transition hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
              >
                {item.label}
              </button>
            ))}
            <div className="relative ml-auto" ref={historyRef}>
              <button
                type="button"
                onClick={() => setHistoryOpen((o) => !o)}
                className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border bg-white px-3 text-xs font-semibold text-muted-fg transition hover:border-primary/40 hover:text-primary"
                aria-expanded={historyOpen}
              >
                <History className="h-3.5 w-3.5" aria-hidden />
                最近检索
                <ChevronDown className={`h-3.5 w-3.5 transition ${historyOpen ? "rotate-180" : ""}`} aria-hidden />
              </button>
              {historyOpen ? (
                <ul
                  className="absolute right-0 z-20 mt-1 min-w-[240px] overflow-hidden rounded-xl border border-border bg-white py-1 shadow-[var(--shadow-lift)]"
                  role="listbox"
                >
                  {history.length === 0 ? (
                    <li className="px-3 py-2 text-xs text-muted-fg">暂无检索记录</li>
                  ) : (
                    history.map((h) => (
                      <li key={`${h.query}-${h.ts}`}>
                        <button
                          type="button"
                          className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs transition hover:bg-muted"
                          onClick={() => {
                            setHistoryOpen(false);
                            void searchSession.runSearch(h.query);
                          }}
                        >
                          <span className="truncate text-foreground">{h.query}</span>
                          <span className="shrink-0 text-muted-fg">{formatHistoryAge(h.ts)}</span>
                        </button>
                      </li>
                    ))
                  )}
                </ul>
              ) : null}
            </div>
          </div>
        ) : null}

        {s.advancedOpen ? (
          <div className="mt-4 grid gap-4 rounded-2xl border border-border/70 bg-muted/30 p-4 sm:grid-cols-2 lg:grid-cols-3">
            <FilterField label="风险类型" id="riskType">
              <select
                id="riskType"
                value={s.riskType}
                onChange={(e) => searchSession.setRiskType(e.target.value)}
                className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              >
                <option value="">全部</option>
                {RISK_ATLAS.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.id} {r.name}
                  </option>
                ))}
              </select>
            </FilterField>
            <FilterField label="时间范围 · 起" id="dateFrom">
              <input
                id="dateFrom"
                type="date"
                value={s.dateFrom}
                onChange={(e) => searchSession.setDateFrom(e.target.value)}
                className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              />
            </FilterField>
            <FilterField label="时间范围 · 止" id="dateTo">
              <input
                id="dateTo"
                type="date"
                value={s.dateTo}
                onChange={(e) => searchSession.setDateTo(e.target.value)}
                className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              />
            </FilterField>
            <FilterField label="监管机构" id="regulator">
              <input
                id="regulator"
                value={s.regulator}
                onChange={(e) => searchSession.setRegulator(e.target.value)}
                placeholder="如 国家金融监督管理总局"
                className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              />
            </FilterField>
            <FilterField label="案例来源 / 业务场景" id="scene">
              <select
                id="scene"
                value={s.scene}
                onChange={(e) => searchSession.setScene(e.target.value)}
                className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              >
                <option value="">全部场景</option>
                <option value="营销宣传">营销宣传</option>
                <option value="销售话术">销售话术</option>
                <option value="产品说明">产品说明</option>
                <option value="培训材料">培训材料</option>
              </select>
            </FilterField>
            <FilterField label="机构类型" id="institutionType">
              <select
                id="institutionType"
                value={s.institutionType}
                onChange={(e) => searchSession.setInstitutionType(e.target.value)}
                className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              >
                <option value="">全部机构</option>
                <option value="寿险公司">寿险公司</option>
                <option value="财险公司">财险公司</option>
                <option value="分支机构">分支机构</option>
                <option value="保险中介">保险中介</option>
              </select>
            </FilterField>
            <FilterField label="返回条数" id="topK">
              <input
                id="topK"
                type="number"
                min={1}
                max={50}
                value={s.topK}
                onChange={(e) => searchSession.setTopK(Number(e.target.value) || 10)}
                className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              />
            </FilterField>
            <div className="flex items-end sm:col-span-2 lg:col-span-3">
              <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-border bg-white px-3 text-sm">
                <input
                  type="checkbox"
                  checked={s.useReranker}
                  onChange={(e) => searchSession.setUseReranker(e.target.checked)}
                  className="h-4 w-4 accent-primary"
                />
                启用精排 Reranker
              </label>
            </div>
          </div>
        ) : null}
      </form>

      {showEmptyLanding ? (
        <section className="rise-in rounded-3xl border border-border/60 bg-white/70 p-6 sm:p-8">
          <h2 className="font-display text-2xl font-semibold text-foreground">相似案例检索能力</h2>
          <p className="mt-2 max-w-2xl text-sm text-muted-fg">
            从监管文书到业务话术，经 BGE-M3 多通道召回与精排返回相似处罚案例，输出可解释、可溯源的匹配证据。
          </p>
          <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {CAPABILITIES.map(({ icon: Icon, title, desc }) => (
              <li
                key={title}
                className="rounded-2xl border border-border/70 bg-white p-4 transition hover:border-primary/30 hover:shadow-[var(--shadow-soft)]"
              >
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Icon className="h-5 w-5" aria-hidden />
                </span>
                <p className="mt-3 font-display text-lg font-semibold text-foreground">{title}</p>
                <p className="mt-1 text-sm text-muted-fg">{desc}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {s.error ? <ErrorAlert message={s.error} /> : null}

      {s.understanding && !s.understandingDone && !s.error ? (
        <SearchUnderstandingPanel
          active
          finished={false}
          query={s.query}
          predictedRiskIds={s.data?.predicted_risk_ids ?? []}
          predictedCnTags={s.data?.predicted_cn_tags ?? []}
          resultCount={s.pendingCount}
          topK={s.topK}
        />
      ) : null}

      {s.understandingDone && s.data && !s.error ? (
        <div className="shrink-0">
          <SearchUnderstandingSummary
            query={s.query}
            predictedRiskIds={s.data.predicted_risk_ids}
            predictedCnTags={s.data.predicted_cn_tags ?? []}
          />
        </div>
      ) : null}

      {s.data ? (
        <section className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
          {s.data.results.length === 0 ? (
            <EmptyState
              title="未找到相似案例"
              description="可尝试更具体的违规行为关键词，或调整高级筛选条件。"
            />
          ) : (
            <div className="grid min-h-0 flex-1 gap-3 overflow-hidden lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
              <div
                className="flex min-h-0 flex-col gap-2 overflow-hidden"
                role="listbox"
                aria-label="相似案例列表"
              >
                <h2 className="shrink-0 px-0.5 text-[11px] font-semibold uppercase tracking-wide text-muted-fg">
                  Top-{s.data.results.length} 相关案例
                </h2>
                <div className="stagger min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain pr-0.5">
                  {s.data.results.map((r) => (
                    <SearchResultListItem
                      key={r.case_id}
                      item={r}
                      userQuery={s.data!.query}
                      predictedCnTags={s.data!.predicted_cn_tags ?? []}
                      predictedRiskIds={s.data!.predicted_risk_ids}
                      selected={r.case_id === s.selectedCaseId}
                      onSelect={() => selectCase(r.case_id)}
                    />
                  ))}
                </div>
              </div>

              <div ref={detailRef} className="min-h-[18rem] overflow-hidden lg:min-h-0 lg:h-full">
                {selected ? (
                  <SearchCaseDetailPanel
                    item={selected}
                    userQuery={s.data.query}
                    predictedCnTags={s.data.predicted_cn_tags ?? []}
                  />
                ) : (
                  <div className="surface flex h-full min-h-[14rem] items-center justify-center rounded-xl p-6 text-sm text-muted-fg">
                    选择左侧案例查看匹配证据
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}

function FilterField({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-semibold text-muted-fg">
        {label}
      </label>
      {children}
    </div>
  );
}
