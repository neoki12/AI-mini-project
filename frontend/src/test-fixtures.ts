import type { Review } from './api/types'

export function makeReview(overrides: Partial<Review> = {}): Review {
  return {
    id: 'rv-test', created_at: '2026-10-20T04:00:00+00:00', thread_id: 't', request: '브레이크 호스 브래킷 협력사 변경',
    shop: '의장', change_types: ['Material'],
    documents: [{ doc_id: 'QS-AS-001', rev: 'F', title: '의장 공장 공정 표준', doc_type: 'standard' }],
    field_findings: [],
    checklist: [
      { id: 'COM-01', name: 'PFMEA 갱신', layer: 'required', evidence: { rule: 'required_items.json', change_types: ['Material'] } },
      { id: 'EXT-AS-01', name: '안전 체결부 변경', layer: 'document', evidence: { doc_id: 'QS-AS-001', rev: 'F', clause: '3' } },
    ],
    grading: { grade: 'A', approver: '품질본부 승인', initial_flow_period: '3개월', reason: '안전 체결부' },
    review_status: '검토 완료', missing_items: [], warnings: [], reply: '1) 변경 요약 ...', events: [],
    metadata: {
      route: 'review', task_count: 4, gate_added: 2, gate_removed: 0, replan_rounds: 0, retry_count: 0,
      validation_attempts: 2, cost_usd: 0.0012, tokens: 2400, features: {}, llm_backend: 'fake',
      supervisor_version: 'v2', instance_id: 1, langsmith_run_id: null,
    },
    ...overrides,
  }
}
