import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ArrowDownWideNarrow,
  Download,
  LayoutGrid,
  Search,
  Table2,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { CaseListItem, Paginated } from "../api/types";
import { CaseCard } from "../components/CaseCard";
import { ConfidenceBar } from "../components/ConfidenceBar";
import { RiskTypeChip } from "../components/RiskTypeChip";
import { EmptyState, ErrorAlert, LoadingBlock } from "../components/ui";
import { CN_TAG_NAMES } from "../lib/cnRiskTags";
import { formatDate, truncate } from "../lib/format";

type ViewMode = "table" | "card";
type SortBy = "publish_date" | "fine_amount" | "overall_confidence" | "party_name";

export function CasesPage() {
  const [searchParams] = useSearchParams();
  const initialRisk = searchParams.get("risk_type") ?? "";
  const [keyword, setKeyword] = useState("");
  const [regulator, setRegulator] = useState("");
  const [riskType, setRiskType] = useState(initialRisk);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [insuranceOnly, setInsuranceOnly] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [sortBy, setSortBy] = useState<SortBy>("publish_date");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Paginated<CaseListItem> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);

  const filterParams = useCallback(
    (p: number) => ({
      page: p,
      page_size: viewMode === "table" ? 20 : 12,
      keyword: keyword.trim() || undefined,
      regulator: regulator.trim() || undefined,
      risk_type: riskType.trim() || undefined,
      is_insurance_related: insuranceOnly ? true : undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      sort_by: sortBy,
      sort_order: sortOrder,
    }),
    [keyword, regulator, riskType, insuranceOnly, dateFrom, dateTo, sortBy, sortOrder, viewMode],
  );

  const load = useCallback(
    async (p: number, overrides?: Partial<ReturnType<typeof filterParams>>) => {
      setLoading(true);
      setError(null);
      try {
        const params = { ...filterParams(p), ...overrides };
        const res = await api.listCases(params);
        setData(res);
        setPage(p);
        setSelected(new Set());
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "加载案例失败");
      } finally {
        setLoading(false);
      }
    },
    [filterParams],
  );

  useEffect(() => {
    const fromUrl = searchParams.get("risk_type") ?? "";
    setRiskType(fromUrl);
    void load(1, {
      keyword: undefined,
      regulator: undefined,
      risk_type: fromUrl || undefined,
      is_insurance_related: true,
      date_from: undefined,
      date_to: undefined,
      page: 1,
      page_size: 20,
      sort_by: "publish_date",
      sort_order: "desc",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function onFilter(e: FormEvent) {
    e.preventDefault();
    void load(1);
  }

  function toggleSort(col: SortBy) {
    const nextOrder =
      sortBy === col ? (sortOrder === "desc" ? "asc" : "desc") : col === "party_name" ? "asc" : "desc";
    setSortBy(col);
    setSortOrder(nextOrder);
    void load(1, { sort_by: col, sort_order: nextOrder, page: 1 });
  }

  function switchView(mode: ViewMode) {
    if (mode === viewMode) return;
    setViewMode(mode);
    void load(1, { page: 1, page_size: mode === "table" ? 20 : 12 });
  }

  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (!data) return;
    const ids = data.items.map((i) => i.case_id);
    const allSelected = ids.length > 0 && ids.every((id) => selected.has(id));
    setSelected(allSelected ? new Set() : new Set(ids));
  }

  async function onExport(format: "csv" | "xlsx") {
    setExporting(true);
    setError(null);
    try {
      await api.exportCasesTable(
        {
          keyword: keyword.trim() || undefined,
          regulator: regulator.trim() || undefined,
          risk_type: riskType.trim() || undefined,
          is_insurance_related: insuranceOnly ? true : undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          sort_by: sortBy,
          sort_order: sortOrder,
          case_ids: selected.size ? Array.from(selected).join(",") : undefined,
        },
        format,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "导出失败");
    } finally {
      setExporting(false);
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const pageIds = data?.items.map((i) => i.case_id) ?? [];
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selected.has(id));

  function SortHeader({
    col,
    label,
  }: {
    col: SortBy;
    label: string;
  }) {
    const active = sortBy === col;
    return (
      <button
        type="button"
        onClick={() => toggleSort(col)}
        className="inline-flex items-center gap-1 font-semibold hover:text-foreground"
      >
        {label}
        <ArrowDownWideNarrow
          className={[
            "h-3.5 w-3.5 transition",
            active ? "text-primary opacity-100" : "opacity-30",
            active && sortOrder === "asc" ? "rotate-180" : "",
          ].join(" ")}
          aria-hidden
        />
        <span className="sr-only">
          {active ? (sortOrder === "desc" ? "降序" : "升序") : "排序"}
        </span>
      </button>
    );
  }

  return (
    <div className="space-y-8">
      <header className="rise-in flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-4xl font-bold">处罚案例库</h1>
          <p className="mt-2 text-muted-fg">
            浏览、筛选和对比已结构化入库的监管处罚案例；支持表格 / 卡片视图与批量导出。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-xl border border-border bg-white p-1" role="group" aria-label="视图切换">
            <button
              type="button"
              aria-pressed={viewMode === "table"}
              onClick={() => switchView("table")}
              className={[
                "inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold transition",
                viewMode === "table" ? "bg-primary text-white" : "text-muted-fg hover:text-foreground",
              ].join(" ")}
            >
              <Table2 className="h-4 w-4" />
              表格
            </button>
            <button
              type="button"
              aria-pressed={viewMode === "card"}
              onClick={() => switchView("card")}
              className={[
                "inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold transition",
                viewMode === "card" ? "bg-primary text-white" : "text-muted-fg hover:text-foreground",
              ].join(" ")}
            >
              <LayoutGrid className="h-4 w-4" />
              卡片
            </button>
          </div>
          <button
            type="button"
            disabled={exporting}
            onClick={() => void onExport("csv")}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-white px-3 text-sm font-medium hover:bg-muted disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {selected.size ? `导出 CSV（${selected.size}）` : "导出 CSV"}
          </button>
          <button
            type="button"
            disabled={exporting}
            onClick={() => void onExport("xlsx")}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-3 text-sm font-semibold text-white hover:bg-primary-deep disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {selected.size ? `导出 Excel（${selected.size}）` : "导出 Excel"}
          </button>
        </div>
      </header>

      <form
        onSubmit={onFilter}
        className="surface flex flex-col gap-3 rounded-2xl p-4 sm:flex-row sm:flex-wrap sm:items-end"
      >
        <div className="min-w-[180px] flex-1">
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
        <div className="w-full sm:w-52">
          <label htmlFor="rt" className="mb-1 block text-xs font-semibold text-muted-fg">
            风险类型（27类）
          </label>
          <select
            id="rt"
            value={riskType}
            onChange={(e) => setRiskType(e.target.value)}
            className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
          >
            <option value="">全部</option>
            {CN_TAG_NAMES.map((tag) => (
              <option key={tag} value={tag}>
                {tag}
              </option>
            ))}
          </select>
        </div>
        <div className="w-full sm:w-44">
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
        <div className="w-full sm:w-36">
          <label htmlFor="df" className="mb-1 block text-xs font-semibold text-muted-fg">
            发布日期起
          </label>
          <input
            id="df"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
          />
        </div>
        <div className="w-full sm:w-36">
          <label htmlFor="dt" className="mb-1 block text-xs font-semibold text-muted-fg">
            发布日期止
          </label>
          <input
            id="dt"
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
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
            {selected.size ? ` · 已选 ${selected.size} 条` : ""}
          </p>

          {viewMode === "card" ? (
            <div className="stagger grid gap-4 lg:grid-cols-2">
              {data.items.map((item) => (
                <CaseCard key={item.case_id} item={item} />
              ))}
            </div>
          ) : (
            <div className="surface overflow-x-auto rounded-2xl">
              <table className="w-full min-w-[1100px] text-left text-sm">
                <thead className="border-b border-border bg-muted/60 text-xs text-muted-fg">
                  <tr>
                    <th className="px-3 py-3">
                      <input
                        type="checkbox"
                        checked={allPageSelected}
                        onChange={toggleAll}
                        aria-label="全选本页"
                        className="accent-primary"
                      />
                    </th>
                    <th className="px-3 py-3">
                      <SortHeader col="party_name" label="当事人" />
                    </th>
                    <th className="px-3 py-3 font-semibold">文号</th>
                    <th className="px-3 py-3 font-semibold">违规类型</th>
                    <th className="px-3 py-3 font-semibold">监管机构</th>
                    <th className="px-3 py-3">
                      <SortHeader col="fine_amount" label="处罚金额" />
                    </th>
                    <th className="px-3 py-3">
                      <SortHeader col="publish_date" label="发布日期" />
                    </th>
                    <th className="px-3 py-3">
                      <SortHeader col="overall_confidence" label="置信度" />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => {
                    const tags =
                      item.risk_tags?.length
                        ? item.risk_tags
                        : item.risk_type_ids ?? [];
                    return (
                      <tr
                        key={item.case_id}
                        className="border-b border-border/60 last:border-0 hover:bg-slate-50/80"
                      >
                        <td className="px-3 py-3">
                          <input
                            type="checkbox"
                            checked={selected.has(item.case_id)}
                            onChange={() => toggleOne(item.case_id)}
                            aria-label={`选择 ${item.party_name || item.case_id}`}
                            className="accent-primary"
                          />
                        </td>
                        <td className="px-3 py-3">
                          <Link
                            to={`/cases/${encodeURIComponent(item.case_id)}`}
                            className="font-medium text-foreground no-underline hover:text-primary"
                          >
                            {item.party_name || "未知当事人"}
                          </Link>
                          <div className="mt-0.5 font-mono text-[11px] text-muted-fg">
                            {item.case_id}
                          </div>
                          <p className="mt-1 max-w-xs text-xs text-slate-600">
                            {truncate(item.violation_behavior, 80)}
                          </p>
                        </td>
                        <td className="px-3 py-3 text-muted-fg">
                          {item.penalty_doc_no || "—"}
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex max-w-[14rem] flex-wrap gap-1">
                            {tags.length
                              ? tags.slice(0, 4).map((t) => (
                                  <RiskTypeChip key={t} idOrTag={t} />
                                ))
                              : "—"}
                          </div>
                        </td>
                        <td className="px-3 py-3 text-muted-fg">
                          {item.regulator || "—"}
                        </td>
                        <td className="px-3 py-3 font-medium tabular-nums">
                          {item.fine_amount || "—"}
                        </td>
                        <td className="px-3 py-3 text-muted-fg tabular-nums">
                          {formatDate(item.publish_date)}
                        </td>
                        <td className="px-3 py-3">
                          <ConfidenceBar value={item.overall_confidence} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="border-t border-border bg-sky-50/60 px-4 py-3 text-xs leading-relaxed text-sky-900">
                表格视图可一次浏览当事人、文号、违规类型、处罚金额、置信度等字段；支持按金额排序、勾选批量导出。
              </div>
            </div>
          )}

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
