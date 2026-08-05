import { useId, useRef, useState, type DragEvent } from "react";
import { FileUp, Loader2, X } from "lucide-react";
import { api, ApiError } from "../api/client";

type QueuedFile = { id: string; file: File };

const ACCEPT = ".pdf,.docx,.html,.htm";
const ACCEPT_EXT = [".pdf", ".docx", ".html", ".htm"];

function isAccepted(file: File): boolean {
  const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
  return ACCEPT_EXT.includes(ext);
}

type Props = {
  open: boolean;
  onClose: () => void;
  onUploaded: () => void;
};

export function UploadDocumentDrawer({ open, onClose, onUploaded }: Props) {
  const inputId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const queueIdRef = useRef(0);
  const [queue, setQueue] = useState<QueuedFile[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [regulator, setRegulator] = useState("");
  const [publishDate, setPublishDate] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  if (!open) return null;

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
        if (next.some((q) => q.file.name === file.name && q.file.size === file.size)) continue;
        queueIdRef.current += 1;
        next.push({ id: `q-${queueIdRef.current}`, file });
      }
      return next;
    });
  }

  async function startUpload() {
    if (!queue.length) {
      setError("请先选择待上传文件");
      return;
    }
    setUploading(true);
    setError(null);
    setMsg(null);
    try {
      for (const item of queue) {
        await api.uploadDocument(item.file, {
          regulator: regulator || undefined,
          publish_date: publishDate || undefined,
        });
      }
      setMsg(`已提交 ${queue.length} 个文件，正在解析入库`);
      setQueue([]);
      if (fileRef.current) fileRef.current.value = "";
      onUploaded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    addFiles(e.dataTransfer.files);
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-labelledby="upload-drawer-title">
      <button
        type="button"
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]"
        aria-label="关闭上传抽屉"
        onClick={onClose}
      />
      <aside className="relative flex h-full w-full max-w-lg flex-col bg-white shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <h2 id="upload-drawer-title" className="font-display text-xl font-semibold">
              上传处罚文书
            </h2>
            <p className="mt-1 text-xs text-muted-fg">
              支持 PDF / DOCX / HTML；上传后进入「入库任务」查看进度。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-border hover:bg-muted"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={[
              "rounded-2xl border-2 border-dashed px-4 py-10 text-center transition",
              dragOver ? "border-primary bg-primary/5" : "border-border bg-slate-50/80",
            ].join(" ")}
          >
            <FileUp className="mx-auto h-8 w-8 text-primary" aria-hidden />
            <p className="mt-3 text-sm font-medium">拖拽文件到此处，或点击选择</p>
            <p className="mt-1 text-xs text-muted-fg">PDF / DOCX / HTML</p>
            <label
              htmlFor={inputId}
              className="mt-4 inline-flex min-h-11 cursor-pointer items-center rounded-xl bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-deep"
            >
              选择文件
            </label>
            <input
              id={inputId}
              ref={fileRef}
              type="file"
              accept={ACCEPT}
              multiple
              className="sr-only"
              onChange={(e) => addFiles(e.target.files)}
            />
          </div>

          {queue.length ? (
            <ul className="space-y-2">
              {queue.map((q) => (
                <li
                  key={q.id}
                  className="flex items-center justify-between gap-2 rounded-xl border border-border px-3 py-2 text-sm"
                >
                  <span className="truncate font-medium">{q.file.name}</span>
                  <button
                    type="button"
                    className="min-h-11 min-w-11 text-muted-fg hover:text-red-600"
                    aria-label={`移除 ${q.file.name}`}
                    onClick={() => setQueue((prev) => prev.filter((x) => x.id !== q.id))}
                  >
                    <X className="mx-auto h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="up-reg" className="mb-1 block text-xs font-semibold text-muted-fg">
                监管机构（可选）
              </label>
              <input
                id="up-reg"
                value={regulator}
                onChange={(e) => setRegulator(e.target.value)}
                className="min-h-11 w-full rounded-xl border border-border px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              />
            </div>
            <div>
              <label htmlFor="up-date" className="mb-1 block text-xs font-semibold text-muted-fg">
                发布日期（可选）
              </label>
              <input
                id="up-date"
                type="date"
                value={publishDate}
                onChange={(e) => setPublishDate(e.target.value)}
                className="min-h-11 w-full rounded-xl border border-border px-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
              />
            </div>
          </div>

          {error ? (
            <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
              {error}
            </p>
          ) : null}
          {msg ? (
            <p className="rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800" role="status">
              {msg}
            </p>
          ) : null}
        </div>

        <footer className="flex gap-2 border-t border-border px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 flex-1 rounded-xl border border-border text-sm font-medium hover:bg-muted"
          >
            取消
          </button>
          <button
            type="button"
            disabled={uploading || !queue.length}
            onClick={() => void startUpload()}
            className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-primary text-sm font-semibold text-white hover:bg-primary-deep disabled:opacity-50"
          >
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            开始上传解析
          </button>
        </footer>
      </aside>
    </div>
  );
}
