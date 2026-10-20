import { afterEach, describe, expect, it, vi } from 'vitest'

import { parseFrames, streamReview } from './stream'

afterEach(() => vi.unstubAllGlobals())

describe('parseFrames', () => {
  it('완성된 프레임만 꺼내고 덜 온 조각은 남긴다', () => {
    const { events, rest } = parseFrames('data: {"type":"NodeStarted","node":"classify"}\n\ndata: {"type":"Clas')
    expect(events).toEqual([{ type: 'NodeStarted', node: 'classify' }])
    expect(rest).toBe('data: {"type":"Clas')
  })

  it('keep-alive 주석 프레임은 무시한다', () => {
    const { events } = parseFrames(': keep-alive\n\ndata: {"type":"NodeStarted","seq":3}\n\n')
    expect(events).toEqual([{ type: 'NodeStarted', seq: 3 }])
  })

  it('[DONE] 센티널을 구분한다', () => {
    expect(parseFrames('data: [DONE]\n\n').events).toEqual(['[DONE]'])
  })
})

describe('streamReview', () => {
  it('청크가 프레임 중간에서 잘려 와도 이벤트를 순서대로 전달한다', async () => {
    const chunks = ['data: {"type":"NodeStarted","node":"route"}\n\nda', 'ta: {"type":"ReviewSaved","id":"rv-1"}\n\n',
      'data: [DONE]\n\n']
    const body = new ReadableStream({
      start(controller) {
        for (const c of chunks) controller.enqueue(new TextEncoder().encode(c))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200 })))
    const seen: string[] = []
    await streamReview('요청', (e) => seen.push(e.type))
    expect(seen).toEqual(['NodeStarted', 'ReviewSaved'])
  })

  it('422 같은 에러 응답은 ApiError로 던진다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ error: { code: 'validation_error', message: '요청 형식 오류' } }), { status: 422 })))
    await expect(streamReview('', () => {})).rejects.toMatchObject({ status: 422, code: 'validation_error' })
  })
})
