/**
 * 处罚案例库会话：模块级状态 + sessionStorage。
 * 切页保留筛选、分页、视图与列表结果；进行中的加载不会因路由卸载而丢弃。
 */
import { useSyncExternalStore } from "react";
import { api, ApiError } from "../api/client";
import type { CaseListItem, Paginated } from "../api/types";

const STORAGE_KEY = "anku-cases-session-v1";

export type CasesViewMode = "table" | "card";
export type CasesSortBy =
  | "publish_date"
  | "fine_amount"
  | "overall_confidence"
  | "party_name";

export type CasesFilterParams = {
  page: number;
  page_size: number;
  keyword?: string;
  regulator?: string;
  risk_type?: string;
  is_insurance_related?: boolean;
  date_from?: string;
  date_to?: string;
  sort_by: CasesSortBy;
  sort_order: "asc" | "desc";
};

export type CasesSessionState = {
  keyword: string;
  regulator: string;
  riskType: string;
  dateFrom: string;
  dateTo: string;
  insuranceOnly: boolean;
  viewMode: CasesViewMode;
  sortBy: CasesSortBy;
  sortOrder: "asc" | "desc";
  page: number;
  data: Paginated<CaseListItem> | null;
  loading: boolean;
  error: string | null;
  selected: string[];
  exporting: boolean;
};

type PersistedSlice = Pick<
  CasesSessionState,
  | "keyword"
  | "regulator"
  | "riskType"
  | "dateFrom"
  | "dateTo"
  | "insuranceOnly"
  | "viewMode"
  | "sortBy"
  | "sortOrder"
  | "page"
  | "data"
  | "error"
  | "selected"
>;

const defaultState: CasesSessionState = {
  keyword: "",
  regulator: "",
  riskType: "",
  dateFrom: "",
  dateTo: "",
  insuranceOnly: true,
  viewMode: "table",
  sortBy: "publish_date",
  sortOrder: "desc",
  page: 1,
  data: null,
  loading: false,
  error: null,
  selected: [],
  exporting: false,
};

function loadPersisted(): Partial<CasesSessionState> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as PersistedSlice;
    return {
      ...parsed,
      selected: Array.isArray(parsed.selected) ? parsed.selected : [],
    };
  } catch {
    return {};
  }
}

function persist(s: CasesSessionState) {
  try {
    const slice: PersistedSlice = {
      keyword: s.keyword,
      regulator: s.regulator,
      riskType: s.riskType,
      dateFrom: s.dateFrom,
      dateTo: s.dateTo,
      insuranceOnly: s.insuranceOnly,
      viewMode: s.viewMode,
      sortBy: s.sortBy,
      sortOrder: s.sortOrder,
      page: s.page,
      data: s.data,
      error: s.error,
      selected: s.selected,
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(slice));
  } catch {
    // quota / private mode
  }
}

let state: CasesSessionState = {
  ...defaultState,
  ...loadPersisted(),
  loading: false,
  exporting: false,
};
let runSeq = 0;
const listeners = new Set<() => void>();

function emit() {
  persist(state);
  listeners.forEach((l) => l());
}

function patch(partial: Partial<CasesSessionState>) {
  state = { ...state, ...partial };
  emit();
}

function buildParams(p: number, overrides?: Partial<CasesFilterParams>): CasesFilterParams {
  const base: CasesFilterParams = {
    page: p,
    page_size: state.viewMode === "table" ? 20 : 12,
    keyword: state.keyword.trim() || undefined,
    regulator: state.regulator.trim() || undefined,
    risk_type: state.riskType.trim() || undefined,
    is_insurance_related: state.insuranceOnly ? true : undefined,
    date_from: state.dateFrom || undefined,
    date_to: state.dateTo || undefined,
    sort_by: state.sortBy,
    sort_order: state.sortOrder,
  };
  return { ...base, ...overrides, page: overrides?.page ?? p };
}

