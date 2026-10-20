"""REST API 요청/응답 스키마 (Pydantic v2).

OpenAPI 문서(/docs)와 Vue 프론트엔드(Step 3)가 이 스키마를 계약으로 삼는다. Agent 내부
상태(AgentState)를 그대로 노출하지 않고, 클라이언트에 필요한 필드만 골라 담는다.
"""
from typing import Any, Literal

from pydantic import BaseModel, Field

THREAD_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,64}$"


class ErrorBody(BaseModel):
    code: str = Field(description="에러 코드 (예: validation_error, agent_failed, not_found)")
    message: str
    request_id: str | None = None
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = Field(description="MCP 서버 중 하나라도 응답이 없으면 degraded")
    mcp_servers: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="MCP 서버별 이름·버전·연결 상태")
    instance_id: int
    creation_count: int = Field(description="Agent 번들 생성 횟수 — 항상 1이어야 정상 (Wave 1)")
    supervisor_version: str
    llm_backend: str
    fast_llm: str
    quality_llm: str


class RunMetadata(BaseModel):
    route: str | None = None
    task_count: int = 0
    gate_added: int = Field(0, description="권위 게이트가 추가한 필수 조사 task 수")
    gate_removed: int = 0
    replan_rounds: int = 0
    retry_count: int = 0
    validation_attempts: int = 0
    cost_usd: float = 0.0
    tokens: int = 0
    features: dict[str, bool] = Field(default_factory=dict,
                                      description="실행 시 켜져 있던 기능 스위치")
    llm_backend: str
    supervisor_version: str
    instance_id: int | None = None
    langsmith_run_id: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str = Field(default="default", pattern=THREAD_ID_PATTERN)


class ChatResponse(BaseModel):
    reply: str
    events: list[dict[str, Any]]
    metadata: RunMetadata


class ReviewRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000,
                         description="4M 변경 요청 내용",
                         examples=["차체 대시 패널 라인 용접 로봇(BD-RB-301, BD-RB-302)의 "
                                   "용접 전류 조건을 변경합니다."])
    thread_id: str | None = Field(default=None, pattern=THREAD_ID_PATTERN,
                                  description="생략하면 검토마다 새 스레드를 만든다")
    parent_id: str | None = Field(default=None, pattern=r"^rv-[0-9a-f]{12}$",
                                  description="보완 재검토: 원 검토 ID. message는 보완 정보만 적는다")


class DocumentRef(BaseModel):
    doc_id: str
    rev: str
    title: str
    doc_type: Literal["standard", "inspection"]


class FieldFinding(BaseModel):
    kind: Literal["equipment", "production"]
    target: str = Field(description="설비 ID 또는 라인 ID")
    status: str
    abnormal: bool = Field(description="설비 이상 상태이거나 라인이 가동 중(running)이면 true")
    note: str = ""
    failed: bool = Field(False, description="MCP 조회 자체가 실패했는지 (상태를 모름)")


class ChecklistItem(BaseModel):
    id: str = Field(description="검증 항목 ID (예: COM-01, EXT-BD-01, DS-PT-01)")
    name: str
    layer: Literal["required", "document", "field", "downstream"] = Field(
        description="required=규칙표, document=표준서 조건부 조항, field=현장 데이터, "
                    "downstream=다음 공정 영향")
    evidence: dict[str, Any] = Field(description="근거 (문서ID·개정판·조항 / Tool / 공정 흐름 규칙)")


class Grading(BaseModel):
    grade: Literal["A", "B", "C"]
    approver: str
    initial_flow_period: str
    reason: str


class ReviewResponse(BaseModel):
    id: str
    created_at: str
    thread_id: str
    request: str
    parent_id: str | None = Field(default=None, description="보완 재검토면 원 검토 ID")
    supplement: str | None = Field(default=None, description="보완 재검토에서 덧붙인 정보")
    shop: str | None = Field(description="변경이 일어나는 공장 (프레스/차체/도장/의장)")
    change_types: list[str] = Field(description="Man / Machine / Material / Method")
    documents: list[DocumentRef] = Field(description="검토에 사용한 표준서와 검사 기준")
    field_findings: list[FieldFinding] = Field(description="조회한 설비·라인 상태")
    checklist: list[ChecklistItem] = Field(description="검증 항목 체크리스트")
    grading: Grading | None = Field(description="변경 등급, 승인 주체, 초기유동관리 기간")
    review_status: Literal["검토 완료", "추가 확인 필요"] | None
    missing_items: list[str] = Field(description="보고서에 끝내 빠진 검증 항목 ID")
    citation_issues: list[str] = Field(default_factory=list,
                                       description="보고서 근거 인용이 실제 자료와 맞지 않은 내용")
    warnings: list[str] = Field(description="Partial Result 경고 (예: 공정 표준 미확보)")
    reply: str = Field(description="검토 결과 본문")
    events: list[dict[str, Any]]
    metadata: RunMetadata


class ReviewSummary(BaseModel):
    id: str
    created_at: str
    request: str
    shop: str | None
    change_types: list[str]
    grading: Grading | None = None
    review_status: str | None = None


class ReviewListResponse(BaseModel):
    items: list[ReviewSummary]
    total: int
    limit: int
    offset: int


# ── 피드백 ──────────────────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    score: Literal[0, 1] = Field(description="1 = 도움이 됨, 0 = 도움이 안 됨")
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackResponse(BaseModel):
    id: str
    review_id: str
    score: int
    comment: str | None
    langsmith_feedback_id: str | None = Field(
        description="LangSmith에 남긴 피드백 ID (추적이 꺼져 있거나 실패하면 null)")
    created_at: str
    request: str | None = None


# ── 관리자 ──────────────────────────────────────────────────────────────

class LangSmithStatus(BaseModel):
    enabled: bool
    project: str
    reachable: bool
    project_url: str | None
    error: str | None
    admin_auth: bool = Field(description="관리자 토큰 인증이 켜져 있는지 (ADMIN_TOKEN)")


class RunSummary(BaseModel):
    id: str
    name: str
    status: str | None
    start_time: str | None
    latency_s: float | None
    total_tokens: int
    error: str | None
    tags: list[str]
    thread_id: str | None
    feedback: dict[str, dict[str, Any]]
    url: str | None


class RunStep(BaseModel):
    name: str
    status: str | None
    latency_s: float | None
    tokens: int
    llm_calls: int
    tool_calls: int
    error: str | None


class RunDetail(RunSummary):
    steps: list[RunStep]
    inputs_preview: str


class EvaluationRequest(BaseModel):
    profiles: list[Literal["baseline", "improved"]] = Field(
        default_factory=lambda: ["baseline", "improved"], min_length=1)
    limit: int | None = Field(default=None, ge=1, le=10, description="앞에서부터 N건만 (빠른 점검용)")


class EvaluationJob(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    created_at: str
    finished_at: str | None = None
    profiles: list[str]
    case_count: int
    llm_backend: str
    progress: dict[str, int]
    dataset: str
    dataset_sync: str | None = None
    experiments: list[dict[str, Any]]
    error: str | None
