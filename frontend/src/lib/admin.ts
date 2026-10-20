// 관리자 화면 표시용 — 평가 지표 이름과 Before/After 비교.
import type { EvaluationJob } from '../api/types'

export const METRICS: { key: string; label: string; kind: 'ratio' | 'seconds' | 'count' }[] = [
  { key: 'f1', label: 'F1', kind: 'ratio' },
  { key: 'recall', label: 'Recall', kind: 'ratio' },
  { key: 'precision', label: 'Precision', kind: 'ratio' },
  { key: 'recall_required', label: 'Recall · 필수 항목', kind: 'ratio' },
  { key: 'recall_document', label: 'Recall · 조건부 항목', kind: 'ratio' },
  { key: 'recall_field', label: 'Recall · 현장 데이터', kind: 'ratio' },
  { key: 'recall_downstream', label: 'Recall · 다음 공정', kind: 'ratio' },
  { key: 'grade_correct', label: '변경 등급 정확도', kind: 'ratio' },
  { key: 'classification_correct', label: '분류 정확도', kind: 'ratio' },
  { key: 'latency_s', label: '평균 지연', kind: 'seconds' },
  { key: 'tokens', label: '평균 토큰', kind: 'count' },
]

export function formatMetric(value: number | null | undefined, kind: string): string {
  if (value === null || value === undefined) return '-'
  if (kind === 'ratio') return value.toFixed(2)
  if (kind === 'seconds') return `${value.toFixed(1)}초`
  return Math.round(value).toLocaleString()
}

// 개선(After) - 기준(Before). 지연·토큰은 늘어나면 비용이므로 방향을 따로 표시한다.
export function delta(job: EvaluationJob, key: string): { text: string; better: boolean | null } {
  const base = job.experiments.find((e) => e.profile === 'baseline')?.summary[key]
  const imp = job.experiments.find((e) => e.profile === 'improved')?.summary[key]
  if (base === null || base === undefined || imp === null || imp === undefined) {
    return { text: '', better: null }
  }
  const diff = imp - base
  const kind = METRICS.find((m) => m.key === key)?.kind ?? 'ratio'
  const sign = diff > 0 ? '+' : ''
  const text = kind === 'ratio' ? `${sign}${diff.toFixed(2)}`
    : kind === 'seconds' ? `${sign}${diff.toFixed(1)}초` : `${sign}${Math.round(diff).toLocaleString()}`
  if (Math.abs(diff) < 1e-9) return { text: '±0', better: null }
  const higherIsBetter = kind === 'ratio'
  return { text, better: higherIsBetter ? diff > 0 : diff < 0 }
}
