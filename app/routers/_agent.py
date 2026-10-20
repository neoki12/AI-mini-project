"""라우터 공통 — Agent 실행 실패를 AgentExecutionError로 바꾸고, SSE 프레임을 만든다."""
import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx

from agent.mcp_client import McpError

from ..activity import describe
from ..errors import AgentExecutionError
from ..runtime import AgentRuntime

logger = logging.getLogger("app")

# 외부 의존성(LLM API, MCP subprocess) 문제로 볼 예외 — 502로 응답한다.
# 그 밖의 예외는 코드 결함이므로 그대로 올려 500으로 처리한다.
EXTERNAL_ERRORS = (httpx.HTTPError, McpError, asyncio.TimeoutError, ConnectionError)

# 실행이 끝났을 때 (최종 상태, 활동 로그, LangSmith 실행 ID) → 추가로 보낼 이벤트 (예: ReviewSaved)
OnComplete = Callable[[dict, list[dict], str | None], Awaitable[dict | None]]


async def run_agent(runtime: AgentRuntime, message: str, thread_id: str,
                    forced_route: str | None = None) -> tuple[dict, str | None]:
    try:
        return await runtime.run(message, thread_id, forced_route=forced_route)
    except EXTERNAL_ERRORS as exc:
        raise AgentExecutionError(f"{type(exc).__name__}: {exc}") from exc


def sse(data) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"data: {payload}\n\n"


HEARTBEAT_SECONDS = 15.0   # 이 시간 동안 이벤트가 없으면 keep-alive 주석 프레임을 보낸다
_END = object()


async def _produce(queue: asyncio.Queue, events: AsyncIterator[dict]) -> None:
    """그래프 실행을 작업 하나에서 끝까지 돌리며 이벤트를 큐에 넣는다.

    실행을 작업 하나로 유지해야 LangGraph·LangSmith가 contextvars에 담는 실행 맥락이
    이벤트 사이에서 끊기지 않는다. 오류는 큐로 넘겨 응답 쪽에서 처리한다."""
    try:
        async for event in events:
            await queue.put(event)
        await queue.put(_END)
    except asyncio.CancelledError:
        raise
    except BaseException as exc:   # noqa: BLE001 — 응답 쪽에서 분류해 처리한다
        await queue.put(exc)


async def sse_stream(runtime: AgentRuntime, message: str, thread_id: str,
                     request_id: str | None, *, forced_route: str | None = None,
                     on_complete: OnComplete | None = None) -> AsyncIterator[str]:
    """Wave 3 — 이벤트마다 'data: {json}\\n\\n'으로 내려보내고 마지막에 data: [DONE]을 보낸다.

    - 이벤트에는 순번(seq), 활동 로그 문장(message), 서버 시각(ts, ms)을 붙인다
    - 이벤트가 HEARTBEAT_SECONDS 동안 없으면 ': keep-alive' 주석 프레임을 보낸다 — LLM이 오래
      생각하는 동안 프록시·로드밸런서가 유휴 연결을 끊지 않게 한다 (SSE 주석은 클라이언트가 무시)
    - 클라이언트가 연결을 끊으면 그래프 실행을 취소한다 — 미완성 검토는 저장하지 않는다
    - 실행 중 실패하면 Error 이벤트 후 정상 종료한다 (이미 200 헤더가 나가 상태 코드를 못 바꾼다)
    """
    activity: list[dict] = []
    queue: asyncio.Queue = asyncio.Queue()
    producer = asyncio.create_task(
        _produce(queue, runtime.stream(message, thread_id, forced_route=forced_route)))
    seq = 0
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is _END:
                break
            if isinstance(item, BaseException):
                raise item
            if item["type"] == "RunCompleted":
                if on_complete is not None:
                    extra = await on_complete(item["state"], activity, item.get("run_id"))
                    if extra:
                        seq += 1
                        yield sse({**extra, "seq": seq})
                continue
            seq += 1
            event = {**describe(item), "seq": seq, "ts": round(time.time() * 1000)}
            if event["type"] not in ("AnswerToken", "FinalAnswer"):
                activity.append(event)
            yield sse(event)
    except EXTERNAL_ERRORS as exc:
        logger.error("stream agent_failed request_id=%s: %s", request_id, exc)
        yield sse({"type": "Error", "code": "agent_failed", "request_id": request_id,
                   "message": "Agent 실행 중 외부 의존성(MCP·LLM) 오류가 발생했습니다."})
    except asyncio.CancelledError:
        logger.info("stream client_disconnected request_id=%s — 실행을 중단합니다", request_id)
        raise
    except Exception:
        logger.exception("stream internal_error request_id=%s", request_id)
        yield sse({"type": "Error", "code": "internal_error", "request_id": request_id,
                   "message": "서버 내부 오류가 발생했습니다."})
    finally:
        if not producer.done():
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await producer
    yield sse("[DONE]")
