"""FastAPI 앱 팩토리 — create_app(settings).

- lifespan : AgentRuntime을 프로세스당 1회 생성·종료 (Wave 1)
- 미들웨어 : 요청 ID(X-Request-ID) 부여 + 접근 로그, CORS(Vue 개발 서버)
- 라우터   : /api/v1/{health, chat, reviews, admin} + 기존 경로 호환(legacy)
- 에러     : 단일 에러 응답 규격 (app/errors.py)
- 화면     : frontend/dist(Vue 빌드 결과)가 있으면 / 에서 서빙 — 운영은 서버 하나로 화면과 API 제공

LangSmith: 요청당 chat_request 루트 run 아래로 노드·LLM·MCP 호출이 계층 기록된다.
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()   # LANGCHAIN_TRACING_V2 / API_KEY / PROJECT — langsmith import보다 먼저

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .config import PROJECT_DIR, Settings  # noqa: E402
from .errors import install_error_handlers  # noqa: E402
from .evaluation import EvaluationManager  # noqa: E402
from .langsmith_service import LangSmithService  # noqa: E402
from .routers import admin, chat, health, legacy, reviews  # noqa: E402
from .runtime import AgentRuntime  # noqa: E402

API_PREFIX = "/api/v1"
logger = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = AgentRuntime(settings)
        await runtime.start()
        app.state.runtime = runtime
        app.state.langsmith = LangSmithService(settings.langsmith_project)
        app.state.evaluations = EvaluationManager(runtime, app.state.langsmith, runtime.reviews)
        yield
        await app.state.evaluations.shutdown()
        await runtime.stop()

    app = FastAPI(
        title="4M 변경 영향 검토 API",
        version="1.0.0",
        description="완성차 공장(프레스·차체·도장·의장)의 4M 변경 요청을 검토하는 "
                    "LangGraph 멀티 Agent 서비스. 교육용 가상 데이터를 사용한다.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info("%s %s %s %.0fms request_id=%s", request.method, request.url.path,
                    response.status_code, (time.perf_counter() - started) * 1000,
                    request_id)
        return response

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET", "POST"], allow_headers=["*"],
                       expose_headers=["X-Request-ID"])
    install_error_handlers(app)

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(chat.router, prefix=API_PREFIX)
    app.include_router(reviews.router, prefix=API_PREFIX)
    app.include_router(admin.router, prefix=API_PREFIX)
    app.include_router(legacy.router)

    # 라우터보다 나중에 마운트해야 /api, /health 등이 먼저 매칭된다
    dist = PROJECT_DIR / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
