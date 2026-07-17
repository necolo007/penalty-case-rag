import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Search } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { CaseListItem, Paginated } from "../api/types";
import { CaseCard } from "../components/CaseCard";
import { EmptyState, ErrorAlert, LoadingBlock } from "../components/ui";

export function CasesPage() {
  const [searchParams] = useSearchParams();
  const initialRisk = searchParams.get("risk_type") ?? "";
  const [keyword, setKeyword] = useState("");
  const [regulator, setRegulator] = useState("");
  const [riskType, setRiskType] = useState(initialRisk);
  const [insuranceOnly, setInsuranceOnly] = useState(true);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paginated<CaseListItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (p: number, filters?: {
    keyword: string;
    regulator: string;
    riskType: string;
    insuranceOnly: boolean;
  }) => {
    const f = filters ?? {
      keyword,
      regulator,
      riskType,
      insuranceOnly,
    };
    setLoading(true);
    setError(null);
    try {
      const res = await api.listCases({
        page: p,
        page_size: 12,
        keyword: f.keyword.trim() || undefined,
        regulator: f.regulator.trim() || undefined,
        risk_type: f.riskType.trim() || undefined,
        is_insurance_related: f.insuranceOnly ? true : undefined,
      });
      setData(res);
      setPage(p);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载案例失败");
    } finally {
      setLoading(false);
    }
  }, [keyword, regulator, riskType, insuranceOnly]);

  useEffect(() => {
    const fromUrl = searchParams.get("risk_type") ?? "";
    setRiskType(fromUrl);
    void load(1, {
      keyword: "",
      regulator: "",
      riskType: fromUrl,
      insuranceOnly: true,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function onFilter(e: FormEvent) {
    e.preventDefault();
    void load(1);
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="space-y-8">
      <header className="rise-in">
        <h1 className="font-display text-4xl font-bold">处罚案例库</h1>
        <p className="mt-2 text-muted-fg">浏览、筛选和对比已结构化入库的监管处罚案例。</p>
      </header>

      <form
        onSubmit={onFilter}
        className="surface flex flex-col gap-3 rounded-2xl p-4 sm:flex-row sm:flex-wrap sm:items-end"
      >
        <div className="min-w-[200px] flex-1">
          <label htmlFor="kw" className="mb-1 block text-xs font-semibold text-muted-fg">
            关键词
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-fg" />
            <input
              id="kw"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              className="min-h-11 w-full rounded-xl border border-border bg-white pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              placeholder="违规行为全文检索"
            />
          </div>
        </div>
        <div className="w-full sm:w-44">
          <label htmlFor="rt" className="mb-1 block text-xs font-semibold text-muted-fg">
            风险类型
          </label>
          <input
            id="rt"
            value={riskType}
            onChange={(e) => setRiskType(e.target.value)}
            className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
            placeholder="R001"
          />
        </div>
        <div className="w-full sm:w-52">
          <label htmlFor="reg" className="mb-1 block text-xs font-semibold text-muted-fg">
            监管机构
          </label>
          <input
            id="reg"
            value={regulator}
            onChange={(e) => setRegulator(e.target.value)}
            className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
          />
        </div>
        <label className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-white px-3 text-sm">
          <input
            type="checkbox"
            checked={insuranceOnly}
            onChange={(e) => setInsuranceOnly(e.target.checked)}
            className="accent-primary"
          />
          仅保险相关
        </label>
        <button
          type="submit"
          className="min-h-11 rounded-xl bg-primary px-5 text-sm font-semibold text-white hover:bg-primary-deep"
        >
          筛选
        </button>
      </form>

      {error ? <ErrorAlert message={error} /> : null}
      {loading ? <LoadingBlock /> : null}

      {!loading && data && data.items.length === 0 ? (
        <EmptyState title="没有匹配的案例" description="调整筛选条件后再试。" />
      ) : null}

      {!loading && data && data.items.length > 0 ? (
        <>
          <p className="text-sm text-muted-fg">
            共 {data.total} 条 · 第 {data.page}/{totalPages} 页
          </p>
          <div className="stagger grid gap-4 lg:grid-cols-2">
            {data.items.map((item) => (
              <CaseCard key={item.case_id} item={item} />
            ))}
          </div>
          <div className="flex items-center justify-center gap-3">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => void load(page - 1)}
              className="min-h-11 rounded-xl border border-border bg-white px-4 text-sm disabled:opacity-40"
            >
              上一页
            </button>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => void load(page + 1)}
              className="min-h-11 rounded-xl border border-border bg-white px-4 text-sm disabled:opacity-40"
            >
              下一页
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
