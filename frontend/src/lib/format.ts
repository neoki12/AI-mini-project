// 화면 표시용 변환 — 백엔드 agent/agents/writer.py의 근거 표기와 같은 규칙을 쓴다.
import type { ChecklistItem, Layer } from '../api/types'

export const LAYERS: { key: Layer; label: string; hint: string }[] = [
  { key: 'required', label: '필수 검증 항목', hint: '변경 유형별 규칙표' },
  { key: 'document', label: '조건부 항목', hint: '표준서 조항의 조건에 해당' },
  { key: 'field', label: '현장 데이터 항목', hint: '설비·라인 상태 조회 결과' },
  { key: 'downstream', label: '다음 공정 영향', hint: '공정 흐름 규칙' },
]

export const CHANGE_TYPE_LABELS: Record<string, string> = {
  Man: '작업자', Machine: '설비', Material: '재료', Method: '공법',
}

export function groupChecklist(items: ChecklistItem[]) {
  return LAYERS.map((layer) => ({ ...layer, items: items.filter((i) => i.layer === layer.key) }))
    .filter((group) => group.items.length > 0)
}

export function evidenceText(item: ChecklistItem): string {
  const ev = item.evidence as Record<string, string | string[] | undefined>
  if (ev.flow_rule) return `공정 흐름 ${ev.flow_rule} — ${ev.subject ?? ''}`.trim()
  if (ev.rule) {
    const types = (ev.change_types as string[] | undefined) ?? []
    return `규칙표 (${types.map((t) => CHANGE_TYPE_LABELS[t] ?? t).join(', ')})`
  }
  let text = ev.doc_id ? `${ev.doc_id} Rev.${ev.rev} 조항 ${ev.clause}` : '공통 규정'
  const targets = (ev.targets as string[] | undefined) ?? []
  if (targets.length) text += ` · ${ev.tool === 'equipment' ? '설비' : '라인'} ${targets.join(', ')}`
  return text
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
}

export const EXAMPLE_REQUESTS = [
  '차체 대시 패널 라인 용접 로봇(BD-RB-301, BD-RB-302)의 용접 전류 조건을 변경합니다.',
  '협력사로부터 브레이크 호스 브래킷 부품의 4M 변경 신고(생산 공장 이전)가 접수됐습니다. 의장 공장 기준으로 검토해주세요.',
  '루프 패널용 강판의 공급사를 기존 X제철에서 Y제철로 변경합니다. 재질과 두께 사양은 동일합니다.',
  '차체 플로어 라인(BD-FLOOR)에 신규 용접 지그를 도입하고, 같은 시점에 구조용 접착제를 B사 제품으로 변경합니다.',
]

const STATUS_LABELS: Record<string, string> = {
  running: '가동 중', planned_stop: '계획정지', unknown: '확인 불가',
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

// LLM 보고서의 최소 마크다운(**굵게**)만 표시한다. 먼저 HTML을 이스케이프하므로 v-html에 넣어도 안전하다.
export function renderReport(text: string): string {
  const escaped = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
  return escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
}
