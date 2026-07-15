import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { RefreshCw, Upload } from "lucide-react";
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

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="space-y-8">
      <header className="rise-in">
        <h1 className="font-display text-4xl font-bold">文档入库</h1>
        <p className="mt-2 text-muted-fg">
          上传处罚文书，异步解析抽取结构化字段并写入案例库。
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
          <option value="pending">pending</option>
          <option value="parsing">parsing</option>
          <option value="done">done</option>
          <option value="failed">failed</option>
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
      {loading ? <LoadingBlock /> : null}

      {!loading && data && data.items.length === 0 ? (
        <EmptyState title="暂无文档" description="上传第一份处罚文书开始构建知识库。" />
      ) : null}

      {!loading && data && data.items.length > 0 ? (
        <div className="surface overflow-x-auto rounded-2xl">
          <table className="w-full min-w-[720px] text-left text-sm">
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
              {data.items.map((d) => (
                <tr key={d.file_id} className="border-b border-border/60 last:border-0">
                  <td className="px-4 py-3">
                    <div className="font-medium text-foreground">{d.file_name}</div>
                    <div className="font-mono text-xs text-muted-fg">{d.file_id}</div>
                  </td>
                  <td className="px-4 py-3 text-muted-fg">{d.source_type}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={d.parse_status} />
                    <span className="ml-2 text-xs text-muted-fg">
                      {statusLabel(d.parse_status)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted-fg">{d.regulator || "—"}</td>
                  <td className="px-4 py-3 text-muted-fg">{formatDate(d.created_at)}</td>
                  <td className="px-4 py-3">
                    {(d.parse_status === "failed" || d.parse_status === "pending") && (
                      <button
                        type="button"
                        onClick={() => void onRetry(d.file_id)}
                        className="text-sm font-medium text-primary hover:underline"
                      >
                        重试解析
                      </button>
                    )}
                  </td>
                </tr>
              ))}
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
    </div>
  );
}
