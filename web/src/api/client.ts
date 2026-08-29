import type {
  ApiErrorBody,
  CaseDetail,
  CnRiskTag,
  DocumentItem,
  FeedbackRequest,
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

  cnTags: () => request<CnRiskTag[]>("/tags/cn"),

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

  confirmCase: (caseId: string) =>
    request<{ case_id: string; status: string }>(
      `/cases/${encodeURIComponent(caseId)}/confirm`,
      { method: "POST" },
    ),

  excludeCase: (caseId: string, reason?: string) =>
    request<{ case_id: string; status: string; candidate_reasons: string[] }>(
      `/cases/${encodeURIComponent(caseId)}/exclude`,
      jsonInit("POST", { reason: reason || null }),
    ),

  patchCase: (
    caseId: string,
    body: {
      party_name?: string;
      risk_tags?: string[];
      risk_type_ids?: string[];
      is_insurance_related?: boolean;
      regulator?: string;
      legal_basis?: string;
      violation_behavior?: string;
      penalty_content?: string;
      penalty_doc_no?: string;
    },
  ) =>
    request<{ case_id: string; updated_fields: string[] }>(
      `/cases/${encodeURIComponent(caseId)}`,
      jsonInit("PATCH", body),
    ),

  exportCasesTable: async (
    params: Record<string, string | number | boolean | undefined>,
    format: "csv" | "xlsx" = "csv",
  ) => {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === "") continue;
      sp.set(k, String(v));
    }
    sp.set("format", format);
    const res = await fetch(`${API_BASE}/cases/export/table?${sp.toString()}`);
    if (!res.ok) {
      const body = await res.text();
      throw new ApiError(res.status, body || `HTTP ${res.status}`, body);
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") ?? "";
    const match = /filename="?([^"]+)"?/i.exec(cd);
    const filename = match?.[1] ?? `penalty_cases.${format}`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },

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

  deleteDocument: (fileId: string) =>
    request<void>(`/documents/${encodeURIComponent(fileId)}`, { method: "DELETE" }),

  retryDocument: (fileId: string) =>
    request<UploadResponse>(`/documents/${encodeURIComponent(fileId)}/retry`, {
      method: "POST",
    }),

  generateReview: (body: ReviewGenerateRequest) =>
    request<ReviewGenerateResponse>("/review/generate", jsonInit("POST", body)),

  submitFeedback: (reviewId: string, body: FeedbackRequest) =>
    request<{ review_id: string; feedback: string }>(
      `/review/${encodeURIComponent(reviewId)}/feedback`,
      jsonInit("PATCH", body),
    ),

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

  saveMaterialHumanReview: (
    materialId: string,
    body: { note?: string; reviewer?: string; status?: string },
  ) =>
    request<{ material_id: string; review_status: string }>(
      `/review/material/${encodeURIComponent(materialId)}/human-review`,
      jsonInit("POST", body),
    ),

  exportMaterialReport: async (body: {
    material_id?: string;
    scene?: string | null;
    source_file?: string | null;
    file_name?: string | null;
    summary?: string;
    overall_suggestion?: string;
    risk_sentences?: MaterialReviewResponse["risk_sentences"];
    human_note?: string;
    human_review_done?: boolean;
  }) => {
    const res = await fetch(`${API_BASE}/review/material/export-report`, jsonInit("POST", body));
    if (!res.ok) {
      const text = await res.text();
      throw new ApiError(res.status, text || `HTTP ${res.status}`, text);
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") ?? "";
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    const plain = /filename="?([^";]+)"?/i.exec(cd);
    let filename = "合规审查报告.docx";
    if (star?.[1]) {
      try {
        filename = decodeURIComponent(star[1]);
      } catch {
        filename = star[1];
      }
    } else if (plain?.[1]) {
      filename = plain[1];
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },
};
