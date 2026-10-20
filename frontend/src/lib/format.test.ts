import { describe, expect, it } from 'vitest'

import type { ChecklistItem } from '../api/types'
import { evidenceText, groupChecklist, renderReport, statusLabel } from './format'

const item = (id: string, layer: ChecklistItem['layer'], evidence: Record<string, unknown>): ChecklistItem =>
  ({ id, name: id, layer, evidence })

describe('groupChecklist', () => {
  it('층 순서(필수 → 조건부 → 현장 → 다음 공정)로 묶고 빈 층은 뺀다', () => {
    const groups = groupChecklist([
      item('DS-PT-01', 'downstream', {}), item('COM-01', 'required', {}), item('EXT-BD-01', 'document', {}),
    ])
    expect(groups.map((g) => g.key)).toEqual(['required', 'document', 'downstream'])
  })
})

describe('evidenceText', () => {
  it('근거 종류별로 표기한다', () => {
    expect(evidenceText(item('COM-01', 'required', { rule: 'x', change_types: ['Method'] }))).toBe('규칙표 (공법)')
    expect(evidenceText(item('EXT-BD-01', 'document', { doc_id: 'QS-BD-001', rev: 'E', clause: '3' })))
      .toBe('QS-BD-001 Rev.E 조항 3')
    expect(evidenceText(item('EXT-EQ-01', 'field', {
      doc_id: 'QS-CM-001', rev: 'D', clause: '4', tool: 'equipment', targets: ['BD-RB-301'],
    }))).toBe('QS-CM-001 Rev.D 조항 4 · 설비 BD-RB-301')
    expect(evidenceText(item('DS-PT-02', 'downstream', { flow_rule: 'FLOW-03', subject: '실러 변경' })))
      .toBe('공정 흐름 FLOW-03 — 실러 변경')
  })
})

describe('renderReport', () => {
  it('굵게만 변환하고 HTML은 이스케이프한다', () => {
    expect(renderReport('**요약** <script>x</script>'))
      .toBe('<strong>요약</strong> &lt;script&gt;x&lt;/script&gt;')
  })
})

describe('statusLabel', () => {
  it('라인 상태를 한국어로 바꾸고 모르는 값은 그대로 둔다', () => {
    expect(statusLabel('running')).toBe('가동 중')
    expect(statusLabel('팁 교체 주기 초과')).toBe('팁 교체 주기 초과')
  })
})
