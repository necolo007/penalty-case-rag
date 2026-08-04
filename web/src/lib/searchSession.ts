/**
 * 相似案例检索会话：模块级状态 + sessionStorage。
 * 切到其他路由再回来时保留表单、结果与理解动画终态；进行中的请求不会因卸载而丢弃结果。
 */
import { useSyncExternalStore } from "react";
import { api, ApiError } from "../api/client";
import type { RetrieveResponse } from "../api/types";
import { pushSearchHistory } from "./searchHistory";

const STORAGE_KEY = "anku-search-session-v1";
const MIN_THINK_MS = 2200;

export type SearchSessionState = {
  query: string;
  riskType: string;
  regulator: string;
  institutionType: string;
  scene: string;
  dateFrom: string;
  dateTo: string;
  riskLevel: string;
  salesRelated: string;
  topK: number;
  useReranker: boolean;
  advancedOpen: boolean;
  loading: boolean;
  understanding: boolean;
  understandingDone: boolean;
  error: string | null;
  data: RetrieveResponse | null;
  pendingCount: number | null;
  /** 主从布局当前选中案例 */
  selectedCaseId: string | null;
};

type PersistedSlice = Pick<
  SearchSessionState,
  | "query"
  | "riskType"
  | "regulator"
  | "institutionType"
  | "scene"
  | "dateFrom"
  | "dateTo"
  | "riskLevel"
  | "salesRelated"
  | "topK"
  | "useReranker"
  | "advancedOpen"
  | "error"
  | "data"
  | "understandingDone"
  | "pendingCount"
  | "selectedCaseId"
>;

const defaultState: SearchSessionState = {
  query: "",
  riskType: "",
  regulator: "",
  institutionType: "",
  scene: "",
  dateFrom: "",
  dateTo: "",
  riskLevel: "",
  salesRelated: "",
  topK: 10,
  useReranker: true,
  advancedOpen: false,
  loading: false,
  understanding: false,
  understandingDone: false,
  error: null,
  data: null,
  pendingCount: null,
  selectedCaseId: null,
};

function loadPersisted(): Partial<SearchSessionState> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as PersistedSlice;
  } catch {
    return {};
  }
}

function persist(s: SearchSessionState) {
  try {
    const slice: PersistedSlice = {
      query: s.query,
      riskType: s.riskType,
      regulator: s.regulator,
      institutionType: s.institutionType,
      scene: s.scene,
      dateFrom: s.dateFrom,
      dateTo: s.dateTo,
      riskLevel: s.riskLevel,
      salesRelated: s.salesRelated,
      topK: s.topK,
      useReranker: s.useReranker,
      advancedOpen: s.advancedOpen,
      error: s.error,
      data: s.data,
      understandingDone: s.understandingDone,
      pendingCount: s.pendingCount,
      selectedCaseId: s.selectedCaseId,
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(slice));
  } catch {
    // quota / private mode
  }
}

let state: SearchSessionState = {
  ...defaultState,
  ...loadPersisted(),
  // 切页回来时若上次请求已结束，不展示 loading；若仍在飞则由 runSeq 回填
  loading: false,
  understanding: false,
};
let runSeq = 0;
const listeners = new Set<() => void>();

function emit() {
  persist(state);
  listeners.forEach((l) => l());
}

function patch(partial: Partial<SearchSessionState>) {
  state = { ...state, ...partial };
  emit();
}

export const searchSession = {
  getSnapshot: () => state,
  subscribe: (listener: () => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  setQuery: (query: string) => patch({ query }),
  setRiskType: (riskType: string) => patch({ riskType }),
  setRegulator: (regulator: string) => patch({ regulator }),
  setInstitutionType: (institutionType: string) => patch({ institutionType }),
  setScene: (scene: string) => patch({ scene }),
  setDateFrom: (dateFrom: string) => patch({ dateFrom }),
  setDateTo: (dateTo: string) => patch({ dateTo }),
  setRiskLevel: (riskLevel: string) => patch({ riskLevel }),
  setSalesRelated: (salesRelated: string) => patch({ salesRelated }),
  setTopK: (topK: number) => patch({ topK }),
  setUseReranker: (useReranker: boolean) => patch({ useReranker }),
  setAdvancedOpen: (advancedOpen: boolean) => patch({ advancedOpen }),
  toggleAdvancedOpen: () => patch({ advancedOpen: !state.advancedOpen }),
  setSelectedCaseId: (selectedCaseId: string | null) => patch({ selectedCaseId }),
  clearResults: () =>
    patch({
      data: null,
      error: null,
      understandingDone: false,
      pendingCount: null,
      understanding: false,
      loading: false,
      selectedCaseId: null,
    }),
  runSearch: async (q?: string) => {
    const text = (q ?? state.query).trim();
    if (!text) {
      patch({ error: "请输入检索问题或违规描述" });
      return;
    }

    const runId = ++runSeq;
    const started = Date.now();
    pushSearchHistory(text);
    patch({
      query: text,
      loading: true,
      understanding: true,
      understandingDone: false,
      error: null,
      data: null,
      pendingCount: null,
      selectedCaseId: null,
    });

    try {
      const res = (await api.retrieve({
        query_text: text,
        risk_type: state.riskType || null,
        regulator: state.regulator || null,
        institution_type: state.institutionType || null,
        scene: state.scene || null,
        date_from: state.dateFrom || null,
        date_to: state.dateTo || null,
        top_k: state.topK,
        use_reranker: state.useReranker,
      })) as RetrieveResponse;

      if (runId !== runSeq) return;

      const poolEstimate = Object.values(res.channel_stats).reduce((a, b) => a + b, 0);
      patch({ pendingCount: poolEstimate || res.results.length * 8 });

      const elapsed = Date.now() - started;
      if (elapsed < MIN_THINK_MS) {
        await new Promise((r) => window.setTimeout(r, MIN_THINK_MS - elapsed));
      }
      if (runId !== runSeq) return;

      patch({
        data: res,
        understandingDone: true,
        understanding: false,
        loading: false,
        selectedCaseId: res.results[0]?.case_id ?? null,
      });
    } catch (err) {
      if (runId !== runSeq) return;
      patch({
        data: null,
        error: err instanceof ApiError ? err.message : "检索失败，请稍后重试",
        understandingDone: true,
        understanding: false,
        loading: false,
        selectedCaseId: null,
      });
    }
  },
};

export function useSearchSession(): SearchSessionState {
  return useSyncExternalStore(
    searchSession.subscribe,
    searchSession.getSnapshot,
    searchSession.getSnapshot,
  );
}