export const casesSession = {
  getSnapshot: () => state,
  subscribe: (listener: () => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  setKeyword: (keyword: string) => patch({ keyword }),
  setRegulator: (regulator: string) => patch({ regulator }),
  setRiskType: (riskType: string) => patch({ riskType }),
  setDateFrom: (dateFrom: string) => patch({ dateFrom }),
  setDateTo: (dateTo: string) => patch({ dateTo }),
  setInsuranceOnly: (insuranceOnly: boolean) => patch({ insuranceOnly }),
  setViewMode: (viewMode: CasesViewMode) => patch({ viewMode }),
  setSortBy: (sortBy: CasesSortBy) => patch({ sortBy }),
  setSortOrder: (sortOrder: "asc" | "desc") => patch({ sortOrder }),
  setSelected: (selected: string[]) => patch({ selected }),
  toggleOne: (id: string) => {
    const set = new Set(state.selected);
    if (set.has(id)) set.delete(id);
    else set.add(id);
    patch({ selected: Array.from(set) });
  },
  toggleAllPage: () => {
    const ids = state.data?.items.map((i) => i.case_id) ?? [];
    const allSelected = ids.length > 0 && ids.every((id) => state.selected.includes(id));
    patch({ selected: allSelected ? [] : ids });
  },
  /**
   * 进入页面时调用：有缓存则直接展示；URL 带 risk_type 且与当前不同则覆盖并重载。
   */
  ensureLoaded: (urlRiskType?: string | null) => {
    const fromUrl = (urlRiskType ?? "").trim();
    if (fromUrl && fromUrl !== state.riskType) {
      patch({ riskType: fromUrl });
      void casesSession.load(1, { risk_type: fromUrl, page: 1 });
      return;
    }
    if (!state.data && !state.loading) {
      void casesSession.load(state.page);
    }
  },
  load: async (p: number, overrides?: Partial<CasesFilterParams>) => {
    const runId = ++runSeq;
    const params = buildParams(p, overrides);
    patch({ loading: true, error: null });
    try {
      const res = await api.listCases(params);
      if (runId !== runSeq) return;
      patch({
        data: res,
        page: p,
        selected: [],
        loading: false,
      });
    } catch (err) {
      if (runId !== runSeq) return;
      patch({
        error: err instanceof ApiError ? err.message : "加载案例失败",
        loading: false,
      });
    }
  },
  switchView: (mode: CasesViewMode) => {
    if (mode === state.viewMode) return;
    patch({ viewMode: mode });
    void casesSession.load(1, { page: 1, page_size: mode === "table" ? 20 : 12 });
  },
  toggleSort: (col: CasesSortBy) => {
    const nextOrder =
      state.sortBy === col
        ? state.sortOrder === "desc"
          ? "asc"
          : "desc"
        : col === "party_name"
          ? "asc"
          : "desc";
    patch({ sortBy: col, sortOrder: nextOrder });
    void casesSession.load(1, { sort_by: col, sort_order: nextOrder, page: 1 });
  },
  exportTable: async (format: "csv" | "xlsx") => {
    patch({ exporting: true, error: null });
    try {
      await api.exportCasesTable(
        {
          keyword: state.keyword.trim() || undefined,
          regulator: state.regulator.trim() || undefined,
          risk_type: state.riskType.trim() || undefined,
          is_insurance_related: state.insuranceOnly ? true : undefined,
          date_from: state.dateFrom || undefined,
          date_to: state.dateTo || undefined,
          sort_by: state.sortBy,
          sort_order: state.sortOrder,
          case_ids: state.selected.length ? state.selected.join(",") : undefined,
        },
        format,
      );
    } catch (err) {
      patch({
        error: err instanceof ApiError ? err.message : "导出失败",
      });
    } finally {
      patch({ exporting: false });
    }
  },
};

export function useCasesSession(): CasesSessionState {
  return useSyncExternalStore(
    casesSession.subscribe,
    casesSession.getSnapshot,
    casesSession.getSnapshot,
  );
}
