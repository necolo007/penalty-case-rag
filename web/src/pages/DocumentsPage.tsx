import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Eye, RefreshCw, Upload, X } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { DocumentItem, Paginated } from "../api/types";
import { formatDate, statusLabel } from "../lib/format";
import { EmptyState, ErrorAlert, LoadingBlock, StatusBadge } from "../components/ui";

export function DocumentsPage() {
  const [data, setData] = useState<Paginated<DocumentItem> | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [regulator, setRegulator] = useState("");
  const [publishDate, setPublishDate] = useState("");
  const [detail, setDetail] = useState<DocumentItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

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

  async function onUpload(e: FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("请选择 PDF / DOCX / HTML 文件");
      return;
    }
    setUploading(true);
    setError(null);
    setUploadMsg(null);
    try {
      const res = await api.uploadDocument(file, {
        regulator: regulator || undefined,
        publish_date: publishDate || undefined,
      });
      setUploadMsg(`${res.message}（${res.file_id}）`);
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

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="space-y-8">
      <header className="rise-in">
        <h1 className="font-display text-4xl font-bold">数据入库</h1>
        <p className="mt-2 text-muted-fg">
          批量上传、解析、纠错、入库。状态栏高亮展示完成 / 失败 / 排队 / 解析中。
        </p>
      </header>

      <form onSubmit={onUpload} className="surface rounded-3xl p-6">
        <h2 className="font-display text-xl font-semibold">上传文档</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <div className="sm:col-span-3">
            <label htmlFor="file" className="mb-1.5 block text-xs font-semibold text-muted-fg">
              文件（PDF / DOCX / HTML）
            </label>
            <input
              id="file"
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.html,.htm"
              className="block w-full text-sm file:mr-4 file:min-h-11 file:cursor-pointer file:rounded-xl file:border-0 file:bg-primary file:px-4 file:text-sm file:font-semibold file:text-white hover:file:bg-primary-deep"
            />
          </div>
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
          <div className="flex items-end">
            <button
              type="submit"
              disabled={uploading}
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
            >
              <Upload className="h-4 w-4" />
              {uploading ? "上传中…" : "提交入库"}
            </button>
          </div>
        </div>
        {uploadMsg ? (
          <p className="mt-3 text-sm text-accent" role="status">
            {uploadMsg}
          </p>
        ) : null}
      </form>

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
              </section>
              <section className="p-5">
                <h3 className="text-sm font-semibold text-muted-fg">结构化信息</h3>
                <dl className="mt-3 space-y-3 text-sm">
                  {[
                    ["文件名", detail.file_name],
                    ["类型", detail.source_type],
                    ["状态", statusLabel(detail.parse_status)],
                    ["监管机构", detail.regulator || "—"],
                    ["发布日期", formatDate(detail.publish_date)],
                    ["创建时间", formatDate(detail.created_at)],
                    ["更新时间", formatDate(detail.updated_at)],
                  ].map(([k, v]) => (
                    <div key={k} className="rounded-xl border border-border/70 bg-slate-50 px-3 py-2">
                      <dt className="text-xs text-muted-fg">{k}</dt>
                      <dd className="mt-0.5 font-medium text-foreground">{v}</dd>
                    </div>
                  ))}
                </dl>
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
