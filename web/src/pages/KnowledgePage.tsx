import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowDownWideNarrow,
  Check,
  Download,
  FileUp,
  LayoutGrid,
  Loader2,
  RefreshCw,
  Search,
  Table2,
  X,
} from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { CaseQueue, StatsResponse } from "../api/types";
import { CaseCard } from "../components/CaseCard";
import {
  IngestTaskCard,
  IngestUploadPanel,
  IngestWorkflowFooter,
} from "../components/IngestTaskPanel";
import { RiskTypeChip } from "../components/RiskTypeChip";
import { UploadDocumentDrawer } from "../components/UploadDocumentDrawer";
import { EmptyState, ErrorAlert, LoadingBlock } from "../components/ui";
import { CN_TAG_NAMES } from "../lib/cnRiskTags";
import {
  casesSession,
  useCasesSession,
  type CasesSortBy,
} from "../lib/casesSession";
import { formatDate, truncate } from "../lib/format";
import { useIngestLive } from "../lib/useIngestLive";

type MainView = "queue" | "ingest";

function formatCount(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("zh-CN");
}

function formatRate(rate: number | null | undefined): string {
  if (rate == null || Number.isNaN(rate)) return "—";
  return `${(rate * 100).toFixed(0)}%`;
}

export function KnowledgePage() {
  const s = useCasesSession();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const view = (searchParams.get("view") === "ingest" ? "ingest" : "queue") as MainView;
  const [uploadOpen, setUploadOpen] = useState(false);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [docStatus, setDocStatus] = useState("");
  const [docPage, setDocPage] = useState(1);
  const [docBusy, setDocBusy] = useState<string | null>(null);

  const ingest = useIngestLive({
    enabled: view === "ingest",
    page: docPage,
    parseStatus: docStatus,
  });
  const {
    docs,
    loading: docLoading,
    error: docError,
    setError: setDocError,
    nowMs,
    live: ingestLive,
    lastSyncAt,
    reload: loadDocs,
  } = ingest;

  const refreshStats = useCallback(() => {
    void api.stats().then(setStats).catch(() => setStats(null));
  }, []);

  useEffect(() => {
    casesSession.syncFromUrl({
      risk_type: searchParams.get("risk_type"),
      queue: searchParams.get("queue"),
      file_id: searchParams.get("file_id"),
    });
  }, [searchParams]);

  useEffect(() => {
    refreshStats();
  }, [refreshStats, s.data]);

  // 进行中任务全部结束后，刷新顶栏统计
  const wasIngestLive = useRef(false);
  useEffect(() => {
    if (wasIngestLive.current && !ingestLive) {
      refreshStats();
    }
    wasIngestLive.current = ingestLive;
  }, [ingestLive, refreshStats]);

  useEffect(() => {
    if (!s.toast) return;
    const t = window.setTimeout(() => casesSession.clearToast(), 2800);
    return () => window.clearTimeout(t);
  }, [s.toast]);

  function setView(next: MainView) {
    const sp = new URLSearchParams(searchParams);
    sp.set("view", next);
    if (next === "queue" && !sp.get("queue")) sp.set("queue", s.queue || "confirmed");
    setSearchParams(sp, { replace: true });
  }

  function setQueueTab(q: CaseQueue) {
    const sp = new URLSearchParams(searchParams);
    sp.set("view", "queue");
    sp.set("queue", q);
    setSearchParams(sp, { replace: true });
    casesSession.switchQueue(q);
  }

  function onFilter(e: FormEvent) {
    e.preventDefault();
    void casesSession.load(1);
  }

  function clearFileFilter() {
    casesSession.setFileId("");
    const sp = new URLSearchParams(searchParams);
    sp.delete("file_id");
    setSearchParams(sp, { replace: true });
    void casesSession.load(1, { file_id: "", page: 1 });
  }

  function openGeneratedCases(fileId: string) {
    const sp = new URLSearchParams();
    sp.set("view", "queue");
    sp.set("queue", "all");
    sp.set("file_id", fileId);
    navigate(`/knowledge?${sp.toString()}`);
  }

  async function onRetry(fileId: string) {
    setDocBusy(fileId);
    try {
      await api.retryDocument(fileId);
      await loadDocs(docPage);
    } catch (err) {
      setDocError(err instanceof ApiError ? err.message : "重试失败");
    } finally {
      setDocBusy(null);
    }
  }

  async function onDeleteDoc(fileId: string) {
    if (!window.confirm("确认删除该文档及其关联案例？")) return;
    setDocBusy(fileId);
    try {
      await api.deleteDocument(fileId);
      await loadDocs(docPage);
      refreshStats();
    } catch (err) {
      setDocError(err instanceof ApiError ? err.message : "删除失败");
    } finally {
      setDocBusy(null);
    }
  }

  function changeDocStatus(st: string) {
    setDocStatus(st);
    setDocPage(1);
  }

  function goDocPage(p: number) {
    setDocPage(p);
  }

  const totalPages = s.data ? Math.max(1, Math.ceil(s.data.total / s.data.page_size)) : 1;
  const pageIds = s.data?.items.map((i) => i.case_id) ?? [];
  const selectedSet = new Set(s.selected);
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedSet.has(id));
  const docTotalPages = docs ? Math.max(1, Math.ceil(docs.total / docs.page_size)) : 1;

  const queueTabs: Array<{ id: CaseQueue; label: string; count: number | null | undefined }> = [
    { id: "confirmed", label: "已确认保险", count: stats?.confirmed_insurance_cases ?? stats?.insurance_cases },
    { id: "pending", label: "待复核候选", count: stats?.pending_insurance_cases },
    { id: "excluded", label: "已排除", count: stats?.excluded_cases },
  ];

  function SortHeader({ col, label }: { col: CasesSortBy; label: string }) {
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
      </button>
    );
  }

  return (
    <div className="space-y-6">
      <header className="rise-in flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-4xl font-bold">案例知识库</h1>
          <p className="mt-2 max-w-2xl text-muted-fg">
            从处罚文书上传、结构化解析到保险案例筛选、标签归类与人工复核。
          </p>
        </div>
        <button
          type="button"
          onClick={() => setUploadOpen(true)}
          className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-accent px-4 text-sm font-semibold text-white shadow-sm transition duration-200 hover:brightness-110"
        >
          <FileUp className="h-4 w-4" />
          上传处罚文书
        </button>
      </header>

      <div className="border-b border-border" role="tablist" aria-label="知识库主视图">
        <div className="flex gap-1">
          {(
            [
              ["queue", "案例队列"],
              ["ingest", "入库任务"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={view === id}
              onClick={() => setView(id)}
              className={[
                "relative min-h-11 px-4 text-sm font-semibold transition duration-200",
                view === id
                  ? "text-primary"
                  : "text-muted-fg hover:text-foreground",
              ].join(" ")}
            >
              {label}
              {view === id ? (
                <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />
              ) : null}
            </button>
          ))}
        </div>
      </div>

      {s.toast ? (
        <p className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800" role="status">
          {s.toast}
        </p>
      ) : null}

      {view === "queue" ? (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["总案例数", formatCount(stats?.cases)],
              ["保险相关案例数", formatCount(stats?.insurance_cases)],
              ["待审核案例数", formatCount(stats?.pending_insurance_cases)],
              ["风险标签覆盖率", formatRate(stats?.tag_coverage_rate)],
            ].map(([label, value]) => (
              <div
                key={label}
                className="surface rounded-2xl px-4 py-4 transition duration-200 hover:shadow-[var(--shadow-lift)]"
              >
                <p className="text-xs font-semibold tracking-wide text-muted-fg">{label}</p>
                <p className="mt-1.5 font-display text-3xl font-bold tabular-nums text-foreground">
                  {value}
                </p>
              </div>
            ))}
          </section>

          <div className="flex flex-wrap items-center gap-2">
            {queueTabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setQueueTab(tab.id)}
                className={[
                  "inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-sm font-semibold ring-1 transition",
                  s.queue === tab.id
                    ? "bg-primary text-white ring-primary"
                    : "bg-white text-foreground ring-border hover:bg-muted",
                ].join(" ")}
              >
                {tab.label}
                <span
                  className={[
                    "rounded-full px-2 py-0.5 text-xs tabular-nums",
                    s.queue === tab.id ? "bg-white/20" : "bg-muted text-muted-fg",
                  ].join(" ")}
                >
                  {formatCount(tab.count)}
                </span>
              </button>
            ))}
            <button
              type="button"
              onClick={() => setQueueTab("all")}
              className={[
                "min-h-11 rounded-full px-3 text-xs font-medium ring-1 transition",
                s.queue === "all"
                  ? "bg-slate-800 text-white ring-slate-800"
                  : "bg-white text-muted-fg ring-border hover:text-foreground",
              ].join(" ")}
            >
              全部案例
            </button>
            {s.fileId ? (
              <button
                type="button"
                onClick={clearFileFilter}
                className="inline-flex min-h-11 items-center gap-1 rounded-full bg-amber-50 px-3 text-xs font-medium text-amber-900 ring-1 ring-amber-200"
              >
                文档筛选：{s.fileId}
                <X className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>

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
                风险类型
              </label>
              <select
                id="rt"
                value={s.riskType}
                onChange={(e) => casesSession.setRiskType(e.target.value)}
                className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              >
                <option value="">全部</option>
                {CN_TAG_NAMES.map((t) => (
                  <option key={t} value={t}>
                    {t}
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
                日期起
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
                日期止
              </label>
              <input
                id="dt"
                type="date"
                value={s.dateTo}
                onChange={(e) => casesSession.setDateTo(e.target.value)}
                className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              />
            </div>
            <button
              type="submit"
              className="min-h-11 rounded-xl bg-primary px-5 text-sm font-semibold text-white hover:bg-primary-deep"
            >
              筛选
            </button>
            <div className="ml-auto flex flex-wrap gap-2">
              <div className="inline-flex rounded-xl border border-border bg-white p-1">
                <button
                  type="button"
                  aria-pressed={s.viewMode === "table"}
                  onClick={() => casesSession.switchView("table")}
                  className={[
                    "inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold",
                    s.viewMode === "table" ? "bg-primary text-white" : "text-muted-fg",
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
                    "inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold",
                    s.viewMode === "card" ? "bg-primary text-white" : "text-muted-fg",
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
                CSV
              </button>
            </div>
          </form>

          {s.error ? <ErrorAlert message={s.error} /> : null}
          {s.loading && !s.data ? <LoadingBlock label="加载案例队列…" /> : null}
          {!s.loading && s.data && s.data.items.length === 0 ? (
            <EmptyState title="当前队列暂无案例" description="可切换队列，或上传文书后在入库任务中查看进度。" />
          ) : null}

          {s.data && s.data.items.length > 0 ? (
            s.viewMode === "card" ? (
              <div className="stagger grid gap-4 lg:grid-cols-2">
                {s.data.items.map((item) => (
                  <div key={item.case_id} className="space-y-2">
                    <CaseCard item={item} />
                    {(s.queue === "pending" || item.is_insurance_candidate) &&
                    !item.is_insurance_related ? (
                      <div className="rounded-2xl border border-amber-200 bg-amber-50/70 p-4">
                        <p className="text-xs font-semibold text-amber-900">候选原因</p>
                        <ul className="mt-2 space-y-1 text-sm text-amber-950">
                          {(item.candidate_reasons || []).length
                            ? (item.candidate_reasons || []).map((r) => (
                                <li key={r} className="flex gap-2">
                                  <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
                                  {r}
                                </li>
                              ))
                            : (
                              <li className="text-muted-fg">暂无命中说明</li>
                            )}
                        </ul>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <button
                            type="button"
                            disabled={s.actionBusyId === item.case_id}
                            onClick={() => void casesSession.confirm(item.case_id)}
                            className="inline-flex min-h-11 items-center gap-1 rounded-xl bg-primary px-3 text-sm font-semibold text-white disabled:opacity-50"
                          >
                            {s.actionBusyId === item.case_id ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : null}
                            确认保险
                          </button>
                          <button
                            type="button"
                            disabled={s.actionBusyId === item.case_id}
                            onClick={() => void casesSession.exclude(item.case_id)}
                            className="min-h-11 rounded-xl border border-border bg-white px-3 text-sm font-medium disabled:opacity-50"
                          >
                            排除
                          </button>
                          <Link
                            to={`/cases/${encodeURIComponent(item.case_id)}`}
                            className="inline-flex min-h-11 items-center rounded-xl border border-border bg-white px-3 text-sm font-medium no-underline"
                          >
                            查看详情
                          </Link>
                        </div>
                      </div>
                    ) : null}
                  </div>
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
                      <th className="px-3 py-3 font-semibold">状态 / 原因</th>
                      <th className="px-3 py-3">
                        <SortHeader col="publish_date" label="日期" />
                      </th>
                      <th className="px-3 py-3 font-semibold">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.data.items.map((item) => {
                      const tags = item.risk_tags?.length
                        ? item.risk_tags
                        : item.risk_type_ids ?? [];
                      const pending =
                        Boolean(item.is_insurance_candidate) && !item.is_insurance_related;
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
                          <td className="px-3 py-3 text-xs">
                            {item.is_insurance_related ? (
                              <span className="rounded-md bg-emerald-50 px-2 py-1 font-medium text-emerald-800 ring-1 ring-emerald-200">
                                已入库
                              </span>
                            ) : pending ? (
                              <div>
                                <span className="rounded-md bg-amber-50 px-2 py-1 font-medium text-amber-900 ring-1 ring-amber-200">
                                  待复核
                                </span>
                                <p className="mt-1 max-w-[14rem] text-muted-fg">
                                  {(item.candidate_reasons || []).slice(0, 2).join("；") || "等待人工确认"}
                                </p>
                              </div>
                            ) : (
                              <div>
                                <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-700 ring-1 ring-slate-200">
                                  已排除
                                </span>
                                <p className="mt-1 max-w-[14rem] text-muted-fg">
                                  {(item.candidate_reasons || []).slice(0, 2).join("；") || "—"}
                                </p>
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-3 text-muted-fg tabular-nums">
                            {formatDate(item.publish_date)}
                          </td>
                          <td className="px-3 py-3">
                            <div className="flex flex-wrap gap-1.5">
                              {pending ? (
                                <>
                                  <button
                                    type="button"
                                    disabled={s.actionBusyId === item.case_id}
                                    onClick={() => void casesSession.confirm(item.case_id)}
                                    className="min-h-11 rounded-lg bg-primary px-2.5 text-xs font-semibold text-white disabled:opacity-50"
                                  >
                                    确认
                                  </button>
                                  <button
                                    type="button"
                                    disabled={s.actionBusyId === item.case_id}
                                    onClick={() => void casesSession.exclude(item.case_id)}
                                    className="min-h-11 rounded-lg border border-border px-2.5 text-xs font-medium disabled:opacity-50"
                                  >
                                    排除
                                  </button>
                                </>
                              ) : null}
                              <Link
                                to={`/cases/${encodeURIComponent(item.case_id)}`}
                                className="inline-flex min-h-11 items-center rounded-lg border border-border px-2.5 text-xs font-medium no-underline"
                              >
                                详情
                              </Link>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )
          ) : null}

          {s.data && s.data.total > 0 ? (
            <div className="flex items-center justify-center gap-3">
              <button
                type="button"
                disabled={s.page <= 1 || s.loading}
                onClick={() => void casesSession.load(s.page - 1)}
                className="min-h-11 rounded-xl border border-border bg-white px-4 text-sm disabled:opacity-40"
              >
                上一页
              </button>
              <span className="text-sm text-muted-fg tabular-nums">
                {s.page} / {totalPages}（共 {s.data.total}）
              </span>
              <button
                type="button"
                disabled={s.page >= totalPages || s.loading}
                onClick={() => void casesSession.load(s.page + 1)}
                className="min-h-11 rounded-xl border border-border bg-white px-4 text-sm disabled:opacity-40"
              >
                下一页
              </button>
            </div>
          ) : null}
        </>
      ) : (
        <div className="space-y-5">
          <IngestUploadPanel
            onOpenDrawer={() => setUploadOpen(true)}
            onUploaded={() => {
              setDocPage(1);
              void loadDocs(1);
              refreshStats();
            }}
          />

          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-display text-xl font-semibold">解析任务</h2>
                  {ingestLive ? (
                    <span
                      className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-900 ring-1 ring-amber-200"
                      role="status"
                      aria-live="polite"
                    >
                      <span className="relative flex h-1.5 w-1.5">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-70" />
                        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-amber-500" />
                      </span>
                      自动刷新中
                    </span>
                  ) : null}
                </div>
                <p className="mt-0.5 text-xs text-muted-fg">
                  全部 {docs?.total ?? "—"} · 跟踪上传、解析与案例分类结果
                  {lastSyncAt ? (
                    <span className="ml-1 tabular-nums text-muted-fg/80">
                      · 同步{" "}
                      {new Date(lastSyncAt).toLocaleTimeString("zh-CN", {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })}
                    </span>
                  ) : null}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {(
                  [
                    ["", "全部"],
                    ["parsing", "处理中"],
                    ["done", "已完成"],
                    ["failed", "异常"],
                    ["pending", "排队"],
                  ] as const
                ).map(([st, label]) => (
                  <button
                    key={st || "all"}
                    type="button"
                    onClick={() => changeDocStatus(st)}
                    className={[
                      "min-h-11 rounded-full px-3.5 text-xs font-semibold ring-1 transition duration-200",
                      docStatus === st
                        ? "bg-primary text-white ring-primary"
                        : "bg-white text-muted-fg ring-border hover:text-foreground",
                    ].join(" ")}
                  >
                    {label}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => void loadDocs(docPage)}
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-border bg-white px-3 text-sm font-medium hover:bg-muted"
                >
                  <RefreshCw className={`h-4 w-4 ${docLoading ? "animate-spin" : ""}`} />
                  刷新
                </button>
              </div>
            </div>

            {docError ? <ErrorAlert message={docError} /> : null}
            {docLoading && !docs ? <LoadingBlock label="加载入库任务…" /> : null}
            {!docLoading && docs && docs.items.length === 0 ? (
              <EmptyState
                title="暂无解析任务"
                description="拖拽文件到上方上传区，或点击右上角「上传处罚文书」。"
              />
            ) : null}

            <div className="grid gap-4" aria-busy={docLoading && Boolean(docs)}>
              {docs?.items.map((d) => (
                <IngestTaskCard
                  key={d.file_id}
                  doc={d}
                  nowMs={nowMs}
                  busy={docBusy === d.file_id}
                  onViewCases={openGeneratedCases}
                  onRetry={(id) => void onRetry(id)}
                  onDelete={(id) => void onDeleteDoc(id)}
                />
              ))}
            </div>

            {docs && docs.total > 0 ? (
              <div className="flex items-center justify-center gap-3 pt-1">
                <button
                  type="button"
                  disabled={docPage <= 1 || docLoading}
                  onClick={() => goDocPage(docPage - 1)}
                  className="min-h-11 rounded-xl border border-border bg-white px-4 text-sm disabled:opacity-40"
                >
                  上一页
                </button>
                <span className="text-sm text-muted-fg tabular-nums">
                  {docPage} / {docTotalPages}
                </span>
                <button
                  type="button"
                  disabled={docPage >= docTotalPages || docLoading}
                  onClick={() => goDocPage(docPage + 1)}
                  className="min-h-11 rounded-xl border border-border bg-white px-4 text-sm disabled:opacity-40"
                >
                  下一页
                </button>
              </div>
            ) : null}
          </section>

          <IngestWorkflowFooter />
        </div>
      )}

      <UploadDocumentDrawer
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={() => {
          setUploadOpen(false);
          setView("ingest");
          setDocPage(1);
          void loadDocs(1);
          refreshStats();
        }}
      />
    </div>
  );
}
