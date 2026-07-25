import { useCallback, useEffect, useId, useRef, useState, type DragEvent } from "react";
import {
  Eye,
  FileUp,
  Loader2,
  RefreshCw,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { api, ApiError } from "../api/client";
import type { DocumentItem, ExtractedCaseSummary, Paginated } from "../api/types";
import { formatConfidencePct, normalizeConfidence } from "../lib/confidence";
import { formatDate, statusLabel } from "../lib/format";
import { ConfidenceBar } from "../components/ConfidenceBar";
import { RiskTypeChip } from "../components/RiskTypeChip";
import { EmptyState, ErrorAlert, LoadingBlock, StatusBadge } from "../components/ui";

type QueuedFile = {
  id: string;
  file: File;
};

const ACCEPT = ".pdf,.docx,.html,.htm";
const ACCEPT_MIME = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/html",
];

function isAccepted(file: File): boolean {
  const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
  return [".pdf", ".docx", ".html", ".htm"].includes(ext) || ACCEPT_MIME.includes(file.type);
}

function fieldConfidenceLabel(
  confidences: Record<string, string | number> | null | undefined,
  key: string,
): string | null {
  if (!confidences || confidences[key] == null) return null;
  return formatConfidencePct(confidences[key]);
}

function ExtractedFields({ cases }: { cases: ExtractedCaseSummary[] }) {
  if (!cases.length) {
    return (
      <p className="mt-3 rounded-xl bg-muted/60 px-3 py-3 text-sm text-muted-fg">
        尚无结构化抽取结果。解析完成后将展示当事人、文号、违规行为等字段。
      </p>
    );
  }

  return (
    <div className="mt-3 space-y-4">
      {cases.map((c) => (
        <div key={c.case_id} className="rounded-xl border border-border/80 bg-slate-50/80 p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="font-mono text-xs text-muted-fg">{c.case_id}</span>
            <ConfidenceBar value={c.overall_confidence} className="max-w-[10rem]" />
          </div>
          <dl className="space-y-2.5 text-sm">
            {(
              [
                ["当事人", c.party_name, "party_name"],
                ["文号", c.penalty_doc_no, "penalty_doc_no"],
                ["违规行为", c.violation_behavior, "violation_behavior"],
                ["处罚内容", c.penalty_content || c.fine_amount, "penalty_content"],
                ["监管机构", c.regulator, "regulator"],
                ["法律依据", c.legal_basis, "legal_basis"],
              ] as const
            ).map(([label, value, key]) => {
              const fc = fieldConfidenceLabel(c.field_confidences, key);
              return (
                <div key={key} className="rounded-lg border border-border/60 bg-white px-3 py-2">
                  <dt className="text-xs text-muted-fg">{label}</dt>
                  <dd className="mt-0.5 flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-medium text-foreground">{value || "—"}</span>
                    {fc ? (
                      <span className="text-xs font-medium text-amber-700">置信度 {fc}</span>
                    ) : null}
                  </dd>
                </div>
              );
            })}
          </dl>
          {(c.risk_tags?.length || c.risk_type_ids?.length) ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {(c.risk_tags?.length ? c.risk_tags : c.risk_type_ids ?? []).map((t) => (
                <RiskTypeChip key={t} idOrTag={t} />
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function DocumentsPage() {
  const inputId = useId();
  const [data, setData] = useState<Paginated<DocumentItem> | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [regulator, setRegulator] = useState("");
  const [publishDate, setPublishDate] = useState("");
  const [queue, setQueue] = useState<QueuedFile[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [detail, setDetail] = useState<DocumentItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const queueIdRef = useRef(0);

  const load = useCallback(
    async (p = 1) => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.listDocuments({
          page: p,
          page_size: 15,
          parse_status: statusFilter || undefined,
        });
        setData(res);
        setPage(p);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "加载文档失败");
      } finally {
        setLoading(false);
      }
    },
    [statusFilter],
  );

  useEffect(() => {
    void load(1);
  }, [load]);

  function addFiles(fileList: FileList | File[] | null) {
    if (!fileList) return;
    const incoming = Array.from(fileList).filter(isAccepted);
    if (!incoming.length) {
      setError("请选择 PDF / DOCX / HTML 文件");
      return;
    }
    setError(null);
    setQueue((prev) => {
      const next = [...prev];
      for (const file of incoming) {
        const dup = next.some(
          (q) => q.file.name === file.name && q.file.size === file.size,
        );
        if (dup) continue;
        queueIdRef.current += 1;
        next.push({ id: `q-${queueIdRef.current}`, file });
      }
      return next;
    });
  }

  function removeQueued(id: string) {
    setQueue((prev) => prev.filter((q) => q.id !== id));
  }

  async function startAnalysis() {
    if (!queue.length) {
      setError("请先拖入或选择待分析文件");
      return;
    }
    setUploading(true);
    setError(null);
    setUploadMsg(null);
    const results: string[] = [];
    try {
      for (const item of queue) {
        const res = await api.uploadDocument(item.file, {
          regulator: regulator || undefined,
          publish_date: publishDate || undefined,
        });
        results.push(`${item.file.name} → ${res.message}`);
      }
      setUploadMsg(`已提交 ${results.length} 个文件开始智能分析`);
      setQueue([]);
      if (fileRef.current) fileRef.current.value = "";
      await load(1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  async function onRetry(fileId: string) {
    try {
      await api.retryDocument(fileId);
      await load(page);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "重试失败");
    }
  }

  async function onDeleteDoc(fileId: string) {
    if (!window.confirm("确认删除该文档及其关联案例？")) return;
    try {
      await api.deleteDocument(fileId);
      if (detail?.file_id === fileId) setDetail(null);
      await load(page);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    }
  }

  async function openDetail(fileId: string) {
    setDetailLoading(true);
    setError(null);
    try {
      const d = await api.getDocument(fileId);
      setDetail(d);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载详情失败");
    } finally {
      setDetailLoading(false);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    addFiles(e.dataTransfer.files);
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="space-y-8">
      <header className="rise-in">
        <h1 className="font-display text-4xl font-bold">数据入库</h1>
        <p className="mt-2 text-muted-fg">
          拖拽或批量选择处罚文书，确认后开始智能分析；详情面板展示结构化抽取字段。
        </p>
      </header>

      <section className="surface space-y-5 rounded-3xl p-6">
        <h2 className="font-display text-xl font-semibold">上传文档</h2>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={[
            "rounded-2xl border-2 border-dashed px-6 py-12 text-center transition duration-200",
            dragOver ? "border-primary bg-primary/5 scale-[1.01]" : "border-border bg-slate-50/80",
          ].join(" ")}
        >
          <FileUp className="mx-auto h-9 w-9 text-primary" aria-hidden />
          <p className="mt-3 text-sm font-semibold text-foreground">拖拽 PDF / DOCX / HTML 到此处</p>
          <p className="mt-1 text-xs text-muted-fg">支持批量添加；也可点击下方按钮选择文件</p>
          <label
            htmlFor={inputId}
            className="mt-5 inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-border bg-white px-4 text-sm font-medium hover:bg-muted"
          >
            批量选择文件
            <input
              id={inputId}
              ref={fileRef}
              type="file"
              accept={ACCEPT}
              multiple
              className="sr-only"
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
        </div>

        {queue.length > 0 ? (
          <ul className="space-y-2" aria-label="待上传文件列表">
            {queue.map((q) => (
              <li
                key={q.id}
                className="flex items-center justify-between gap-3 rounded-xl border border-border bg-white px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{q.file.name}</p>
                  <p className="text-xs text-muted-fg">
                    {(q.file.size / 1024).toFixed(1)} KB
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => removeQueued(q.id)}
                  className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-border text-muted-fg hover:bg-red-50 hover:text-destructive"
                  aria-label={`移除 ${q.file.name}`}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="doc-reg" className="mb-1.5 block text-xs font-semibold text-muted-fg">
              监管机构（可选）
            </label>
            <input
              id="doc-reg"
              value={regulator}
              onChange={(e) => setRegulator(e.target.value)}
              className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
            />
          </div>
          <div>
            <label htmlFor="pub" className="mb-1.5 block text-xs font-semibold text-muted-fg">
              发布日期（可选）
            </label>
            <input
              id="pub"
              type="date"
              value={publishDate}
              onChange={(e) => setPublishDate(e.target.value)}
              className="min-h-11 w-full rounded-xl border border-border bg-white px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
            />
          </div>
        </div>

        <button
          type="button"
          disabled={uploading || queue.length === 0}
          onClick={() => void startAnalysis()}
          className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-accent px-5 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-50 sm:w-auto"
        >
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          {uploading ? "提交中…" : "开始智能分析"}
        </button>

        {uploadMsg ? (
          <p className="text-sm text-accent" role="status">
            {uploadMsg}
          </p>
        ) : null}
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="status" className="text-sm font-medium text-muted-fg">
          状态筛选
        </label>
        <select
          id="status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="min-h-11 rounded-xl border border-border bg-white px-3 text-sm"
        >
          <option value="">全部</option>
          <option value="pending">排队中 Pending</option>
          <option value="parsing">解析中 Processing</option>
          <option value="done">已完成 Done</option>
          <option value="failed">解析失败 Failed</option>
        </select>
        <button
          type="button"
          onClick={() => void load(page)}
          className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-white px-3 text-sm hover:bg-muted"
        >
          <RefreshCw className="h-4 w-4" />
          刷新
        </button>
      </div>

      {error ? <ErrorAlert message={error} /> : null}
      {loading || detailLoading ? <LoadingBlock /> : null}

      {!loading && data && data.items.length === 0 ? (
        <EmptyState title="暂无文档" description="上传第一份处罚文书开始构建知识库。" />
      ) : null}

      {!loading && data && data.items.length > 0 ? (
        <div className="surface overflow-x-auto rounded-2xl">
          <table className="w-full min-w-[800px] text-left text-sm">
            <thead className="border-b border-border bg-muted/60 text-xs uppercase tracking-wide text-muted-fg">
              <tr>
                <th className="px-4 py-3 font-semibold">文件</th>
                <th className="px-4 py-3 font-semibold">类型</th>
                <th className="px-4 py-3 font-semibold">状态</th>
                <th className="px-4 py-3 font-semibold">监管机构</th>
                <th className="px-4 py-3 font-semibold">上传时间</th>
                <th className="px-4 py-3 font-semibold">操作</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((d) => {
                const failed = d.parse_status === "failed" || d.parse_status === "error";
                return (
                  <tr
                    key={d.file_id}
                    className={[
                      "border-b border-border/60 last:border-0",
                      failed ? "bg-red-50/50" : "",
                    ].join(" ")}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-foreground">{d.file_name}</div>
                      <div className="font-mono text-xs text-muted-fg">{d.file_id}</div>
                    </td>
                    <td className="px-4 py-3 text-muted-fg">{d.source_type}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={d.parse_status} />
                    </td>
                    <td className="px-4 py-3 text-muted-fg">{d.regulator || "—"}</td>
                    <td className="px-4 py-3 text-muted-fg">{formatDate(d.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => void openDetail(d.file_id)}
                          className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-border bg-white px-2.5 text-xs font-medium hover:bg-muted"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          查看详情
                        </button>
                        {failed || d.parse_status === "pending" ? (
                          <button
                            type="button"
                            onClick={() => void onRetry(d.file_id)}
                            className={[
                              "inline-flex min-h-9 items-center rounded-lg px-2.5 text-xs font-semibold",
                              failed
                                ? "bg-destructive text-white hover:brightness-110"
                                : "border border-border bg-white text-primary hover:bg-muted",
                            ].join(" ")}
                          >
                            {failed ? "重新解析" : "重试"}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => void onDeleteDoc(d.file_id)}
                          className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-border bg-white px-2.5 text-xs font-medium text-destructive hover:bg-red-50"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="flex items-center justify-between border-t border-border px-4 py-3 text-sm text-muted-fg">
            <span>
              共 {data.total} 条 · {page}/{totalPages}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => void load(page - 1)}
                className="min-h-10 rounded-lg border border-border bg-white px-3 disabled:opacity-40"
              >
                上一页
              </button>
              <button
                type="button"
                disabled={page >= totalPages}
                onClick={() => void load(page + 1)}
                className="min-h-10 rounded-lg border border-border bg-white px-3 disabled:opacity-40"
              >
                下一页
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {detail ? (
        <div className="fixed inset-0 z-50 flex justify-end">
          <button
            type="button"
            className="absolute inset-0 bg-black/40"
            aria-label="关闭详情"
            onClick={() => setDetail(null)}
          />
          <aside
            className="relative flex h-full w-full max-w-3xl flex-col bg-white shadow-2xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="doc-detail-title"
          >
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div>
                <h2 id="doc-detail-title" className="font-display text-xl font-semibold">
                  文档详情
                </h2>
                <p className="font-mono text-xs text-muted-fg">{detail.file_id}</p>
              </div>
              <button
                type="button"
                onClick={() => setDetail(null)}
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-border hover:bg-muted"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="grid flex-1 gap-0 overflow-y-auto md:grid-cols-2">
              <section className="border-b border-border p-5 md:border-b-0 md:border-r">
                <h3 className="text-sm font-semibold text-muted-fg">原始文本 / OCR</h3>
                <p className="mt-3 rounded-xl bg-muted/60 p-4 text-sm leading-relaxed text-slate-600">
                  {detail.raw_text_path
                    ? `原文路径：${detail.raw_text_path}。当前接口未直接返回全文内容，请在服务端 data 目录查看 OCR 文本。`
                    : "暂无 OCR 原文路径。解析完成后将写入 raw_text。"}
                </p>
                {detail.parse_error ? (
                  <p className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
                    错误：{detail.parse_error}
                  </p>
                ) : null}
                <dl className="mt-4 space-y-2 text-sm">
                  {[
                    ["文件名", detail.file_name],
                    ["类型", detail.source_type],
                    ["状态", statusLabel(detail.parse_status)],
                    ["上传时间", formatDate(detail.created_at)],
                  ].map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-border/60 bg-slate-50 px-3 py-2">
                      <dt className="text-xs text-muted-fg">{k}</dt>
                      <dd className="mt-0.5 font-medium">{v}</dd>
                    </div>
                  ))}
                </dl>
              </section>
              <section className="p-5">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-muted-fg">结构化抽取</h3>
                  {detail.cases?.[0]?.overall_confidence != null ? (
                    <span className="text-xs text-muted-fg">
                      整体置信度{" "}
                      {formatConfidencePct(detail.cases[0].overall_confidence)}
                      {normalizeConfidence(detail.cases[0].overall_confidence) != null &&
                      normalizeConfidence(detail.cases[0].overall_confidence)! >= 0.85
                        ? " · 高"
                        : ""}
                    </span>
                  ) : null}
                </div>
                <ExtractedFields cases={detail.cases ?? []} />
                {(detail.parse_status === "failed" || detail.parse_status === "pending") && (
                  <button
                    type="button"
                    onClick={() => void onRetry(detail.file_id)}
                    className="mt-4 inline-flex min-h-11 items-center rounded-xl bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-deep"
                  >
                    重新解析
                  </button>
                )}
              </section>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
