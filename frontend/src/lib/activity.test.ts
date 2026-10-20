import { describe, expect, it } from 'vitest'

import type { StreamEvent } from '../api/types'
import { buildSteps, formatElapsed } from './activity'

describe('buildSteps', () => {
  it('시작 → 결과 → 종료를 하나의 단계로 묶고, 끝나지 않은 단계는 진행 중으로 둔다', () => {
    const events: StreamEvent[] = [
      { type: 'NodeStarted', node: 'standards', agent: 'Standards', message: '공정 표준을 읽고 있어요' },
      { type: 'NodeStarted', node: 'field', agent: 'Field Data', message: '설비 상태를 조회하고 있어요' },
      { type: 'TaskCompleted', node: 'standards', message: 'QS-BD-001 Rev.E를 읽었어요' },
      { type: 'NodeFinished', node: 'standards', elapsed_ms: 1500 },
      { type: 'AnswerToken', delta: '무시' },
    ]
    const steps = buildSteps(events)
    expect(steps.map((s) => [s.node, s.status])).toEqual([['standards', 'done'], ['field', 'running']])
    expect(steps[0].details).toEqual([{ text: 'QS-BD-001 Rev.E를 읽었어요', warn: false }])
    expect(formatElapsed(steps[0].elapsedMs)).toBe('1.5초')
  })

  it('검수 반려와 fallback은 경고로 표시한다', () => {
    const steps = buildSteps([
      { type: 'NodeStarted', node: 'validate', agent: 'Validator', message: '검수 중' },
      { type: 'Validation', node: 'validate', verdict: '불합격', message: '검수 반려: 2건 누락' },
    ])
    expect(steps[0].details[0].warn).toBe(true)
  })

  it('NodeStarted가 없는 저장 이벤트도 노드별 단계로 보여 준다', () => {
    const steps = buildSteps([
      { type: 'Classified', node: 'classify', agent: 'Classifier', message: '분류 결과: 차체' },
      { type: 'PlanCreated', node: 'plan', agent: 'Planner', message: '조사 계획 3건' },
    ])
    expect(steps.map((s) => [s.agent, s.title, s.status])).toEqual([
      ['Classifier', '분류 결과: 차체', 'done'], ['Planner', '조사 계획 3건', 'done']])
  })
})
