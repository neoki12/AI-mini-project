"""4M 검토 엔드포인트 — 항상 검토(review) 경로로 실행하고 결과를 이력으로 남긴다.

- POST /api/v1/reviews        : 검토 실행 + 저장 (201)
- POST /api/v1/reviews/stream : 검토 실행 과정을 SSE 활동 로그로 스트리밍 + 끝나면 저장
- POST /api/v1/reviews/{id}/feedback : 사용자 평가(👍/👎) — 로컬 저장 + LangSmith 실행에 기록
- GET  /api/v1/reviews/{id}/feedback : 그 검토에 남긴 평가 목록
- GET  /api/v1/reviews        : 검토 이력 목록 (최신순, 페이지네이션)
- GET  /api/v1/reviews/{id}   : 검토 상세
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..dependencies import get_runtime
from ..runtime import AgentRuntime
from ..schemas import (ErrorResponse, FeedbackRequest, FeedbackResponse, ReviewListResponse,
                       ReviewRequest, ReviewResponse)
from ..activity import describe
from ..errors import NotAChangeRequest
from ._agent import run_agent, sse_stream

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _documents(documents: list[dict]) -> list[dict]:
    docs, seen = [], set()
    for d in documents:
        if not d["found"] or d["doc_id"] in seen:
            continue
        seen.add(d["doc_id"])
        docs.append({"doc_id": d["doc_id"], "rev": d["rev"] or "", "title": d["title"] or "",
                     "doc_type": d["doc_type"]})
    return docs


def _field_findings(findings: list[dict]) -> list[dict]:
    return [{"kind": f["kind"], "target": f["target"], "status": f["status"] or "unknown",
             "abnormal": f["abnormal"], "note": f["note"], "failed": f.get("failed", False)}
            for f in findings]


@router.post("", response_model=ReviewResponse, status_code=201,
             responses={422: {"model": ErrorResponse,
                              "description": "요청 형식 오류 또는 4M 변경 요청이 아님"},
                         502: {"model": ErrorResponse}})
async def create_review(req: ReviewRequest, runtime: AgentRuntime = Depends(get_runtime)):
    thread_id = req.thread_id or f"review-{uuid.uuid4().hex[:12]}"
    result, run_id = await run_agent(runtime, req.message, thread_id, forced_route="review")
    if result.get("route") == "out_of_scope":   # 검토하지 않았으므로 이력에 남기지 않는다
        raise NotAChangeRequest(result["final"])
    events = [describe(e) for e in result.get("events", [])]
    return runtime.reviews.save(thread_id, req.message,
                                _review_body(runtime, result, events, run_id))


@router.post("/stream", response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}}},
                        422: {"model": ErrorResponse}})
async def stream_review(req: ReviewRequest, request: Request,
                        runtime: AgentRuntime = Depends(get_runtime)):
    """검토 진행 과정을 활동 로그로 스트리밍한다.

    이벤트: NodeStarted(Agent 시작, message) · Agent 결과 이벤트(message) · NodeFinished
    (elapsed_ms) · AnswerToken(보고서 토큰) · FinalAnswer · ReviewSaved(id) · [DONE].
    GET + EventSource 대신 POST를 쓴다 — EventSource는 연결이 끊기면 자동 재연결해 같은
    검토를 다시 실행하기 때문이다."""
    thread_id = req.thread_id or f"review-{uuid.uuid4().hex[:12]}"

    async def save(state: dict, activity: list[dict], run_id: str | None) -> dict:
        if state.get("route") == "out_of_scope":
            return {"type": "OutOfScope", "code": "not_a_change_request",
                    "message": state.get("final", "")}
        review = runtime.reviews.save(thread_id, req.message,
                                      _review_body(runtime, state, activity, run_id))
        return {"type": "ReviewSaved", "id": review["id"],
                "review_status": review["review_status"]}

    return StreamingResponse(
        sse_stream(runtime, req.message, thread_id, request.state.request_id,
                   forced_route="review", on_complete=save),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _review_body(runtime: AgentRuntime, result: dict, events: list[dict],
                 run_id: str | None) -> dict:
    classification = result.get("classification", {})
    return {
        "shop": classification.get("shop"),
        "change_types": classification.get("change_types", []),
        "documents": _documents(result.get("documents", [])),
        "field_findings": _field_findings(result.get("findings", [])),
        "checklist": result.get("checklist", []),
        "grading": result.get("grading"),
        "review_status": result.get("review_status"),
        "missing_items": result.get("missing_items", []),
        "warnings": result.get("warnings", []),
        "reply": result.get("final", ""),
        "events": events,
        "metadata": runtime.metadata(result, run_id),
    }


@router.get("", response_model=ReviewListResponse)
async def list_reviews(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                       runtime: AgentRuntime = Depends(get_runtime)):
    items, total = runtime.reviews.list(limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{review_id}", response_model=ReviewResponse,
            responses={404: {"model": ErrorResponse}})
async def get_review(review_id: str, runtime: AgentRuntime = Depends(get_runtime)):
    review = runtime.reviews.get(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"검토 이력이 없습니다: {review_id}")
    return review


@router.post("/{review_id}/feedback", response_model=FeedbackResponse, status_code=201,
             responses={404: {"model": ErrorResponse}})
async def add_feedback(review_id: str, req: FeedbackRequest, request: Request,
                       runtime: AgentRuntime = Depends(get_runtime)):
    """검토 결과에 대한 사용자 평가. LangSmith 실행 ID가 있으면 그 실행에 피드백으로 남겨
    관리자 화면과 LangSmith에서 품질을 추적한다. LangSmith 기록이 실패해도 로컬에는 저장한다."""
    review = runtime.reviews.get(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"검토 이력이 없습니다: {review_id}")
    run_id = review["metadata"].get("langsmith_run_id")
    ls_id = (await request.app.state.langsmith.create_feedback(run_id, req.score, req.comment)
             if run_id else None)
    return runtime.reviews.add_feedback(review_id, req.score, req.comment, ls_id)


@router.get("/{review_id}/feedback", response_model=list[FeedbackResponse])
async def list_review_feedback(review_id: str, runtime: AgentRuntime = Depends(get_runtime)):
    return runtime.reviews.feedback_for(review_id)
