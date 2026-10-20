// 백엔드 app/schemas.py와 1:1로 맞춘 응답 타입 — 스키마를 바꾸면 여기도 함께 바꾼다.

export type Layer = 'required' | 'document' | 'field' | 'downstream'
export type Grade = 'A' | 'B' | 'C'
export type ReviewStatus = '검토 완료' | '추가 확인 필요'

export interface ChecklistItem {
  id: string
  name: string
  layer: Layer
  evidence: Record<string, unknown>
}

export interface Grading {
  grade: Grade
  approver: string
  initial_flow_period: string
  reason: string
}

export interface DocumentRef {
  doc_id: string
  rev: string
  title: string
  doc_type: 'standard' | 'inspection'
}

export interface FieldFinding {
  kind: 'equipment' | 'production'
  target: string
  status: string
  abnormal: boolean
  note: string
  failed?: boolean
}

export interface RunMetadata {
  route: string | null
  task_count: number
  gate_added: number
  gate_removed: number
  replan_rounds: number
  retry_count: number
  validation_attempts: number
  cost_usd: number
  tokens: number
  features: Record<string, boolean>
  llm_backend: string
  supervisor_version: string
  instance_id: number | null
  langsmith_run_id: string | null
}

export interface Review {
  id: string
  created_at: string
  thread_id: string
  request: string
  parent_id?: string | null
  supplement?: string | null
  shop: string | null
  change_types: string[]
  documents: DocumentRef[]
  field_findings: FieldFinding[]
  checklist: ChecklistItem[]
  grading: Grading | null
  review_status: ReviewStatus | null
  missing_items: string[]
  citation_issues?: string[]
  warnings: string[]
  reply: string
  events: StreamEvent[]
  metadata: RunMetadata
}

export interface ReviewSummary {
  id: string
  created_at: string
  request: string
  shop: string | null
  change_types: string[]
  grading: Grading | null
  review_status: ReviewStatus | null
}

export interface ReviewList {
  items: ReviewSummary[]
  total: number
  limit: number
  offset: number
}

export interface Health {
  status: 'ok' | 'degraded'
  mcp_servers: Record<string, { name?: string; version?: string; ok: boolean }>
  instance_id: number
  creation_count: number
  supervisor_version: string
  llm_backend: string
  fast_llm: string
  quality_llm: string
}

// 스트리밍·활동 로그 이벤트 (app/activity.py가 message를 붙인다)
export interface StreamEvent {
  type: string
  node?: string
  agent?: string
  message?: string
  ts?: number
  elapsed_ms?: number
  error?: boolean
  delta?: string
  attempt?: number
  id?: string
  code?: string
  request_id?: string
  review_status?: string
  [key: string]: unknown
}

// ── 피드백·관리자 (app/schemas.py) ─────────────────────────────────────
export interface Feedback {
  id: string
  review_id: string
  score: number
  comment: string | null
  langsmith_feedback_id: string | null
  created_at: string
  request?: string | null
}

export interface LangSmithStatus {
  enabled: boolean
  project: string
  reachable: boolean
  project_url: string | null
  error: string | null
  admin_auth: boolean
}

export interface RunSummary {
  id: string
  name: string
  status: string | null
  start_time: string | null
  latency_s: number | null
  total_tokens: number
  error: string | null
  tags: string[]
  thread_id: string | null
  feedback: Record<string, { n?: number; avg?: number }>
  url: string | null
}

export interface RunStep {
  name: string
  status: string | null
  latency_s: number | null
  tokens: number
  llm_calls: number
  tool_calls: number
  error: string | null
}

export interface RunDetail extends RunSummary {
  steps: RunStep[]
  inputs_preview: string
}

export interface ExperimentResult {
  profile: string
  experiment: string
  url: string | null
  summary: Record<string, number | null>
  cases: Record<string, unknown>[]
}

export interface EvaluationJob {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  created_at: string
  finished_at?: string | null
  profiles: string[]
  case_count: number
  llm_backend: string
  progress: { done: number; total: number }
  dataset: string
  dataset_sync?: string | null
  experiments: ExperimentResult[]
  error: string | null
}
