"""라우터가 쓰는 FastAPI 의존성 — 라우터는 app.state를 직접 만지지 않는다."""
from fastapi import Request

from .runtime import AgentRuntime


def get_runtime(request: Request) -> AgentRuntime:
    return request.app.state.runtime
