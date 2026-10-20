"""대화형 엔드포인트 — 라우팅 LLM이 잡담(chat)과 4M 검토(review)를 고른다.

- POST /api/v1/chat         : 끝까지 실행한 뒤 한 번에 응답
- GET  /api/v1/chat/stream  : 진행 과정을 SSE로 스트리밍 (Wave 3)
"""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from ..dependencies import get_runtime
from ..runtime import AgentRuntime
from ..schemas import THREAD_ID_PATTERN, ChatRequest, ChatResponse, ErrorResponse
from ._agent import run_agent, sse_stream

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse,
             responses={422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
async def chat(req: ChatRequest, runtime: AgentRuntime = Depends(get_runtime)):
    result, run_id = await run_agent(runtime, req.message, req.thread_id)
    return {"reply": result["final"], "events": result.get("events", []),
            "metadata": runtime.metadata(result, run_id)}


@router.get("/stream", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}}})
async def chat_stream(request: Request,
                      message: str = Query(min_length=1, max_length=2000),
                      thread_id: str = Query("default", pattern=THREAD_ID_PATTERN),
                      runtime: AgentRuntime = Depends(get_runtime)):
    return StreamingResponse(
        sse_stream(runtime, message, thread_id, request.state.request_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
