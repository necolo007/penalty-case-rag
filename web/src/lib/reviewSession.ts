import { useSyncExternalStore } from "react";
import { api, ApiError } from "../api/client";
import type { FeedbackVerdict, MaterialReviewResponse, ReviewGenerateResponse } from "../api/types";

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
  /** UI 本地态；与后端 agree/disagree/partial 对应 */
  feedback: Record<string, FeedbackVerdict>;
  feedbackSaving: Record<string, boolean>;
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
  feedbackSaving: {},
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
    const parsed = JSON.parse(raw) as PersistedSlice & {
      feedback?: Record<string, string>;
    };
    // 兼容旧版 pass/wrong
    if (parsed.feedback) {
      const mapped: Record<string, FeedbackVerdict> = {};
      for (const [k, v] of Object.entries(parsed.feedback)) {
        const raw = String(v);
        if (raw === "pass" || raw === "agree") mapped[k] = "agree";
        else if (raw === "wrong" || raw === "disagree") mapped[k] = "disagree";
        else if (raw === "partial") mapped[k] = "partial";
      }
      parsed.feedback = mapped;
    }
    return parsed;
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

let state: ReviewSessionState = {
  ...defaultState,
  ...loadPersisted(),
  loading: false,
  feedbackSaving: {},
  justFinished: false,
};
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
  setError: (error: string | null) => patch({ error }),
  setFeedback: (feedback: Record<string, FeedbackVerdict>) => patch({ feedback }),
  /** 提交人工复核到后端（agree / disagree / partial） */
  submitCaseFeedback: async (caseKey: string, verdict: FeedbackVerdict, note?: string) => {
    const reviewId = state.review?.review_id;
    if (!reviewId) {
      patch({ error: "缺少 review_id，无法提交复核" });
      return;
    }
    patch({
      feedback: { ...state.feedback, [caseKey]: verdict },
      feedbackSaving: { ...state.feedbackSaving, [caseKey]: true },
      error: null,
    });
    try {
      await api.submitFeedback(reviewId, {
        feedback: verdict,
        feedback_note: note || `case_id=${caseKey}`,
        reviewer: "web-ui",
      });
    } catch (err) {
      patch({
        error: err instanceof ApiError ? err.message : "复核提交失败",
      });
    } finally {
      const nextSaving = { ...state.feedbackSaving };
      delete nextSaving[caseKey];
      patch({ feedbackSaving: nextSaving });
    }
  },
  dismissJustFinished: () => patch({ justFinished: false }),
  clearResults: () =>
    patch({
      review: null,
      materialReport: null,
      feedback: {},
      feedbackSaving: {},
      error: null,
      thinkFinished: false,
      thinkElapsedMs: null,
      thinkHint: "",
      justFinished: false,
    }),
  saveMaterialHumanReview: async (note: string) => {
    const materialId = state.materialReport?.material_id;
    if (!materialId) {
      patch({ error: "缺少 material_id，无法保存复核" });
      return false;
    }
    patch({ feedbackSaving: { ...state.feedbackSaving, human: true }, error: null });
    try {
      await api.saveMaterialHumanReview(materialId, {
        note,
        reviewer: "web-ui",
        status: "done",
      });
      return true;
    } catch (err) {
      patch({
        error: err instanceof ApiError ? err.message : "人工复核保存失败",
      });
      return false;
    } finally {
      const nextSaving = { ...state.feedbackSaving };
      delete nextSaving.human;
      patch({ feedbackSaving: nextSaving });
    }
  },
  /** 单句审查 — 请求在模块级继续，切页不中断 */
  startSentenceReview: async () => {
    const query = state.query.trim();
    if (!query) {
      patch({ error: "请输入待审查文本" });
      return;
    }
    const runId = ++runSeq;
    beginThink(query);
    patch({ materialReport: null, feedback: {}, feedbackSaving: {}, review: null });
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
      patch({ error: "请先粘贴材料文本，或拖入/选择文件后再开始审查" });
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
