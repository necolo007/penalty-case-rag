import { useSyncExternalStore } from "react";
import { api, ApiError } from "../api/client";
import type { MaterialReviewResponse, ReviewGenerateResponse } from "../api/types";

const STORAGE_KEY = "anku-review-session-v1";

export type ReviewTab = "sentence" | "material";

export type ReviewSessionState = {
  tab: ReviewTab;
  query: string;
  material: string;
  scene: string;
  topK: number;
  loading: boolean;
  error: string | null;
  review: ReviewGenerateResponse | null;
  materialReport: MaterialReviewResponse | null;
  feedback: Record<string, "pass" | "wrong">;
  thinkFinished: boolean;
  thinkElapsedMs: number | null;
  thinkHint: string;
  thinkStartedAt: number | null;
  /** 完成后短暂提示（切页回来也能看到） */
  justFinished: boolean;
};

const defaultState: ReviewSessionState = {
  tab: "material",
  query: "",
  material: "",
  scene: "",
  topK: 5,
  loading: false,
  error: null,
  review: null,
  materialReport: null,
  feedback: {},
  thinkFinished: false,
  thinkElapsedMs: null,
  thinkHint: "",
  thinkStartedAt: null,
  justFinished: false,
};

type PersistedSlice = Pick<
  ReviewSessionState,
  | "tab"
  | "query"
  | "material"
  | "scene"
  | "topK"
  | "error"
  | "review"
  | "materialReport"
  | "feedback"
  | "thinkFinished"
  | "thinkElapsedMs"
  | "thinkHint"
>;

function loadPersisted(): Partial<ReviewSessionState> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as PersistedSlice;
  } catch {
    return {};
  }
}

function persist(state: ReviewSessionState) {
  try {
    const slice: PersistedSlice = {
      tab: state.tab,
      query: state.query,
      material: state.material,
      scene: state.scene,
      topK: state.topK,
      error: state.error,
      review: state.review,
      materialReport: state.materialReport,
      feedback: state.feedback,
      thinkFinished: state.thinkFinished,
      thinkElapsedMs: state.thinkElapsedMs,
      thinkHint: state.thinkHint,
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(slice));
  } catch {
    // quota / private mode — ignore
  }
}

let state: ReviewSessionState = { ...defaultState, ...loadPersisted(), loading: false, justFinished: false };
let runSeq = 0;
const listeners = new Set<() => void>();

function emit() {
  persist(state);
  listeners.forEach((l) => l());
}

function patch(partial: Partial<ReviewSessionState>) {
  state = { ...state, ...partial };
  emit();
}

function beginThink(hint: string) {
  patch({
    thinkHint: hint,
    thinkFinished: false,
    thinkElapsedMs: null,
    thinkStartedAt: Date.now(),
    loading: true,
    error: null,
    justFinished: false,
  });
}

function endThink(runId: number, ok: boolean) {
  if (runId !== runSeq) return;
  const started = state.thinkStartedAt ?? Date.now();
  patch({
    thinkElapsedMs: Date.now() - started,
    thinkFinished: ok,
    loading: false,
    thinkStartedAt: null,
    justFinished: ok,
  });
  if (ok) {
    window.setTimeout(() => {
      if (runId === runSeq) patch({ justFinished: false });
    }, 8000);
  }
}

export const reviewSession = {
  getSnapshot: () => state,
  subscribe: (listener: () => void) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  setTab: (tab: ReviewTab) => patch({ tab }),
  setQuery: (query: string) => patch({ query }),
  setMaterial: (material: string) => patch({ material }),
  setScene: (scene: string) => patch({ scene }),
  setTopK: (topK: number) => patch({ topK }),
  setFeedback: (feedback: Record<string, "pass" | "wrong">) => patch({ feedback }),
  dismissJustFinished: () => patch({ justFinished: false }),
  clearResults: () =>
    patch({
      review: null,
      materialReport: null,
      feedback: {},
      error: null,
      thinkFinished: false,
      thinkElapsedMs: null,
      thinkHint: "",
      justFinished: false,
    }),
  /** 单句审查 — 请求在模块级继续，切页不中断 */
  startSentenceReview: async () => {
    const query = state.query.trim();
    if (!query) {
      patch({ error: "请输入待审查文本" });
      return;
    }
    const runId = ++runSeq;
    beginThink(query);
    patch({ materialReport: null, feedback: {}, review: null });
    try {
      const res = await api.generateReview({
        query_text: query,
        top_k: state.topK,
        generate_suggestion: true,
      });
      if (runId !== runSeq) return;
      patch({ review: res });
      endThink(runId, true);
    } catch (err) {
      if (runId !== runSeq) return;
      patch({
        review: null,
        error: err instanceof ApiError ? err.message : "审查生成失败",
      });
      endThink(runId, false);
    }
  },
  startMaterialReview: async () => {
    const material = state.material.trim();
    if (!material) {
      patch({ error: "请粘贴待审查材料文本，或上传文件" });
      return;
    }
    const runId = ++runSeq;
    beginThink(material);
    patch({ review: null });
    try {
      const res = await api.reviewMaterialText(material, state.scene || undefined);
      if (runId !== runSeq) return;
      patch({ materialReport: res });
      endThink(runId, true);
    } catch (err) {
      if (runId !== runSeq) return;
      patch({
        materialReport: null,
        error: err instanceof ApiError ? err.message : "材料审查失败",
      });
      endThink(runId, false);
    }
  },
  startMaterialFile: async (file: File) => {
    const runId = ++runSeq;
    beginThink(file.name);
    patch({ review: null, tab: "material" });
    try {
      const res = await api.reviewMaterialUpload(file, state.scene || undefined);
      if (runId !== runSeq) return;
      patch({ materialReport: res });
      endThink(runId, true);
    } catch (err) {
      if (runId !== runSeq) return;
      patch({
        materialReport: null,
        error: err instanceof ApiError ? err.message : "材料文件审查失败",
      });
      endThink(runId, false);
    }
  },
};

export function useReviewSession(): ReviewSessionState {
  return useSyncExternalStore(reviewSession.subscribe, reviewSession.getSnapshot, reviewSession.getSnapshot);
}
