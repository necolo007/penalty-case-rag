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
  /** 最终分类：27 类中文标签 */
  predicted_cn_tags?: string[];
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
  fine_amount?: string | null;
  regulator: string | null;
  publish_date: string | null;
  risk_tags: string[] | null;
  risk_type_ids: string[] | null;
  is_insurance_related: boolean | null;
  overall_confidence: number | null;
  source_file: string | null;
}

export interface ExtractedCaseSummary {
  case_id: string;
  party_name: string | null;
  penalty_doc_no: string | null;
  violation_behavior: string | null;
  penalty_content: string | null;
  fine_amount?: string | null;
  regulator: string | null;
  publish_date: string | null;
  legal_basis?: string | null;
  risk_tags: string[] | null;
  risk_type_ids: string[] | null;
  overall_confidence: number | null;
  field_confidences?: Record<string, string | number> | null;
  extraction_method?: string | null;
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
  cases?: ExtractedCaseSummary[];
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
  cn_tag_distribution?: Record<string, number>;
  document_status: Record<string, number>;
  /** 待复核候选数（材料审查未完成 + 未反馈审查日志） */
  pending_review_count?: number | null;
  /** 标签覆盖率 0~1；无数据时为 null */
  tag_coverage_rate?: number | null;
  /** 主体标准化完成率 0~1；无数据时为 null */
  entity_normalize_rate?: number | null;
  /** 风险标签树 + 真实案例数 */
  tag_tree?: Array<{
    risk_type_id: string;
    parent_id: string | null;
    level: number;
    risk_type_name: string;
    case_count: number;
  }>;
}

export interface CnRiskTag {
  risk_tag: string;
  description: string;
  category: string;
  competition_id?: string;
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
  /** 后端 overall_suggestion 的前端别名 */
  summary?: string;
  overall_suggestion?: string;
  source_file?: string | null;
  file_name?: string | null;
  raw_text?: string | null;
  /** 后端 sentence_reviews 的前端别名（已在 to_dict 中映射） */
  risk_sentences?: Array<{
    text?: string;
    risk_level?: string;
    suggestion?: string;
    risk_types?: string[];
    risk_type_ids?: string[];
    compliance_reason?: string;
    confidence?: number;
    position_start?: number;
    position_end?: number;
    paragraph_idx?: number;
    hit_case_id?: string | null;
    hit_penalty_doc_no?: string | null;
    hit_party_name?: string | null;
    case_key_field?: string | null;
    match_reason?: string | null;
    source_file?: string | null;
    retrieved_cases?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  }>;
  case_blocks?: Array<{
    block_id: string;
    paragraph_idx: number;
    label: string;
    risk_sentences: Array<Record<string, unknown>>;
  }>;
  sentence_reviews?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export type FeedbackVerdict = "agree" | "disagree" | "partial";

export interface FeedbackRequest {
  feedback: FeedbackVerdict;
  feedback_note?: string;
  reviewer?: string;
}

export interface ApiErrorBody {
  detail?: string | { error?: string; detail?: string; cause?: string } | unknown;
}
