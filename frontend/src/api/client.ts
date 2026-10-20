// REST API 클라이언트 — /api/v1 호출과 단일 에러 규격({"error": {...}}) 해석을 한곳에서 한다.
import type {
  EvaluationJob, Feedback, Health, LangSmithStatus, Review, ReviewList, RunDetail, RunSummary,
} from './types'

const BASE = '/api/v1'
const ADMIN_TOKEN_KEY = 'admin-token'

// 관리자 토큰은 탭을 닫으면 사라지도록 sessionStorage에 둔다 (저장소 접근이 막혀도 동작)
export function getAdminToken(): string | null {
  try { return sessionStorage.getItem(ADMIN_TOKEN_KEY) } catch { return null }
}
export function setAdminToken(token: string | null) {
  try {
    if (token) sessionStorage.setItem(ADMIN_TOKEN_KEY, token)
    else sessionStorage.removeItem(ADMIN_TOKEN_KEY)
  } catch { /* 저장 불가 — 이번 요청에만 쓰지 못한다 */ }
}

function adminHeaders(): Record<string, string> {
  const token = getAdminToken()
  return token ? { 'X-Admin-Token': token } : {}
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId: string | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError(0, 'network_error', '서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요.')
  }
  if (!res.ok) {
    let body: { error?: { code?: string; message?: string; request_id?: string } } | null = null
    try {
      body = await res.json()
    } catch {
      body = null
    }
    throw new ApiError(
      res.status,
      body?.error?.code ?? `http_${res.status}`,
      body?.error?.message ?? res.statusText,
      body?.error?.request_id ?? res.headers.get('X-Request-ID'),
    )
  }
  return (await res.json()) as T
}

export const api = {
  health: () => request<Health>('/health'),
  createReview: (message: string) =>
    request<Review>('/reviews', { method: 'POST', body: JSON.stringify({ message }) }),
  listReviews: (limit = 20, offset = 0) =>
    request<ReviewList>(`/reviews?limit=${limit}&offset=${offset}`),
  getReview: (id: string) => request<Review>(`/reviews/${encodeURIComponent(id)}`),
  addFeedback: (id: string, score: 0 | 1, comment?: string) =>
    request<Feedback>(`/reviews/${encodeURIComponent(id)}/feedback`, {
      method: 'POST', body: JSON.stringify({ score, comment: comment || null }),
    }),
  listReviewFeedback: (id: string) => request<Feedback[]>(`/reviews/${encodeURIComponent(id)}/feedback`),

  admin: {
    langsmith: () => request<LangSmithStatus>('/admin/langsmith', { headers: adminHeaders() }),
    runs: (limit = 20, errorOnly = false) =>
      request<RunSummary[]>(`/admin/runs?limit=${limit}&error_only=${errorOnly}`, { headers: adminHeaders() }),
    run: (id: string) => request<RunDetail>(`/admin/runs/${encodeURIComponent(id)}`, { headers: adminHeaders() }),
    feedback: () => request<Feedback[]>('/admin/feedback', { headers: adminHeaders() }),
    evaluations: () => request<EvaluationJob[]>('/admin/evaluations', { headers: adminHeaders() }),
    evaluation: (id: string) =>
      request<EvaluationJob>(`/admin/evaluations/${encodeURIComponent(id)}`, { headers: adminHeaders() }),
    startEvaluation: (profiles: string[], limit?: number) =>
      request<EvaluationJob>('/admin/evaluations', {
        method: 'POST', headers: adminHeaders(), body: JSON.stringify({ profiles, limit: limit ?? null }),
      }),
  },
}
