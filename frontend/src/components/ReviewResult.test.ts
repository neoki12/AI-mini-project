import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { makeReview } from '../test-fixtures'
import ReviewResult from './ReviewResult.vue'

describe('ReviewResult', () => {
  it('등급, 층별 체크리스트, 근거를 보여 준다', () => {
    const wrapper = mount(ReviewResult, { props: { review: makeReview() } })
    const text = wrapper.text()
    expect(text).toContain('A등급 · 품질본부 승인')
    expect(text).toContain('필수 검증 항목')
    expect(text).toContain('조건부 항목')
    expect(text).toContain('QS-AS-001 Rev.F 조항 3')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('추가 확인 필요면 경고와 누락 항목을 강조한다', () => {
    const wrapper = mount(ReviewResult, {
      props: { review: makeReview({ review_status: '추가 확인 필요', missing_items: ['EXT-AS-01'], warnings: ['의장 공장의 공정 표준을 찾지 못했습니다.'] }) },
    })
    const alert = wrapper.find('[role="alert"]')
    expect(alert.text()).toContain('공정 표준을 찾지 못했습니다')
    expect(alert.text()).toContain('EXT-AS-01')
    expect(wrapper.find('tr.missing').text()).toContain('보고서 누락')
  })
})
