import { describe, expect, it } from 'vitest'

import type { EvaluationJob } from '../api/types'
import { delta, formatMetric } from './admin'

const job = {
  experiments: [
    { profile: 'baseline', summary: { f1: 0.32, latency_s: 30.0, tokens: 2000 } },
    { profile: 'improved', summary: { f1: 0.94, latency_s: 34.5, tokens: 2500 } },
  ],
} as unknown as EvaluationJob

describe('delta', () => {
  it('정확도 지표는 오를수록, 지연·토큰은 내려갈수록 개선으로 본다', () => {
    expect(delta(job, 'f1')).toEqual({ text: '+0.62', better: true })
    expect(delta(job, 'latency_s')).toEqual({ text: '+4.5초', better: false })
    expect(delta(job, 'tokens')).toEqual({ text: '+500', better: false })
    expect(delta(job, 'recall').text).toBe('')   // 값 없음
  })
})

describe('formatMetric', () => {
  it('종류별로 표기한다', () => {
    expect(formatMetric(0.9432, 'ratio')).toBe('0.94')
    expect(formatMetric(34.3, 'seconds')).toBe('34.3초')
    expect(formatMetric(null, 'ratio')).toBe('-')
  })
})
