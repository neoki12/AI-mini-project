import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError } from './client'

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('에러 응답을 ApiError(code, message, request_id)로 바꾼다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ error: { code: 'agent_failed', message: '외부 의존성 오류', request_id: 'req-1' } }),
      { status: 502 },
    )))
    const err = await api.createReview('x').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 502, code: 'agent_failed', requestId: 'req-1' })
  })

  it('네트워크 실패는 network_error로 알린다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('failed') }))
    await expect(api.health()).rejects.toMatchObject({ code: 'network_error', status: 0 })
  })

  it('검토 생성은 POST /api/v1/reviews로 보낸다', async () => {
    const fetchMock = vi.fn(async () => new Response('{"id":"rv-1"}', { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)
    await api.createReview('용접 전류 변경')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/reviews', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ message: '용접 전류 변경' }),
    }))
  })
})
