import { useEffect, useId, useRef, useState, type DragEvent } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  Eye,
  FileText,
  FileUp,
  Loader2,
  Radio,
  RefreshCw,
  Scale,
  ShieldCheck,
  Trash2,
  Upload,
} from "lucide-react";
import { api, ApiError } from "../api/client";
import type { DocumentItem, ParseStage } from "../api/types";
import { formatDate } from "../lib/format";
import { liveProgressPct, liveStages } from "../lib/useIngestLive";

function ingestStatusMeta(status: string): { label: string; className: string } {
  if (status === "done") {
    return {
      label: "解析完成",
      className: "bg-emerald-50 text-emerald-800 ring-emerald-200",
    };
  }
  if (status === "failed") {
    return {
      label: "解析异常",
      className: "bg-red-50 text-red-700 ring-red-200",
    };
  }
  if (status === "parsing") {
    return {
      label: "处理中",
      className: "bg-amber-50 text-amber-900 ring-amber-200 animate-pulse",
    };
  }
  return {
    label: "排队中",
    className: "bg-slate-100 text-slate-700 ring-slate-200",
  };
}

export function ParseStepper({ stages }: { stages?: ParseStage[] }) {
  if (!stages?.length) return null;
  return (
    <ol className="mt-4 flex w-full items-start gap-0 overflow-x-auto pb-1">
      {stages.map((s, i) => {
        const done = s.status === "done";
        const active = s.status === "active";
        const failed = s.status === "failed";
        return (
          <li key={s.key} className="flex min-w-[5.5rem] flex-1 items-start">
            <div className="flex w-full flex-col items-center text-center">
              <div className="flex w-full items-center">
                {i > 0 ? (
                  <span
                    className={[
                      "h-0.5 flex-1 rounded-full transition-colors duration-500 ease-out",
                      stages[i - 1]?.status === "done" ? "bg-accent" : "bg-border",
                    ].join(" ")}
                    aria-hidden
                  />
                ) : (
                  <span className="flex-1" aria-hidden />
                )}
                <span
                  className={[
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-full ring-2 transition-all duration-300 ease-out",
                    done
                      ? "bg-accent text-white ring-accent/30 scale-100"
                      : active
                        ? "bg-white text-amber-600 ring-amber-400 scale-110"
                        : failed
                          ? "bg-red-50 text-red-600 ring-red-300"
                          : "bg-white text-slate-400 ring-border",
                  ].join(" ")}
                >
                  {done ? (
                    <Check className="h-3.5 w-3.5" aria-hidden />
                  ) : active ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  ) : failed ? (
                    <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                  ) : (
                    <span className="h-2 w-2 rounded-full bg-current" aria-hidden />
                  )}
                </span>
                {i < stages.length - 1 ? (
                  <span
                    className={[
                      "h-0.5 flex-1 rounded-full transition-colors duration-500 ease-out",
                      done ? "bg-accent" : "bg-border",
                    ].join(" ")}
                    aria-hidden
                  />
                ) : (
                  <span className="flex-1" aria-hidden />
                )}
              </div>
              <span
                className={[
                  "mt-2 max-w-[5.5rem] text-[11px] font-medium leading-snug transition-colors duration-300",
                  done
                    ? "text-accent"
                    : active
                      ? "text-amber-800"
                      : failed
                        ? "text-red-700"
                        : "text-muted-fg",
                ].join(" ")}
              >
                {s.label}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

type TaskCardProps = {
  doc: DocumentItem;
  nowMs: number;
  busy?: boolean;
  highlight?: boolean;
  onViewCases: (fileId: string) => void;
  onRetry: (fileId: string) => void;
  onDelete: (fileId: string) => void;
};

export function IngestTaskCard({
  doc,
  nowMs,
  busy,
  highlight,
  onViewCases,
  onRetry,
  onDelete,
}: TaskCardProps) {
  const meta = ingestStatusMeta(doc.parse_status);
  const stages = liveStages(doc, nowMs);
  const pct = liveProgressPct(doc, nowMs);
  const done = doc.parse_status === "done";
  const failed = doc.parse_status === "failed";
  const processing = doc.parse_status === "parsing" || doc.parse_status === "pending";
  const [justDone, setJustDone] = useState(false);
  const prevStatus = useRef(doc.parse_status);

  useEffect(() => {
    if (
      prevStatus.current !== "done" &&
      doc.parse_status === "done" &&
      (prevStatus.current === "parsing" || prevStatus.current === "pending")
    ) {
      setJustDone(true);
      const t = window.setTimeout(() => setJustDone(false), 2200);
      prevStatus.current = doc.parse_status;
      return () => window.clearTimeout(t);
    }
    prevStatus.current = doc.parse_status;
  }, [doc.parse_status]);

  return (
    <article
      className={[
        "surface overflow-hidden rounded-2xl transition-all duration-300 ease-out",
        highlight || justDone ? "ring-2 ring-accent/40 shadow-[var(--shadow-lift)]" : "hover:shadow-[var(--shadow-lift)]",
        processing ? "border-l-4 border-l-amber-400" : done ? "border-l-4 border-l-accent" : failed ? "border-l-4 border-l-red-400" : "",
      ].join(" ")}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className={[
              "mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-colors duration-300",
              processing ? "bg-amber-50 text-amber-700" : "bg-muted text-primary",
            ].join(" ")}
          >
            {processing ? (
              <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            ) : (
              <FileText className="h-5 w-5" aria-hidden />
            )}
          </span>
          <div className="min-w-0">
            <h3 className="truncate font-display text-lg font-semibold text-foreground">
              {doc.file_name}
            </h3>
            <p className="mt-1 text-xs text-muted-fg">
              {formatDate(doc.created_at)} · {doc.source_type}
              {doc.regulator ? ` · ${doc.regulator}` : ""}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ring-1 transition-colors duration-300 ${meta.className}`}
          >
            {processing ? <Radio className="h-3 w-3" aria-hidden /> : null}
            {meta.label}
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={() => onDelete(doc.file_id)}
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-border text-muted-fg hover:border-red-200 hover:text-red-700 disabled:opacity-50"
            aria-label={`删除 ${doc.file_name}`}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="px-5 py-4">
        <ParseStepper stages={stages} />

        {processing ? (
          <div className="mt-4">
            <div className="mb-1.5 flex items-center justify-between text-xs text-muted-fg">
              <span className="inline-flex items-center gap-1.5">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
                </span>
                解析进度
                {typeof doc.cases_done === "number" &&
                typeof doc.cases_total === "number" &&
                doc.cases_total > 0 &&
                doc.parse_status === "parsing" ? (
                  <span className="text-muted-fg">
                    · 案例 {doc.cases_done}/{doc.cases_total}
                  </span>
                ) : null}
              </span>
              <span className="font-semibold tabular-nums text-foreground transition-all duration-300">
                {pct}%
              </span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-gradient-to-r from-accent via-emerald-400 to-sky-500 transition-[width] duration-700 ease-out motion-reduce:transition-none"
                style={{ width: `${Math.max(6, pct)}%` }}
              />
            </div>
            <p className="mt-3 flex items-start gap-2 text-xs leading-relaxed text-muted-fg">
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" aria-hidden />
              文档经解析、保险筛选与人工治理后方可进入案例知识库。进度随 Worker 阶段自动更新。
            </p>
          </div>
        ) : null}

        {done ? (
          <div
            className={[
              "mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4",
              justDone ? "animate-[fadeIn_0.4s_ease-out]" : "",
            ].join(" ")}
          >
            {(
              [
                ["生成案例", doc.case_total ?? 0],
                ["已确认保险", doc.case_confirmed ?? 0],
                ["待复核", doc.case_pending ?? 0],
                ["已排除", doc.case_excluded ?? 0],
              ] as const
            ).map(([label, n]) => (
              <div
                key={label}
                className="rounded-xl border border-border/80 bg-slate-50/80 px-3 py-3 text-center transition duration-300"
              >
                <p className="text-[11px] font-medium text-muted-fg">{label}</p>
                <p className="mt-1 font-display text-2xl font-bold tabular-nums text-foreground">
                  {n}
                  <span className="ml-0.5 text-sm font-sans font-medium text-muted-fg">条</span>
                </p>
              </div>
            ))}
          </div>
        ) : null}

        {failed ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50/80 px-4 py-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-red-800">
              <AlertTriangle className="h-4 w-4" aria-hidden />
              文本提取或解析失败
            </p>
            <p className="mt-1 text-xs leading-relaxed text-red-700/90">
              {doc.parse_error ||
                "请检查文件是否为扫描件、加密 PDF，或尝试重新上传后再次解析。"}
            </p>
          </div>
        ) : null}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {done && (doc.case_total ?? 0) > 0 ? (
            <button
              type="button"
              onClick={() => onViewCases(doc.file_id)}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-primary/20 bg-white px-4 text-sm font-semibold text-primary transition duration-200 hover:bg-primary hover:text-white"
            >
              <Eye className="h-4 w-4" />
              查看生成案例
              <ArrowRight className="h-4 w-4" />
            </button>
          ) : null}
          {(failed || doc.parse_status === "pending") && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onRetry(doc.file_id)}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-deep disabled:opacity-50"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              重新解析
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

type UploadPanelProps = {
  onUploaded: () => void;
  onOpenDrawer?: () => void;
};

const ACCEPT = ".pdf,.docx,.html,.htm";
const ACCEPT_EXT = [".pdf", ".docx", ".html", ".htm"];

function isAccepted(file: File): boolean {
  const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
  return ACCEPT_EXT.includes(ext);
}

export function IngestUploadPanel({ onUploaded, onOpenDrawer }: UploadPanelProps) {
  const inputId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function uploadFiles(files: File[]) {
    const accepted = files.filter(isAccepted);
    if (!accepted.length) {
      setError("请选择 PDF / DOCX / HTML 文件");
      return;
    }
    setUploading(true);
    setError(null);
    setMsg(null);
    try {
      for (const file of accepted) {
        await api.uploadDocument(file);
      }
      setMsg(`已提交 ${accepted.length} 个文件，正在解析入库`);
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
    void uploadFiles(Array.from(e.dataTransfer.files || []));
  }

  return (
    <section className="surface rounded-2xl p-5 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">批量上传文书</h2>
          <p className="mt-1 text-sm text-muted-fg">
            支持 PDF / DOCX / HTML；一份监管文书可生成多条候选案例。
          </p>
        </div>
        {onOpenDrawer ? (
          <button
            type="button"
            onClick={onOpenDrawer}
            className="text-sm font-medium text-primary hover:underline"
          >
            高级选项（监管机构 / 日期）
          </button>
        ) : null}
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={[
          "mt-4 rounded-2xl border-2 border-dashed px-4 py-10 text-center transition duration-200",
          dragOver ? "border-accent bg-accent-soft/40" : "border-border bg-slate-50/70",
        ].join(" ")}
      >
        <FileUp
          className={["mx-auto h-9 w-9", dragOver ? "text-accent" : "text-primary"].join(" ")}
          aria-hidden
        />
        <p className="mt-3 text-sm font-medium text-foreground">
          拖拽 PDF / DOCX / HTML 到此处
        </p>
        <p className="mt-1 text-xs text-muted-fg">也可点击选择文件，支持批量上传</p>
        <label
          htmlFor={inputId}
          className={[
            "mt-4 inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-xl px-4 text-sm font-semibold transition",
            uploading
              ? "bg-muted text-muted-fg"
              : "bg-white text-primary ring-1 ring-border hover:bg-primary hover:text-white",
          ].join(" ")}
        >
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          {uploading ? "上传中…" : "选择文件"}
        </label>
        <input
          id={inputId}
          ref={fileRef}
          type="file"
          accept={ACCEPT}
          multiple
          className="sr-only"
          disabled={uploading}
          onChange={(e) => {
            const list = e.target.files;
            if (list?.length) void uploadFiles(Array.from(list));
          }}
        />
      </div>

      <p className="mt-3 rounded-xl bg-sky-50 px-3 py-2.5 text-xs leading-relaxed text-sky-900">
        一份监管文书可生成多条候选处罚案例；原文与案例保持可追溯关联，解析完成后请在「案例队列」人工确认。
      </p>

      {error ? (
        <p className="mt-2 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}
      {msg ? (
        <p className="mt-2 rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-800" role="status">
          {msg}
        </p>
      ) : null}
    </section>
  );
}

export function IngestWorkflowFooter() {
  const steps = [
    { label: "上传文书", icon: Upload },
    { label: "结构化解析", icon: FileText },
    { label: "保险判定", icon: ShieldCheck },
    { label: "人工复核", icon: Scale },
    { label: "知识库入库", icon: Check },
  ];
  return (
    <nav
      aria-label="入库链路"
      className="rounded-2xl border border-border/80 bg-white/80 px-4 py-4"
    >
      <ol className="flex flex-wrap items-center justify-center gap-2 sm:gap-1">
        {steps.map((s, i) => {
          const Icon = s.icon;
          return (
            <li key={s.label} className="flex items-center gap-2 sm:gap-1">
              <span className="inline-flex items-center gap-2 rounded-full bg-muted/80 px-3 py-2 text-xs font-semibold text-foreground">
                <Icon className="h-3.5 w-3.5 text-primary" aria-hidden />
                {s.label}
              </span>
              {i < steps.length - 1 ? (
                <ArrowRight className="hidden h-3.5 w-3.5 text-muted-fg sm:block" aria-hidden />
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
