// 검토 스트리밍 — POST /api/v1/reviews/stream의 SSE 응답을 읽어 이벤트마다 콜백을 부른다.
//
// EventSource 대신 fetch + ReadableStream을 쓴다. EventSource는 GET만 되고, 연결이 끊기면
// 자동으로 재연결해 같은 검토를 다시 실행하기 때문이다.
import { ApiError } from './client'
import type { StreamEvent } from './types'

export function parseFrames(buffer: string): { events: (StreamEvent | '[DONE]')[]; rest: string } {
  const frames = buffer.split('\n\n')
  const rest = frames.pop() ?? ''   // 마지막 조각은 아직 덜 온 프레임일 수 있다
  const events: (StreamEvent | '[DONE]')[] = []
  for (const frame of frames) {
    const data = frame.split('\n').filter((l) => l.startsWith('data: ')).map((l) => l.slice(6)).join('\n')
    if (!data) continue
    events.push(data === '[DONE]' ? '[DONE]' : (JSON.parse(data) as StreamEvent))
  }
  return { events, rest }
}

export async function streamReview(
  message: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch('/api/v1/reviews/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message }),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'network_error', '서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요.')
  }
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body?.error?.code ?? `http_${res.status}`,
      body?.error?.message ?? res.statusText, body?.error?.request_id ?? res.headers.get('X-Request-ID'))
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parsed = parseFrames(buffer)
    buffer = parsed.rest
    for (const event of parsed.events) {
      if (event === '[DONE]') return
      onEvent(event)
    }
  }
}
