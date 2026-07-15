import type { ReactNode } from "react";
import { AlertCircle, Inbox, Loader2 } from "lucide-react";

export function LoadingBlock({ label = "加载中…" }: { label?: string }) {
  return (
    <div
      className="flex items-center justify-center gap-3 py-16 text-muted-fg"
      role="status"
      aria-live="polite"
    >
      <Loader2 className="h-5 w-5 animate-spin text-primary" aria-hidden />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-primary">
        <Inbox className="h-5 w-5" aria-hidden />
      </div>
      <h3 className="font-display text-xl font-semibold text-foreground">{title}</h3>
      {description ? <p className="max-w-md text-sm text-muted-fg">{description}</p> : null}
      {action}
    </div>
  );
}

export function ErrorAlert({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <p>{message}</p>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "done" || status === "completed"
      ? "bg-accent-soft text-accent"
      : status === "failed" || status === "error"
        ? "bg-red-50 text-destructive"
        : status === "pending" || status === "parsing" || status === "extracting"
          ? "bg-amber-50 text-warning"
          : "bg-muted text-muted-fg";

  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold tracking-wide ${tone}`}
    >
      {status}
    </span>
  );
}

export function TagChip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md bg-primary/8 px-2 py-0.5 text-xs font-medium text-primary">
      {children}
    </span>
  );
}
