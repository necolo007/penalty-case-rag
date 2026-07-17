import { useState, type FormEvent } from "react";
import { Loader2, Search, Sparkles } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { RetrieveResponse } from "../api/types";
import { CaseCard } from "../components/CaseCard";
import { EmptyState, ErrorAlert, TagChip } from "../components/ui";

const SUGGESTIONS = [
  "销售误导承诺收益保本",
  "给予投保人合同外利益",
  "虚假宣传保险产品",
  "未按规定披露关联交易",
];

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [riskType, setRiskType] = useState("");
  const [regulator, setRegulator] = useState("");
  const [topK, setTopK] = useState(10);
  const [useReranker, setUseReranker] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<RetrieveResponse | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) {
      setError("请输入检索问题或违规描述");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = (await api.retrieve({
        query_text: q,
        risk_type: riskType || null,
        regulator: regulator || null,
        top_k: topK,
        use_reranker: useReranker,
      })) as RetrieveResponse;
      setData(res);
    } catch (err) {
      setData(null);
      setError(err instanceof ApiError ? err.message : "检索失败，请稍后重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <header className="rise-in max-w-3xl">
        <h1 className="font-display text-4xl font-bold text-foreground sm:text-5xl">智能检索</h1>
        <p className="mt-3 text-base text-muted-fg">
          输入业务场景或违规描述，系统将改写查询并以四路召回 + RRF 融合返回相似处罚案例。
        </p>
      </header>

      <form
        onSubmit={onSubmit}
        className="surface rise-in rounded-3xl p-5 sm:p-7"
        aria-label="案例检索表单"
      >
        <label htmlFor="query" className="mb-2 block text-sm font-semibold text-foreground">
          检索内容
        </label>
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-fg"
            aria-hidden
          />
          <textarea
            id="query"
            rows={3}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="例如：代理人向客户承诺保险产品保本保收益…"
            className="w-full resize-y rounded-2xl border border-border bg-white py-4 pl-12 pr-4 text-base leading-relaxed text-foreground outline-none transition focus:border-primary focus:ring-4 focus:ring-primary/15"
          />
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setQuery(s)}
              className="rounded-full border border-border bg-white px-3 py-1.5 text-xs font-medium text-muted-fg transition hover:border-primary/40 hover:text-primary"
            >
              {s}
            </button>
          ))}
        </div>

        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label htmlFor="riskType" className="mb-1.5 block text-xs font-semibold text-muted-fg">
              风险类型（可选）
            </label>
            <input
              id="riskType"
              value={riskType}
              onChange={(e) => setRiskType(e.target.value)}
              placeholder="如 R001"
              className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
            />
          </div>
          <div>
            <label htmlFor="regulator" className="mb-1.5 block text-xs font-semibold text-muted-fg">
              监管机构（可选）
            </label>
            <input
              id="regulator"
              value={regulator}
              onChange={(e) => setRegulator(e.target.value)}
              placeholder="如 国家金融监督管理总局"
              className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
            />
          </div>
          <div>
            <label htmlFor="topK" className="mb-1.5 block text-xs font-semibold text-muted-fg">
              返回条数
            </label>
            <input
              id="topK"
              type="number"
              min={1}
              max={50}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value) || 10)}
              className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
            />
          </div>
          <div className="flex items-end">
            <label className="inline-flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-xl border border-border bg-white px-3 text-sm">
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
            {loading ? "检索中…" : "检索相似案例"}
          </button>
          {data ? (
            <span className="text-sm text-muted-fg">
              耗时 {data.took_ms} ms · 返回 {data.results.length} 条
            </span>
          ) : null}
        </div>
      </form>

      {error ? <ErrorAlert message={error} /> : null}

      {data ? (
        <section className="space-y-5">
          <div className="surface rounded-2xl p-5">
            <h2 className="font-display text-xl font-semibold">查询解读</h2>
            <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-fg">原始查询</dt>
                <dd className="mt-1 text-foreground">{data.query}</dd>
              </div>
              <div>
                <dt className="text-muted-fg">改写查询</dt>
                <dd className="mt-1 text-foreground">{data.rewritten_query || "—"}</dd>
              </div>
            </dl>
            <div className="mt-4 flex flex-wrap gap-2">
              {data.predicted_risk_ids.map((id) => (
                <TagChip key={id}>{id}</TagChip>
              ))}
              {Object.entries(data.channel_stats).map(([ch, n]) => (
                <span
                  key={ch}
                  className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-fg"
                >
                  {ch}: {n}
                </span>
              ))}
            </div>
          </div>

          {data.results.length === 0 ? (
            <EmptyState
              title="未找到相似案例"
              description="可尝试更具体的违规行为关键词，或先确认案例库已入库并完成向量化。"
            />
          ) : (
            <div className="stagger grid gap-4 lg:grid-cols-2">
              {data.results.map((r) => (
                <CaseCard key={r.case_id} item={r} />
              ))}
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}
