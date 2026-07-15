import type {
  ApiErrorBody,
  CaseDetail,
  DocumentItem,
  HealthResponse,
  MaterialReviewResponse,
  Paginated,
  CaseListItem,
  RetrieveRequest,
  RetrieveResponse,
  ReviewGenerateRequest,
  ReviewGenerateResponse,
  RiskTag,
  StatsResponse,
  SubmissionResponse,
  UploadResponse,
} from "./types";

const API_BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function formatDetail(detail: ApiErrorBody["detail"]): string {
  if (detail == null) return "请求失败";
  if (typeof detail === "string") return detail;
  if (typeof detail === "object" && detail !== null && "detail" in detail) {
    const d = detail as { error?: string; detail?: string };
    return [d.error, d.detail].filter(Boolean).join("：") || "请求失败";
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return "请求失败";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (res.status === 204) return undefined as T;

  const contentType = res.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const body = isJson ? await res.json() : await res.text();

  if (!res.ok) {
    const message = isJson
      ? formatDetail((body as ApiErrorBody).detail)
      : typeof body === "string" && body
        ? body
        : `HTTP ${res.status}`;
    throw new ApiError(res.status, message, body);
  }
  return body as T;
}

function jsonInit(method: string, data: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  };
}

export const api = {
  health: () => request<HealthResponse>("/health"),

  stats: () => request<StatsResponse>("/stats"),

  tags: () => request<RiskTag[]>("/tags"),

  retrieve: (body: RetrieveRequest, format?: "submission") => {
    const qs = format ? `?format=${format}` : "";
    return request<RetrieveResponse | SubmissionResponse>(
      `/search/retrieve${qs}`,
      jsonInit("POST", body),
    );
  },

  listCases: (params: Record<string, string | number | boolean | undefined>) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === "") continue;
      sp.set(k, String(v));
    }
    const qs = sp.toString();
    return request<Paginated<CaseListItem>>(`/cases${qs ? `?${qs}` : ""}`);
  },

  getCase: (caseId: string) => request<CaseDetail>(`/cases/${encodeURIComponent(caseId)}`),

  listDocuments: (params: {
    page?: number;
    page_size?: number;
    parse_status?: string;
  }) => {
    const sp = new URLSearchParams();
    if (params.page) sp.set("page", String(params.page));
    if (params.page_size) sp.set("page_size", String(params.page_size));
    if (params.parse_status) sp.set("parse_status", params.parse_status);
    const qs = sp.toString();
    return request<Paginated<DocumentItem>>(`/documents${qs ? `?${qs}` : ""}`);
  },

  getDocument: (fileId: string) =>
    request<DocumentItem>(`/documents/${encodeURIComponent(fileId)}`),

  uploadDocument: async (file: File, meta?: { regulator?: string; publish_date?: string }) => {
    const fd = new FormData();
    fd.append("file", file);
    if (meta?.regulator) fd.append("regulator", meta.regulator);
    if (meta?.publish_date) fd.append("publish_date", meta.publish_date);
    return request<UploadResponse>("/documents/upload", { method: "POST", body: fd });
  },

  retryDocument: (fileId: string) =>
    request<UploadResponse>(`/documents/${encodeURIComponent(fileId)}/retry`, {
      method: "POST",
    }),

  generateReview: (body: ReviewGenerateRequest) =>
    request<ReviewGenerateResponse>("/review/generate", jsonInit("POST", body)),

  reviewMaterialText: (text: string, scene?: string) =>
    request<MaterialReviewResponse>(
      "/review/material",
      jsonInit("POST", { text, scene: scene || null }),
    ),

  reviewMaterialUpload: async (file: File, scene?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (scene) fd.append("scene", scene);
    return request<MaterialReviewResponse>("/review/material/upload", {
      method: "POST",
      body: fd,
    });
  },
};
