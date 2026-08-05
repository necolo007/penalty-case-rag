import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { DocumentItem, Paginated, ParseStage } from "../api/types";

const ACTIVE = new Set(["pending", "parsing"]);

export function hasActiveIngestJobs(items: DocumentItem[] | undefined): boolean {
  return Boolean(items?.some((d) => ACTIVE.has(d.parse_status)));
}

/** 直接使用后端推导的真实阶段（Worker 写入 stage） */
export function liveStages(doc: DocumentItem, _nowMs?: number): ParseStage[] {
  return doc.parse_stages ?? [];
}

/**
 * 进度百分比：优先用 Worker 上报的 progress_pct；
 * 仅在当前阶段内做轻微缓增（避免两次轮询间进度条完全静止）。
 */
export function liveProgressPct(doc: DocumentItem, nowMs: number): number {
  if (doc.parse_status === "done") return 100;

  const stages = doc.parse_stages ?? [];
  const reported =
    typeof doc.progress_pct === "number" && !Number.isNaN(doc.progress_pct)
      ? Math.max(0, Math.min(100, doc.progress_pct))
      : null;

  if (doc.parse_status === "failed") {
    if (reported != null) return Math.min(99, Math.round(reported));
    const done = stages.filter((s) => s.status === "done").length;
    return stages.length ? Math.round((done / stages.length) * 100) : 15;
  }

  let base =
    reported ??
    (() => {
      const done = stages.filter((s) => s.status === "done").length;
      const active = stages.some((s) => s.status === "active") ? 0.45 : 0;
      return stages.length ? ((done + active) / stages.length) * 100 : 4;
    })();

  if (doc.parse_status === "pending") {
    return Math.min(8, Math.round(base || 2));
  }

  // 阶段内 soft：距上次 updated_at 最多 +3%，且不超过 96%
  const t0 = new Date(doc.updated_at || doc.created_at || Date.now()).getTime();
  const elapsed = Math.max(0, (nowMs - t0) / 1000);
  const soft = Math.min(3, elapsed * 0.35);
  return Math.min(96, Math.round(base + soft));
}

type Options = {
  enabled: boolean;
  page: number;
  pageSize?: number;
  parseStatus?: string;
  pollMs?: number;
  tickMs?: number;
};

/**
 * 入库任务列表：首屏加载 + 入库视图静默轮询；本地时钟仅用于阶段内微动画。
 */
export function useIngestLive(opts: Options) {
  const {
    enabled,
    page,
    pageSize = 12,
    parseStatus = "",
    pollMs = 2000,
    tickMs = 1000,
  } = opts;

  const [docs, setDocs] = useState<Paginated<DocumentItem> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [live, setLive] = useState(false);
  const [lastSyncAt, setLastSyncAt] = useState<number | null>(null);
  const pageRef = useRef(page);
  const statusRef = useRef(parseStatus);
  pageRef.current = page;
  statusRef.current = parseStatus;

  const fetchPage = useCallback(
    async (p: number, opts: { silent: boolean }) => {
      const silent = opts.silent;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await api.listDocuments({
          page: p,
          page_size: pageSize,
          parse_status: statusRef.current || undefined,
        });
        setDocs(res);
        setLastSyncAt(Date.now());
        setLive(hasActiveIngestJobs(res.items));
        return res;
      } catch (err) {
        if (!silent) {
          setError(err instanceof Error ? err.message : "加载入库任务失败");
        }
        return null;
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [pageSize],
  );

  useEffect(() => {
    if (!enabled) return;
    void fetchPage(page, { silent: false });
  }, [enabled, page, parseStatus, fetchPage]);

  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(() => {
      void fetchPage(pageRef.current, { silent: true });
    }, pollMs);
    return () => window.clearInterval(id);
  }, [enabled, pollMs, fetchPage]);

  useEffect(() => {
    if (!enabled || !live) return;
    const id = window.setInterval(() => setNowMs(Date.now()), tickMs);
    return () => window.clearInterval(id);
  }, [enabled, live, tickMs]);

  const reload = useCallback(
    (p = pageRef.current) => fetchPage(p, { silent: false }),
    [fetchPage],
  );

  const softReload = useCallback(
    (p = pageRef.current) => fetchPage(p, { silent: true }),
    [fetchPage],
  );

  return {
    docs,
    setDocs,
    loading,
    error,
    setError,
    nowMs,
    live,
    lastSyncAt,
    reload,
    softReload,
  };
}
