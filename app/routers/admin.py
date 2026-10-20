"""관리자 API — LangSmith 기반 운영 기능.

- GET  /api/v1/admin/langsmith           : 추적 상태, 프로젝트 링크
- GET  /api/v1/admin/runs                : 최근 실행(루트) 목록 — 상태, 소요 시간, 토큰, 피드백
- GET  /api/v1/admin/runs/{run_id}       : 실행 상세 — Agent(노드)별 소요 시간·토큰·호출 수
- GET  /api/v1/admin/feedback            : 사용자 피드백 목록
- POST /api/v1/admin/evaluations         : 평가 데이터셋으로 Baseline/Improved 실험 시작 (202)
- GET  /api/v1/admin/evaluations[/{id}]  : 평가 작업 목록·진행률·결과

ADMIN_TOKEN이 설정돼 있으면 X-Admin-Token 헤더가 일치해야 한다.
"""
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from ..evaluation import EvaluationManager
from ..langsmith_service import LangSmithService, LangSmithUnavailable
from ..schemas import (ErrorResponse, EvaluationJob, EvaluationRequest, FeedbackResponse,
                       LangSmithStatus, RunDetail, RunSummary)


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    expected = request.app.state.runtime.settings.admin_token
    if expected and not (x_admin_token and secrets.compare_digest(x_admin_token, expected)):
        raise HTTPException(status_code=401, detail="관리자 토큰이 필요합니다 (X-Admin-Token)")


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)],
                   responses={401: {"model": ErrorResponse}})


def _langsmith(request: Request) -> LangSmithService:
    return request.app.state.langsmith


def _evaluations(request: Request) -> EvaluationManager:
    return request.app.state.evaluations


def _unavailable(exc: LangSmithUnavailable):
    return HTTPException(status_code=503, detail=str(exc))


@router.get("/langsmith", response_model=LangSmithStatus)
async def langsmith_status(request: Request, ls: LangSmithService = Depends(_langsmith)):
    return {**await ls.status(),
            "admin_auth": bool(request.app.state.runtime.settings.admin_token)}


@router.get("/runs", response_model=list[RunSummary], responses={503: {"model": ErrorResponse}})
async def list_runs(limit: int = Query(20, ge=1, le=100), error_only: bool = False,
                    ls: LangSmithService = Depends(_langsmith)):
    try:
        return await ls.list_runs(limit=limit, error_only=error_only)
    except LangSmithUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/runs/{run_id}", response_model=RunDetail,
            responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def run_detail(run_id: str, ls: LangSmithService = Depends(_langsmith)):
    try:
        return await ls.run_detail(run_id)
    except LangSmithUnavailable as exc:
        raise _unavailable(exc) from exc
    except Exception as exc:   # 없는 run_id 등
        raise HTTPException(status_code=404, detail=f"실행을 찾을 수 없습니다: {run_id}") from exc


@router.get("/feedback", response_model=list[FeedbackResponse])
async def list_feedback(request: Request, limit: int = Query(50, ge=1, le=200)):
    return request.app.state.runtime.reviews.list_feedback(limit=limit)


@router.post("/evaluations", response_model=EvaluationJob, status_code=202,
             responses={409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def start_evaluation(req: EvaluationRequest,
                           ls: LangSmithService = Depends(_langsmith),
                           ev: EvaluationManager = Depends(_evaluations)):
    if not ls.enabled:
        raise HTTPException(status_code=503, detail="LangSmith 추적이 꺼져 있어 평가를 실행할 수 없습니다")
    try:
        return ev.start(list(dict.fromkeys(req.profiles)), limit=req.limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/evaluations", response_model=list[EvaluationJob])
async def list_evaluations(ev: EvaluationManager = Depends(_evaluations)):
    return ev.list()


@router.get("/evaluations/{job_id}", response_model=EvaluationJob,
            responses={404: {"model": ErrorResponse}})
async def get_evaluation(job_id: str, ev: EvaluationManager = Depends(_evaluations)):
    job = ev.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"평가 작업이 없습니다: {job_id}")
    return job
