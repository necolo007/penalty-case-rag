import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
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
import { api, ApiError } from "../api/client";
import type { RetrieveResponse } from "../api/types";
import { SearchResultCard } from "../components/SearchResultCard";
import { SearchUnderstandingPanel } from "../components/SearchUnderstandingPanel";
import { EmptyState, ErrorAlert, TagChip } from "../components/ui";
import {
  formatHistoryAge,
  loadSearchHistory,
  pushSearchHistory,
  type SearchHistoryItem,
} from "../lib/searchHistory";
import { RISK_ATLAS } from "../lib/riskAtlas";

const CAPABILITY_TAGS = ["语义理解", "多路召回", "智能排序", "证据追溯"];

const SUGGESTIONS = [
  { label: "销售误导", query: "向客户承诺保本保收益，夸大产品收益" },
  { label: "合同外利益", query: "购买产品即可领取礼品，收益稳定无风险" },
  { label: "虚假宣传", query: "宣传材料存在虚假夸大表述，隐瞒重要信息" },
  { label: "费用违规", query: "虚构业务套取费用、虚列费用" },
] as const;

const CAPABILITIES = [
  {
    icon: FileText,
    title: "文档理解",
    desc: "解析监管处罚文件",
  },
  {
    icon: ScanSearch,
    title: "语义搜索",
    desc: "理解业务表达",
  },
  {
    icon: Scale,
    title: "案例匹配",
    desc: "匹配历史处罚",
  },
  {
    icon: Bookmark,
    title: "证据追溯",
    desc: "定位处罚依据",
  },
] as const;

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [riskType, setRiskType] = useState("");
  const [regulator, setRegulator] = useState("");
  const [institutionType, setInstitutionType] = useState("");
  const [scene, setScene] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [riskLevel, setRiskLevel] = useState("");
  const [salesRelated, setSalesRelated] = useState("");
  const [topK, setTopK] = useState(10);
  const [useReranker, setUseReranker] = useState(true);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<SearchHistoryItem[]>([]);

  const [loading, setLoading] = useState(false);
  const [understanding, setUnderstanding] = useState(false);
  const [understandingDone, setUnderstandingDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<RetrieveResponse | null>(null);
  const [pendingCount, setPendingCount] = useState<number | null>(null);

  const historyRef = useRef<HTMLDivElement>(null);
  const minThinkMs = 2200;

  useEffect(() => {
    setHistory(loadSearchHistory());
  }, []);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) {
        setHistoryOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  async function runSearch(q: string) {
    const text = q.trim();
    if (!text) {
      setError("请输入检索问题或违规描述");
      return;
    }

    setQuery(text);
    setLoading(true);
    setUnderstanding(true);
    setUnderstandingDone(false);
    setError(null);
    setData(null);
    setPendingCount(null);

    const started = Date.now();
    pushSearchHistory(text);
    setHistory(loadSearchHistory());

    try {
      const res = (await api.retrieve({
        query_text: text,
        risk_type: riskType || null,
        regulator: regulator || null,
        institution_type: institutionType || null,
        scene: scene || null,
        date_from: dateFrom || null,
        date_to: dateTo || null,
        top_k: topK,
        use_reranker: useReranker,
      })) as RetrieveResponse;

      const poolEstimate = Object.values(res.channel_stats).reduce((a, b) => a + b, 0);
      setPendingCount(poolEstimate || res.results.length * 8);

      const elapsed = Date.now() - started;
      if (elapsed < minThinkMs) {
        await new Promise((r) => window.setTimeout(r, minThinkMs - elapsed));
      }

      setData(res);
      setUnderstandingDone(true);
    } catch (err) {
      setData(null);
      setError(err instanceof ApiError ? err.message : "检索失败，请稍后重试");
      setUnderstandingDone(true);
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void runSearch(query);
  }

  const showEmptyLanding = !data && !loading && !understanding;

  return (
    <div className="space-y-8">
      <header className="rise-in max-w-3xl">
        <h1 className="font-display text-4xl font-bold text-foreground sm:text-5xl">智能检索</h1>
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

      <form
        onSubmit={onSubmit}
        className="surface rise-in rounded-3xl p-5 sm:p-7"
        aria-label="案例检索表单"
      >
        <label htmlFor="query" className="mb-2 block text-sm font-semibold text-foreground">
          检索内容
        </label>
        <textarea
          id="query"
          rows={3}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='输入营销话术、业务描述或疑似违规表述，例如："购买产品即可领取礼品，收益稳定无风险"'
          className="w-full resize-y rounded-2xl border border-border bg-white px-4 py-4 text-base leading-relaxed text-foreground outline-none transition focus:border-primary focus:ring-4 focus:ring-primary/15"
        />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s.label}
              type="button"
              onClick={() => setQuery(s.query)}
              className="rounded-lg border border-border bg-white px-3 py-1.5 text-xs font-semibold text-foreground transition hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
            >
              {s.label}
            </button>
          ))}

          <div className="relative ml-auto" ref={historyRef}>
            <button
              type="button"
              onClick={() => setHistoryOpen((o) => !o)}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border bg-white px-3 text-xs font-semibold text-muted-fg transition hover:border-primary/40 hover:text-primary"
              aria-expanded={historyOpen}
              aria-haspopup="listbox"
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
                          void runSearch(h.query);
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

        <div className="mt-5">
          <button
            type="button"
            onClick={() => setAdvancedOpen((o) => !o)}
            className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-border bg-white px-4 text-sm font-semibold text-foreground transition hover:border-primary/40 hover:bg-muted"
            aria-expanded={advancedOpen}
          >
            <SlidersHorizontal className="h-4 w-4 text-primary" aria-hidden />
            高级筛选
            <ChevronDown className={`h-4 w-4 text-muted-fg transition ${advancedOpen ? "rotate-180" : ""}`} aria-hidden />
          </button>

          {advancedOpen ? (
            <div className="mt-4 grid gap-4 rounded-2xl border border-border/70 bg-muted/30 p-4 sm:grid-cols-2 lg:grid-cols-3">
              <FilterField label="风险类型" id="riskType">
                <select
                  id="riskType"
                  value={riskType}
                  onChange={(e) => setRiskType(e.target.value)}
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
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
                />
              </FilterField>

              <FilterField label="时间范围 · 止" id="dateTo">
                <input
                  id="dateTo"
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
                />
              </FilterField>

              <FilterField label="监管机构" id="regulator">
                <input
                  id="regulator"
                  value={regulator}
                  onChange={(e) => setRegulator(e.target.value)}
                  placeholder="如 国家金融监督管理总局"
                  className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
                />
              </FilterField>

              <FilterField label="案例来源 / 业务场景" id="scene">
                <select
                  id="scene"
                  value={scene}
                  onChange={(e) => setScene(e.target.value)}
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
                  value={institutionType}
                  onChange={(e) => setInstitutionType(e.target.value)}
                  className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
                >
                  <option value="">全部机构</option>
                  <option value="寿险公司">寿险公司</option>
                  <option value="财险公司">财险公司</option>
                  <option value="分支机构">分支机构</option>
                  <option value="保险中介">保险中介</option>
                </select>
              </FilterField>

              <FilterField label="风险等级（展示偏好）" id="riskLevel">
                <select
                  id="riskLevel"
                  value={riskLevel}
                  onChange={(e) => setRiskLevel(e.target.value)}
                  className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
                >
                  <option value="">不限</option>
                  <option value="high">高风险优先</option>
                  <option value="medium">中风险</option>
                  <option value="low">低风险</option>
                </select>
              </FilterField>

              <FilterField label="是否涉及销售行为" id="salesRelated">
                <select
                  id="salesRelated"
                  value={salesRelated}
                  onChange={(e) => setSalesRelated(e.target.value)}
                  className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
                >
                  <option value="">不限</option>
                  <option value="yes">是</option>
                  <option value="no">否</option>
                </select>
              </FilterField>

              <FilterField label="返回条数" id="topK">
                <input
                  id="topK"
                  type="number"
                  min={1}
                  max={50}
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value) || 10)}
                  className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
                />
              </FilterField>

              <div className="flex items-end sm:col-span-2 lg:col-span-3">
                <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-border bg-white px-3 text-sm">
                  <input
                    type="checkbox"
                    checked={useReranker}
                    onChange={(e) => setUseReranker(e.target.checked)}
                    className="h-4 w-4 accent-primary"
                  />
                  启用精排 Reranker
                </label>
              </div>
            </div>
          ) : null}
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={loading}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-6 text-sm font-semibold text-white transition hover:bg-primary-deep disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Sparkles className="h-4 w-4" aria-hidden />
            )}
            {loading ? "理解并检索中…" : "检索相似案例"}
          </button>
          {data ? (
            <span className="text-sm text-muted-fg">
              耗时 {data.took_ms} ms · 返回 {data.results.length} 条
            </span>
          ) : null}
        </div>
      </form>

      {showEmptyLanding ? (
        <section className="rise-in rounded-3xl border border-border/60 bg-white/70 p-6 sm:p-8">
          <h2 className="font-display text-2xl font-semibold text-foreground">智能检索能力</h2>
          <p className="mt-2 max-w-2xl text-sm text-muted-fg">
            从监管文书到业务话术，多路召回并精排相似处罚案例，输出可解释、可溯源的匹配证据。
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

      {error ? <ErrorAlert message={error} /> : null}

      {(understanding || understandingDone) && !error ? (
        <SearchUnderstandingPanel
          active={understanding && !understandingDone}
          finished={understandingDone}
          query={query}
          predictedRiskIds={data?.predicted_risk_ids ?? []}
          predictedCnTags={data?.predicted_cn_tags ?? []}
          resultCount={pendingCount}
          topK={topK}
        />
      ) : null}

      {data ? (
        <section className="space-y-5">
          {(data.predicted_cn_tags?.length || data.predicted_risk_ids.length > 0 || Object.keys(data.channel_stats).length > 0) ? (
            <div className="space-y-2 rounded-2xl border border-border/70 bg-white/80 px-4 py-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-muted-fg">预判风险（27类）</span>
                {(data.predicted_cn_tags?.length ? data.predicted_cn_tags : []).map((tag) => (
                  <TagChip key={tag}>{tag}</TagChip>
                ))}
                {!data.predicted_cn_tags?.length ? (
                  <span className="text-muted-fg">暂无细粒度标签，已用内部大类召回</span>
                ) : null}
              </div>
              {data.predicted_risk_ids.length > 0 ? (
                <div className="flex flex-wrap items-center gap-2 text-muted-fg">
                  <span className="font-medium">内部召回大类</span>
                  {data.predicted_risk_ids.map((id) => (
                    <span key={id} className="rounded-md bg-muted px-2 py-0.5 font-mono">
                      {id}
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {Object.entries(data.channel_stats).map(([ch, n]) => (
                  <span key={ch} className="rounded-md bg-muted px-2 py-0.5 text-muted-fg">
                    {ch}: {n}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {data.results.length === 0 ? (
            <EmptyState
              title="未找到相似案例"
              description="可尝试更具体的违规行为关键词，或调整高级筛选条件。"
            />
          ) : (
            <div className="stagger space-y-5">
              {data.results.map((r) => (
                <SearchResultCard
                  key={r.case_id}
                  item={r}
                  userQuery={data.query}
                  rewrittenQuery={data.rewritten_query}
                  predictedRiskIds={data.predicted_risk_ids}
                  predictedCnTags={data.predicted_cn_tags ?? []}
                  onSearchExpanded={(q) => void runSearch(q)}
                />
              ))}
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
