"""기존 경로 호환 — /health, /version, /chat, /chat/stream.

web_chat.html, web_demo_server.py, sh/run_agent_*.sh의 curl 예시가 이 경로를 쓴다.
새 클라이언트는 /api/v1을 쓰고, 이 경로들은 OpenAPI 문서에 deprecated로 표시한다.
"""
from fastapi import APIRouter, Depends, Request

from ..dependencies import get_runtime
from ..runtime import AgentRuntime
from ..schemas import ChatRequest
from . import chat as chat_v1
from .health import health_body

router = APIRouter(tags=["legacy"], deprecated=True)


@router.get("/health")
async def health(runtime: AgentRuntime = Depends(get_runtime)):
    return await health_body(runtime)


@router.get("/version")
async def version(runtime: AgentRuntime = Depends(get_runtime)):
    return {"supervisor_version": runtime.deps.version}


@router.post("/chat")
async def chat(req: ChatRequest, runtime: AgentRuntime = Depends(get_runtime)):
    return await chat_v1.chat(req, runtime)


@router.get("/chat/stream")
async def chat_stream(request: Request, message: str, thread_id: str = "default",
                      runtime: AgentRuntime = Depends(get_runtime)):
    return await chat_v1.chat_stream(request, message, thread_id, runtime)
