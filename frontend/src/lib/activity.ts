// 스트림 이벤트 → 활동 로그 단계(step) 목록.
//
// NodeStarted가 단계를 열고(진행 중), 같은 노드의 결과 이벤트가 세부 줄로 붙고,
// NodeFinished가 단계를 닫는다(완료 + 소요 시간). 저장된 검토처럼 NodeStarted가 없는
// 이벤트 목록도 노드별로 묶어 완료된 단계로 보여 준다.
import type { StreamEvent } from '../api/types'

export type StepStatus = 'running' | 'done' | 'error'

export interface ActivityDetail {
  text: string
  warn: boolean
}

export interface ActivityStep {
  key: string
  node: string
  agent: string
  title: string
  status: StepStatus
  elapsedMs: number | null
  details: ActivityDetail[]
}

const IGNORED = new Set(['AnswerToken', 'FinalAnswer', 'ReviewSaved'])

function isWarning(e: StreamEvent): boolean {
  if (e.type === 'FallbackUsed' || e.type === 'Error') return true
  if (e.type === 'Validation') return e.verdict !== '합격'
  if (e.type === 'ReplanCheck') return e.is_sufficient === false
  if (e.type === 'TaskCompleted') return e.found === false || e.failed === true
  return false
}

export function buildSteps(events: StreamEvent[]): ActivityStep[] {
  const steps: ActivityStep[] = []
  const lastOpen = (node: string) =>
    [...steps].reverse().find((s) => s.node === node && s.status === 'running')
  const lastOf = (node: string) => [...steps].reverse().find((s) => s.node === node)

  for (const e of events) {
    if (IGNORED.has(e.type)) continue
    if (e.type === 'Queued') {   // 동시 실행 대기 — 실제 검토가 시작되면 완료로 바뀐다
      steps.push({ key: `queue-${steps.length}`, node: 'queue', agent: '대기열',
        title: e.message ?? '대기 중', status: 'running', elapsedMs: null, details: [] })
      continue
    }
    if (e.type === 'Error') {
      steps.push({ key: `error-${steps.length}`, node: 'error', agent: '오류', title: e.message ?? '오류',
        status: 'error', elapsedMs: null, details: [] })
      continue
    }
    const node = e.node ?? 'unknown'
    if (e.type === 'NodeStarted') {
      steps.filter((st) => st.node === 'queue' && st.status === 'running').forEach((st) => { st.status = 'done' })
      steps.push({ key: `${node}-${steps.length}`, node, agent: e.agent ?? node,
        title: e.message ?? `${node} 실행 중`, status: 'running', elapsedMs: null, details: [] })
      continue
    }
    if (e.type === 'NodeFinished') {
      const step = lastOpen(node)
      if (step) {
        step.status = e.error ? 'error' : 'done'
        step.elapsedMs = e.elapsed_ms ?? null
      }
      continue
    }
    if (!e.message) continue
    let step = lastOpen(node) ?? lastOf(node)
    if (!step) {   // NodeStarted가 없는 저장 이벤트 — 노드별 완료 단계로 만든다
      step = { key: `${node}-${steps.length}`, node, agent: e.agent ?? node, title: e.message,
        status: 'done', elapsedMs: null, details: [] }
      steps.push(step)
      if (isWarning(e)) step.details.push({ text: e.message, warn: true })
      continue
    }
    step.details.push({ text: e.message, warn: isWarning(e) })
  }
  return steps
}

export function formatElapsed(ms: number | null): string {
  if (ms === null) return ''
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}초`
}
