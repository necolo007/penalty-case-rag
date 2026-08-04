import { useEffect, type FormEvent } from "react";
import {
  ArrowDownWideNarrow,
  Download,
  LayoutGrid,
  Search,
  Table2,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { CaseCard } from "../components/CaseCard";
import { ConfidenceBar } from "../components/ConfidenceBar";
import { RiskTypeChip } from "../components/RiskTypeChip";
import { EmptyState, ErrorAlert, LoadingBlock } from "../components/ui";
import { CN_TAG_NAMES } from "../lib/cnRiskTags";
import {
  casesSession,
  useCasesSession,
  type CasesSortBy,
} from "../lib/casesSession";
import { formatDate, truncate } from "../lib/format";

export function CasesPage() {
  const s = useCasesSession();
  const [searchParams] = useSearchParams();

  useEffect(() => {
    casesSession.ensureLoaded(searchParams.get("risk_type"));
  }, [searchParams]);

  function onFilter(e: FormEvent) {
    e.preventDefault();
    void casesSession.load(1);
  }

  const totalPages = s.data ? Math.max(1, Math.ceil(s.data.total / s.data.page_size)) : 1;
  const pageIds = s.data?.items.map((i) => i.case_id) ?? [];
  const selectedSet = new Set(s.selected);
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedSet.has(id));

  function SortHeader({
    col,
    label,
  }: {
    col: CasesSortBy;
    label: string;
  }) {
    const active = s.sortBy === col;
    return (
      <button
        type="button"
        onClick={() => casesSession.toggleSort(col)}
        className="inline-flex items-center gap-1 font-semibold hover:text-foreground"
      >
        {label}
        <ArrowDownWideNarrow
          className={[
            "h-3.5 w-3.5 transition",
            active ? "text-primary opacity-100" : "opacity-30",
            active && s.sortOrder === "asc" ? "rotate-180" : "",
          ].join(" ")}
          aria-hidden
        />
        <span className="sr-only">
          {active ? (s.sortOrder === "desc" ? "降序" : "升序") : "排序"}
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
              aria-pressed={s.viewMode === "table"}
              onClick={() => casesSession.switchView("table")}
              className={[
                "inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold transition",
                s.viewMode === "table" ? "bg-primary text-white" : "text-muted-fg hover:text-foreground",
              ].join(" ")}
            >
              <Table2 className="h-4 w-4" />
              表格
            </button>
            <button
              type="button"
              aria-pressed={s.viewMode === "card"}
              onClick={() => casesSession.switchView("card")}
              className={[
                "inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold transition",
                s.viewMode === "card" ? "bg-primary text-white" : "text-muted-fg hover:text-foreground",
              ].join(" ")}
            >
              <LayoutGrid className="h-4 w-4" />
              卡片
            </button>
          </div>
          <button
            type="button"
            disabled={s.exporting}
            onClick={() => void casesSession.exportTable("csv")}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-white px-3 text-sm font-medium hover:bg-muted disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {s.selected.length ? `导出 CSV（${s.selected.length}）` : "导出 CSV"}
          </button>
          <button
            type="button"
            disabled={s.exporting}
            onClick={() => void casesSession.exportTable("xlsx")}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-3 text-sm font-semibold text-white hover:bg-primary-deep disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {s.selected.length ? `导出 Excel（${s.selected.length}）` : "导出 Excel"}
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
              value={s.keyword}
              onChange={(e) => casesSession.setKeyword(e.target.value)}
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
            value={s.riskType}
            onChange={(e) => casesSession.setRiskType(e.target.value)}
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
            value={s.regulator}
            onChange={(e) => casesSession.setRegulator(e.target.value)}
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
            value={s.dateFrom}
            onChange={(e) => casesSession.setDateFrom(e.target.value)}
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
            value={s.dateTo}
            onChange={(e) => casesSession.setDateTo(e.target.value)}
            className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
          />
        </div>
        <label className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-white px-3 text-sm">
          <input
            type="checkbox"
            checked={s.insuranceOnly}
            onChange={(e) => casesSession.setInsuranceOnly(e.target.checked)}
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

      {s.error ? <ErrorAlert message={s.error} /> : null}
      {s.loading ? <LoadingBlock /> : null}

      {!s.loading && s.data && s.data.items.length === 0 ? (
        <EmptyState title="没有匹配的案例" description="调整筛选条件后再试。" />
      ) : null}

      {!s.loading && s.data && s.data.items.length > 0 ? (
        <>
          <p className="text-sm text-muted-fg">
            共 {s.data.total} 条 · 第 {s.data.page}/{totalPages} 页
            {s.selected.length ? ` · 已选 ${s.selected.length} 条` : ""}
          </p>

          {s.viewMode === "card" ? (
            <div className="stagger grid gap-4 lg:grid-cols-2">
              {s.data.items.map((item) => (
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
                        onChange={() => casesSession.toggleAllPage()}
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
                  {s.data.items.map((item) => {
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
                            checked={selectedSet.has(item.case_id)}
                            onChange={() => casesSession.toggleOne(item.case_id)}
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
              disabled={s.page <= 1}
              onClick={() => void casesSession.load(s.page - 1)}
              className="min-h-11 rounded-xl border border-border bg-white px-4 text-sm disabled:opacity-40"
            >
              上一页
            </button>
            <button
              type="button"
              disabled={s.page >= totalPages}
              onClick={() => void casesSession.load(s.page + 1)}
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
