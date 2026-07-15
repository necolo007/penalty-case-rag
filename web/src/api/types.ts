/** 与后端 api/schemas 及路由响应对齐的类型 */

export interface RetrieveRequest {
  query_text: string;
  question_id?: string | null;
  scene?: string | null;
  risk_type?: string | null;
  regulator?: string | null;
  institution_type?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  top_k?: number;
  use_reranker?: boolean;
}

export interface CaseResult {
  rank: number;
  case_id: string;
  party_name: string;
  penalty_doc_no: string;
  violation_behavior: string;
  penalty_content: string;
  regulator: string;
  risk_tags: string[];
  score: number;
  match_reason: string;
  source_file: string;
  channels: string[];
}

export interface RetrieveResponse {
  query: string;
  rewritten_query: string;
  predicted_risk_ids: string[];
  results: CaseResult[];
  channel_stats: Record<string, number>;
  took_ms: number;
}

export interface SubmissionCase {
  case_id: string;
  rank: number;
  reason: string;
}

export interface SubmissionResponse {
  question_id?: string | null;
  risk_type: string;
  retrieved_cases: SubmissionCase[];
  suggestion: string;
}

export interface CaseListItem {
  case_id: string;
  party_name: string | null;
  institution_type: string | null;
  penalty_doc_no: string | null;
  violation_behavior: string | null;
  penalty_content: string | null;
  regulator: string | null;
  publish_date: string | null;
  risk_tags: string[] | null;
  risk_type_ids: string[] | null;
  is_insurance_related: boolean | null;
  overall_confidence: number | null;
  source_file: string | null;
}

export interface Paginated<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface CaseDetail extends CaseListItem {
  file_id?: string;
  legal_basis?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  [key: string]: unknown;
}

export interface DocumentItem {
  file_id: string;
  file_name: string;
  source_type: string;
  regulator: string | null;
  publish_date: string | null;
  parse_status: string;
  parse_error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  raw_text_path?: string | null;
}

export interface UploadResponse {
  file_id: string;
  status: string;
  message: string;
}

export interface StatsResponse {
  documents: number;
  cases: number;
  insurance_cases: number;
  embedded_cases: number;
  tag_distribution: Record<string, number>;
  document_status: Record<string, number>;
}

export interface HealthResponse {
  status: string;
  database: boolean;
}

export interface RiskTag {
  risk_type_id: string;
  competition_id: string | null;
  parent_id: string | null;
  level: number;
  risk_type_name: string;
  display_tags: string[] | null;
  keywords: string[] | null;
  description: string | null;
}

export interface ReviewGenerateRequest {
  query_text: string;
  top_k?: number;
  generate_suggestion?: boolean;
}

export interface ReviewGenerateResponse {
  review_id: string;
  query_text: string;
  rewritten_query: string;
  risk_types?: string[];
  suggestion?: string;
  case_analysis?: Array<{
    case_id?: string;
    similarity_reason?: string;
    [key: string]: unknown;
  }>;
  took_ms: number;
  [key: string]: unknown;
}

export interface MaterialReviewResponse {
  material_id?: string;
  overall_risk?: string;
  summary?: string;
  risk_sentences?: Array<{
    text?: string;
    risk_level?: string;
    suggestion?: string;
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
}

export interface ApiErrorBody {
  detail?: string | { error?: string; detail?: string; cause?: string } | unknown;
}
