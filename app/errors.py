"""에러 응답 규격과 예외 처리.

모든 에러는 {"error": {"code", "message", "request_id", "details"}} 한 가지 모양으로
내려간다. 프론트엔드는 HTTP 상태 코드와 error.code만 보고 분기하면 된다.

- 422 validation_error : 요청 스키마 위반
- 422 not_a_change_request : 4M 변경 요청이 아닌 입력 (검토하지 않음)
- 404 not_found        : 없는 리소스 (예: 검토 ID)
- 502 agent_failed     : Agent 실행 중 MCP·LLM 등 외부 의존성 실패
- 500 internal_error   : 그 밖의 예상하지 못한 오류
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app")


class AgentExecutionError(Exception):
    """Agent 실행이 외부 의존성(MCP 서버, LLM API) 문제로 실패했을 때."""


class NotAChangeRequest(Exception):
    """검토 범위 밖 입력 — 4M 변경 요청이 아니라고 판단했을 때."""


def _error(request: Request, status: int, code: str, message: str, details=None):
    body = {"code": code, "message": message,
            "request_id": getattr(request.state, "request_id", None)}
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=status, content={"error": body})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return _error(request, 422, "validation_error", "요청 형식이 올바르지 않습니다.",
                      details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = "not_found" if exc.status_code == 404 else f"http_{exc.status_code}"
        return _error(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(NotAChangeRequest)
    async def _out_of_scope(request: Request, exc: NotAChangeRequest):
        return _error(request, 422, "not_a_change_request", str(exc))

    @app.exception_handler(AgentExecutionError)
    async def _agent(request: Request, exc: AgentExecutionError):
        logger.error("agent_failed request_id=%s: %s",
                     getattr(request.state, "request_id", None), exc)
        return _error(request, 502, "agent_failed",
                      "Agent 실행 중 외부 의존성(MCP·LLM) 오류가 발생했습니다.")

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        logger.exception("internal_error request_id=%s",
                         getattr(request.state, "request_id", None))
        return _error(request, 500, "internal_error", "서버 내부 오류가 발생했습니다.")
