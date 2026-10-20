# 4M 변경 영향 검토 서비스 — 상용 수준 전환 로드맵

우선순위 1(멀티 Agent, REST API, Vue UI)을 먼저 완성하고, 우선순위 2(MCP, Streaming, LangSmith 관리자)를 이어서 진행한다. 단계마다 테스트로 확인한 뒤 다음 단계로 넘어간다.

| 단계 | 우선순위 | 영역 | 목표 | 상태 |
|---|---|---|---|---|
| Step 1 | 1 | FastAPI REST API | `/api/v1` 버전 관리, 요청/응답 스키마, 검토 이력 저장·조회, 단일 에러 규격, 요청 ID, CORS, API 테스트 | ✅ 완료 |
| Step 2 | 1 | LangChain/LangGraph 멀티 Agent | LangChain 채팅 모델 도입, 전문 Agent 분리(분류·표준서 조사·현장 데이터·영향 분석·작성·검증), 4M 게이트·등급·공정 영향 | ✅ 완료 |
| Step 3 | 1 | Vue UI | Vite + Vue 3 프로젝트, 검토 요청·결과(체크리스트, 등급, 근거)·이력 화면 | ✅ 완료 |
| Step 4 | 2 | MCP 서버 | 입력 검증, 에러 응답, Tool·Resource 확장, MCP 단위 테스트 | ✅ 완료 |
| Step 5 | 2 | Streaming | 타입이 정해진 SSE 이벤트 규격, 끊김 처리, Vue 실시간 연동 | ✅ 완료 |
| Step 6 | 2 | LangSmith 관리자 | 관리자 API·화면: 실행 기록, 피드백, 평가 데이터셋 실행 결과 | ✅ 완료 |

## Step 1 결과 — REST API

### 구조

```
server.py                 실행 진입점 (sh 스크립트 호환) → app.main.create_app()
app/
├── main.py               앱 팩토리: lifespan, 요청 ID 미들웨어, CORS, 라우터, 에러 처리
├── config.py             Settings — 환경변수를 한곳에서 읽어 주입
├── runtime.py            AgentRuntime — MCP·LLM·그래프·저장소를 프로세스당 1회 생성
├── schemas.py            요청/응답 스키마 (OpenAPI 계약)
├── review_store.py       검토 이력 저장소 (SQLite)
├── errors.py             단일 에러 응답 규격
├── dependencies.py       get_runtime()
└── routers/
    ├── health.py         GET  /api/v1/health
    ├── chat.py           POST /api/v1/chat, GET /api/v1/chat/stream
    ├── reviews.py        POST /api/v1/reviews, GET /api/v1/reviews, GET /api/v1/reviews/{id}
    ├── legacy.py         /health, /version, /chat, /chat/stream (deprecated, 기존 화면 호환)
    └── _agent.py         Agent 실행 실패 → 502 변환, SSE 프레임
```

### 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/v1/health` | 기동 상태, Agent 번들 정보 |
| POST | `/api/v1/chat` | 대화형 — 라우팅 LLM이 잡담/검토를 고름 |
| GET | `/api/v1/chat/stream` | 대화형 SSE 스트리밍 |
| POST | `/api/v1/reviews` | 4M 검토 실행(항상 검토 경로) + 이력 저장 → 201 |
| GET | `/api/v1/reviews` | 검토 이력 목록 (`limit`, `offset`, 최신순) |
| GET | `/api/v1/reviews/{id}` | 검토 상세 |

OpenAPI 문서: `http://127.0.0.1:8100/docs`

### 에러 규격

```json
{"error": {"code": "validation_error", "message": "...", "request_id": "...", "details": [...]}}
```

| 상태 | code | 상황 |
|---|---|---|
| 422 | `validation_error` | 요청 스키마 위반 (빈 메시지, 2000자 초과, 잘못된 thread_id) |
| 404 | `not_found` | 없는 검토 ID |
| 502 | `agent_failed` | MCP·LLM 등 외부 의존성 실패 |
| 500 | `internal_error` | 그 밖의 오류 |

스트리밍 중 실패하면 `{"type": "Error", "code": ...}` 이벤트 후 `[DONE]`으로 정상 종료한다.

### 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `LLM_BACKEND` | `fake` | `fake` / `ollama` / `openai` |
| `SUPERVISOR_VERSION` | `v2` | `v1`(legacy) / `v2` |
| `MCP_FLAKY_FIRST_CALL` | `0` | Wave 9 데모용 강제 타임아웃. 재시도 데모 때만 `1` |
| `APP_DB_PATH` | `session.db` | 세션·검토 이력 SQLite 파일 |
| `CORS_ORIGINS` | Vite(5173), web_demo(8600) | 쉼표로 구분 |

### 테스트

```bash
.venv/bin/python3 -m pytest -q      # API 17개 + 데이터 정합성 10개
```

## Step 2 결과 — LangChain/LangGraph 멀티 Agent

### 그래프

```
route ─┬─ chat_answer                                     Chat Agent (잡담, 세션 기억)
       └─ classify → plan → gate ─┬─ standards ─┐          Classifier → Planner → 권위 게이트
                                  └─ field ─────┴─ replan_check ─┬─ standards_gap (재조사)
                                                                 └─ judge → assess → write
                                                                    → validate ─┬─ write (재작성)
                                                                                └─ finalize
```

| Agent | 모델 | 역할 | 파일 |
|---|---|---|---|
| Router | fast LLM | 잡담/검토 분기 | `agent/agents/router.py` |
| Chat | fast LLM | 잡담 응답 (세션 기억) | `agent/agents/chat.py` |
| Classifier | fast LLM | 공장, 변경 유형, 설비·라인 식별 + 코드 보정 | `agent/agents/classifier.py` |
| Planner + 권위 게이트 | fast LLM + 코드 | 조사 계획 제안 → 빠진 필수 조사를 코드가 추가 | `agent/agents/planner.py` |
| Standards / Field Data | MCP | 표준서(Resource)와 설비·라인(Tool)을 **병렬** 조회 | `agent/agents/research.py` |
| Judge | fast LLM + 안전망 | 조건부 조항·공정 간 영향의 해당 여부 판정. 안전 체결부는 코드가 강제 포함 | `agent/agents/judge.py` |
| Assessor | 코드 | 체크리스트(필수·문서·현장·다음 공정), 변경 등급, 초기유동관리 | `agent/agents/assessor.py` |
| Writer | quality LLM | 검토 보고 작성 (토큰 스트리밍) | `agent/agents/writer.py` |
| Validator | 코드 | 항목 누락 탐지, 검토 상태("검토 완료"/"추가 확인 필요") | `agent/agents/validator.py` |

- LLM은 모두 LangChain `BaseChatModel`(`ChatOllama`, `ChatOpenAI`)이다. 구조화 출력은 `with_structured_output`을 쓰고, 실패하면 각 Agent가 키워드 규칙으로 fallback한다(`FallbackUsed` 이벤트).
- fake 백엔드도 `BaseChatModel`을 구현한 규칙 기반 모델(`agent/llm/fake_chat.py`)이라 실모델과 같은 경로로 테스트한다.
- 3회 재작성 후에도 항목이 빠지면 강제로 통과시키지 않고 "추가 확인 필요" + 보고서 맨 위 경고로 내보낸다.

### 기능 스위치 (Baseline ↔ Improved)

| 환경변수 | 기본 | 끄면 |
|---|---|---|
| `GATE_4M` | on | 규칙표 필수 항목과 필수 조사 task를 강제하지 않음 |
| `JUDGE_CONDITIONS` | on | 조건 판정 없이 문서에 적힌 항목 ID를 전부 나열 |
| `FLOW_IMPACT` | on | 다음 공정 영향을 보지 않음 |
| `VALIDATOR_4M` | on | 길이·번호만 보는 범용 검증, 3회 후 통과 처리 |

`PIPELINE_PROFILE=baseline`이면 전부 끈다.

### 기능별 기여도 (fake 백엔드, 평가 10건)

| 구성 | Recall | Precision | F1 |
|---|---|---|---|
| Baseline | 0.25 | 0.47 | 0.32 |
| + 권위 게이트만 | 0.95 | 0.75 | 0.83 |
| + 조건 판정만 | 0.10 | 1.00 | 0.17 |
| + 공정 영향만 | 0.30 | 0.50 | 0.37 |
| Improved (전부) | 1.00 | 1.00 | 1.00 |

fake의 판단은 키워드 규칙이라 이 수치는 **배선 검증용**이다. 실모델 성능은 Step 6에서 LangSmith 평가로 측정한다.

### 실모델 확인 (Ollama: fast `qwen2.5:7b`, quality `qwen3:8b`)

| 케이스 | 결과 | 비고 |
|---|---|---|
| case-08 용접 전류 변경 | F1 1.0, B등급, 59초 | fallback 없음 |
| case-06 브레이크 브래킷 | 처음 F1 0.86, **B등급(오답)** → 안전망 추가 후 F1 1.0, A등급 | 판정 Agent가 안전 항목을 놓침 → 안전 체결부는 코드가 강제 포함하도록 보완 |

### 테스트

```bash
.venv/bin/python3 -m pytest -q    # 44개: API 17 + 데이터 정합성 10 + 파이프라인 15 + Agent 단위 2
```

## Step 3 결과 — Vue UI

### 실행

```bash
bash sh/setup_venv.sh                 # 최초 1회: Python 패키지
bash sh/setup_ollama.sh               # 최초 1회: qwen2.5:7b(fast), qwen3:8b(quality) — 있으면 건너뜀
bash sh/run_agent_ollma.sh            # 백엔드 (8100). .env가 없으면 LangSmith 없이 실행
bash sh/build_frontend.sh             # 화면 빌드 → http://127.0.0.1:8100 에서 화면 + API
# 또는 개발 모드: bash sh/run_frontend.sh → http://localhost:5173 (핫 리로드, /api는 8100으로 프록시)
```

### 구조

```
frontend/
├── src/api/          types.ts(백엔드 스키마와 1:1), client.ts(에러 규격 → ApiError)
├── src/lib/          format.ts(체크리스트 층 묶기, 근거 표기, 상태 한글화, 보고서 렌더)
├── src/components/   ReviewResult, GradeBadge, StatusPill, ErrorBanner
├── src/views/        ReviewNew(요청), ReviewDetail(결과), ReviewHistory(이력)
└── *.test.ts         vitest 9개 (포맷, API 클라이언트, 결과 화면)
```

- 해시 라우팅(`#/reviews/rv-...`) — FastAPI 정적 서빙에서 깊은 링크를 새로고침해도 404가 나지 않는다
- 라이트/다크 모드 토큰, 좁은 화면에서는 2단 카드가 1단으로 바뀐다
- 보고서는 HTML을 이스케이프한 뒤 `**굵게**`만 변환해 표시한다 (XSS 방지)

### 실모델 측정 (평가 10건, fast `qwen2.5:7b` / quality `qwen3:8b`, 화면과 같은 API 경로)

| 지표 | 값 |
|---|---|
| Recall / Precision / F1 | 0.92 / 0.97 / 0.94 |
| 변경 등급 정확도 | 10/10 (안전 체결부 A등급 2건 포함) |
| 분류 정확도 (공장 + 유형) | 8/10 |
| 평균 지연 / 토큰 | 34초 / 2,500 |

알려진 약점: 판정 Agent가 일부 조건부 항목(EXT-PR-01, EXT-BD-01)과 다음 공정 영향(DS-*)을 놓친다. 공장명이 없는 요청(루프 강판)을 차체로 분류한다. 설비 교체+토크 변경을 Material+Method로 분류한다. → Step 6 LangSmith 평가에서 개선 전후를 비교한다.

`qwen3:0.6b`를 fast 모델로 쓰면 공장 오분류(“의장 공장 기준” → 프레스)가 실측돼 기본값을 `qwen2.5:7b`로 바꿨다. 분류 Agent는 원문에 적힌 공장명·설비·라인을 LLM 답보다 우선한다.

## 활동 로그 (Step 5 일부를 앞당겨 구현)

검토에 30~40초가 걸리는 동안 "지금 어떤 Agent가 무엇을 하는지"를 보여 준다.

- `POST /api/v1/reviews/stream` — SSE. GET + EventSource 대신 POST + fetch 스트림을 쓴다 (EventSource는 끊기면 자동 재연결해 같은 검토를 다시 실행한다)
- 이벤트: `NodeStarted`(Agent 시작 문장) → Agent 결과 이벤트(세부 문장) → `NodeFinished`(소요 시간) · `AnswerToken`(보고서 토큰) · `FinalAnswer` · `ReviewSaved`(id) · `[DONE]`
- 노드 시작·종료는 LangGraph `tasks` 스트림 모드에서 받는다. 문장은 서버(`app/activity.py`)에서 만들어 모든 클라이언트가 같은 로그를 본다
- 화면: 진행 중 단계는 스피너, 끝난 단계는 ✓와 소요 시간, 검수 반려·fallback은 경고색. 보고서는 작성되는 동안 토큰 단위로 미리 보인다. 저장된 검토의 상세 화면에서도 "처리 과정"을 다시 볼 수 있다

실측 (Ollama, 용접 전류 변경 1건, 43.5초): 분류 5.0초 → 계획 7.5초 → 게이트(필수 조사 3건 추가) → 표준서·설비 병렬 조회 0.3초 → 판정 1.3초 → 보고서 작성 29.4초(토큰 551개 실시간 수신) → 검수 통과 → 저장.

## Step 4 결과 — MCP 서버·클라이언트 보강

### 서버 (`mcp_server.py`, v1.1.0)

| 항목 | 내용 |
|---|---|
| 입력 검증 | 설비·라인 ID 형식(`^[A-Z]{2}-[A-Z0-9]+(-[A-Z0-9]+)*$`, 32자 이하)을 입력 스키마로 강제 |
| 출력 스키마 | `EquipmentStatus`, `ProductionStatus` (Pydantic) — 클라이언트는 `structured_content`로 받는다 |
| 도구 표시 | `readOnlyHint`, `idempotentHint` — 조회 전용임을 MCP 클라이언트에 알린다 |
| 오류 규약 | 형식 위반 → 검증 오류 / 대상 없음 → `found=false` 정상 응답 / 데이터 소스 장애 → `ToolError`·`ResourceError`(원인 메시지) / 예상 못 한 오류 → `mask_error_details`로 상세 숨김 |
| 서버 정보 | 이름·버전·instructions를 initialize 응답으로 공개 |

### 클라이언트 (`agent/mcp_client.py`)

| 항목 | 내용 |
|---|---|
| 시간 제한 | 요청 15초(초과 시 `TimeoutError` → `with_retry` 재시도), 기동 30초 — 둘을 분리 |
| 오류 변환 | 도구 `is_error` → `MCPToolError` |
| 직렬화 잠금 제거 | 전역 잠금이 병렬 조회를 순차로 만들고 있었다 → 제거 (설비·라인 조회 약 300ms → 84ms) |
| 기동 실패 정리 | 서버 하나라도 기동 실패하면 이미 띄운 subprocess를 정리하고 오류를 올린다 (정리하지 않으면 프로세스 종료가 멈추는 결함을 테스트로 발견) |
| ping | `/api/v1/health`에 서버별 연결 상태 → 하나라도 실패면 `degraded` |
| 데모 장치 | Wave 9 강제 타임아웃은 기본 꺼짐 (`MCP_FLAKY_FIRST_CALL=1`일 때만) |

### 장애 격리 (Agent)

문서 하나·설비 하나의 MCP 조회가 실패해도 검토 전체를 실패시키지 않는다. 그 항목만 "조회 실패"로 기록하고 경고를 남겨 최종 상태를 **"추가 확인 필요"**로 만든다. 상태를 모르는 설비로 현장 데이터 항목(EXT-EQ-01)을 판정하지 않는다. LLM 장애는 그대로 502(`agent_failed`)로 응답한다.

### 테스트

```bash
.venv/bin/python3 -m pytest -q     # 70개
#   MCP 서버 16 (메모리 내 클라이언트: 스키마, 검증, 오류 규약, Resource, Prompt)
#   MCP 클라이언트 6 (실제 stdio: 오류 변환, 시간 제한+재시도, 병렬성, ping, 기동 실패 정리)
#   API 23 (장애 격리, LLM 장애 502, 헬스 MCP 상태 포함) · 파이프라인 17 · 데이터 정합성 10
```

## Step 5 결과 — Streaming 마무리

이벤트 규격은 `doc/STREAMING.md`에 정리했다.

| 항목 | 내용 |
|---|---|
| keep-alive | 이벤트가 15초 동안 없으면 `: keep-alive` SSE 주석 — 프록시의 유휴 연결 종료 방지 |
| 연결 끊김 | 클라이언트가 끊으면 그래프 실행을 취소하고 미완성 검토를 저장하지 않는다. 실서버 확인: Writer 시작 시점에 끊음 → `client_disconnected` 로그, 이력 수 변화 없음 |
| 순번 | 모든 이벤트에 `seq` |
| 구조 | 생산자 작업 1개가 그래프를 끝까지 실행하고 큐로 전달 — LangGraph·LangSmith의 contextvars 실행 맥락을 유지 |

## Step 6 결과 — LangSmith 관리자 기능

### 추적 구조

- 루트 실행 ID를 서버가 정해 그래프에 넘긴다 (`app/runtime.py` `_trace_config`) — 일반·스트리밍 검토 모두 검토 이력과 LangSmith 실행이 1:1로 연결된다
- 이름 `4m_review`, 태그 `4m-agent`·`backend:*`·`profile:*`, 메타데이터 thread_id·기능 스위치
- LangGraph가 노드를, LangChain이 LLM을, MCP 클라이언트가 Tool·Resource 호출을 계층 기록한다 (노드 @traceable 중복 제거)
- 프로젝트: `capstone-4m-ollama` / `capstone-4m-openai` (실행 스크립트가 백엔드별로 지정). 테스트는 추적을 끈다 (`tests/conftest.py`)

### API

| 메서드 | 경로 | 내용 |
|---|---|---|
| POST | `/api/v1/reviews/{id}/feedback` | 사용자 평가(👍/👎 + 의견) — 로컬 저장 + LangSmith 실행에 `user_rating` 피드백 |
| GET | `/api/v1/admin/langsmith` | 추적 상태, 프로젝트 링크, 관리자 인증 여부 |
| GET | `/api/v1/admin/runs` | 최근 루트 실행 — 상태, 소요, 토큰, 사용자 평가 통계, LangSmith 링크 |
| GET | `/api/v1/admin/runs/{id}` | Agent(노드)별 소요 시간·LLM 호출·MCP 호출·토큰 |
| GET | `/api/v1/admin/feedback` | 사용자 피드백 목록 |
| POST / GET | `/api/v1/admin/evaluations` | Before/After 평가 실행(백그라운드, 202) / 진행률·결과 |

`ADMIN_TOKEN`을 설정하면 `/api/v1/admin/*`에 `X-Admin-Token` 헤더가 필요하다 (설정하지 않으면 개발 모드로 열려 있고 화면에 표시된다). LangSmith가 꺼져 있거나 닿지 않으면 Agent 서비스는 그대로 동작하고, 관리자 조회만 503으로 알린다.

### 평가 (`app/evaluation.py`, CLI `eval/run_eval.py`)

- `eval/4m_dataset.jsonl` 10건 → LangSmith Dataset `4m-review-eval` (내용이 바뀌면 다시 올림)
- 구성마다 `aevaluate` 실험 1개: `baseline`(기능 스위치 전부 끔) / `improved`(전부 켬). 서버 설정은 바꾸지 않고 스위치만 다른 그래프를 따로 만든다
- 평가자: recall · precision · f1 · 층별 recall(필수/조건부/현장/다음 공정) · 등급 정확도 · 분류 정확도. 지연·토큰은 출력에서 집계
- 관리자 화면에서 시작·진행률·Before/After 비교표·실험 링크를 본다

```bash
set -a; source .env; set +a
LLM_BACKEND=ollama .venv/bin/python3 eval/run_eval.py          # 전체 10건 × 2구성
LLM_BACKEND=fake   .venv/bin/python3 eval/run_eval.py --limit 3
```

### 화면

- 관리자(`#/admin`): LangSmith 상태·프로젝트 링크, Before/After 평가(시작, 진행률, 비교표, 변화량 색 표시, 실험 링크), 최근 실행(사용자 평가 통계, 단계별 상세 — Agent별 소요 시간 막대), 사용자 피드백
- 검토 상세: 👍/👎 + 의견 → LangSmith 기록 여부 표시

### 테스트

```bash
.venv/bin/python3 -m pytest -q        # 백엔드 84개
cd frontend && npm test               # 프론트 19개
```

### 실측 Before/After (Ollama fast `qwen2.5:7b` / quality `qwen3:8b`, 평가 10건, LangSmith 실험 `4m-baseline-*` · `4m-improved-*`)

| 지표 | Baseline | Improved | 변화 |
|---|---|---|---|
| F1 | 0.32 | **0.94** | +0.62 |
| Recall / Precision | 0.25 / 0.47 | 0.92 / 0.97 | +0.67 / +0.51 |
| Recall · 필수 항목 | 0.16 | 0.99 | +0.82 (권위 게이트) |
| Recall · 조건부 항목 | 1.00 | 0.67 | −0.33 |
| Recall · 현장 데이터 | 1.00 | 1.00 | ±0 |
| Recall · 다음 공정 | 0.00 | 0.00 | ±0 |
| 변경 등급 정확도 | 0.90 | 1.00 | +0.10 |
| 분류 정확도 | 0.80 | 0.80 | ±0 |
| 평균 지연 / 토큰 | 24.2초 / 1,867 | 29.4초 / 2,434 | +5.1초 / +567 (판정 Agent 호출 비용) |

해석 (발표의 "한계와 트레이드오프"):
- 조건부 항목 Recall이 떨어진 것은 Baseline이 문서의 항목 ID를 **조건 없이 전부** 나열하기 때문이다 (그 대가로 Precision 0.47). Improved는 Judge Agent가 조건을 따지면서 일부(EXT-PR-01 외판, EXT-BD-01 용접 설비 교체)를 놓친다 — Precision을 얻고 Recall을 잃는 트레이드오프
- 다음 공정 영향은 두 구성 모두 0 — Judge(qwen2.5:7b)가 공정 흐름 규칙을 해당으로 판정하지 못한다. 다음 개선 대상: 공정 흐름 규칙에 판단 기준을 구조화하거나 판정 모델 상향
- 분류 오류 2건(공장명 없는 강판 요청, 설비 교체+토크 변경을 Material+Method로)은 두 구성 공통
- 개선 비용: 건당 +5.1초, +567토큰

## RAG (진행계획 4번)

### 구현

| 항목 | 내용 |
|---|---|
| 인덱스 | `rag/index.py` — 표준서 조항 41개를 조항 단위로 임베딩(Ollama `bge-m3`, 1024차원)해 Chroma에 저장, `.cache/rag`에 영속 |
| 검색 | MCP Tool `search_standards` (서버 v1.2.0) — 공장 AND 변경 유형 메타데이터 필터, 상위 4개 |
| 공통 규정 | QS-CM-001은 검색 대상에서 빼고 항상 전체를 읽는다 (등급·현장 데이터 규칙의 근거) |
| 부족 시 | 검색 결과에 해당 공장 공정 표준이 없으면 재조사가 원문 전체를 읽는다 |
| 재인덱싱 | 본문·메타데이터·임베딩 모델 해시가 바뀌면 다시 만든다 (개정판만 바뀌어도 감지) |
| 스위치 | `RETRIEVER=keyword\|rag` — Baseline은 키워드, Improved는 RAG |

검색 품질 (평가 10건, 조건부 항목 근거 조항이 상위 k개 안에 드는지):

| 임베딩 | k=4 | k=6 |
|---|---|---|
| bge-m3 (공통 규정 포함 검색) | 6/8 | 8/8 |
| bge-m3 (공통 규정 제외) | **8/8** | 8/8 |
| fake 2-gram (공통 규정 제외) | 8/8 | 8/8 |

### 실측 Before/After (RAG 포함, Ollama, 평가 10건, 실험 `4m-baseline-a165302f` · `4m-improved-22f8c8c1`)

| 지표 | Baseline | Improved (RAG 없음, 이전 측정) | Improved (RAG 포함) |
|---|---|---|---|
| F1 | 0.32 | 0.94 | **0.94** |
| Recall / Precision | 0.25 / 0.47 | 0.92 / 0.97 | 0.92 / 0.97 |
| Recall · 조건부 항목 | 1.00 | 0.67 | 0.67 |
| Recall · 다음 공정 | 0.00 | 0.00 | 0.00 |
| 변경 등급 정확도 | 0.90 | 1.00 | 1.00 |
| 관련 문서 검색 Recall | 0.90 | — | 0.90 |
| 평균 지연 / 토큰 | 23.9초 / 1,867 | 29.4초 / 2,434 | 29.8초 / 2,413 |

해석:
- **검색은 정확하다.** 근거 조항 8/8을 상위 4개 안에 찾는다. 공장 문서 전체 대신 관련 조항 4개만 판정·작성 단계로 넘긴다
- **정확도는 RAG 전후가 같다.** 남은 오답(조건부 항목 3건, 다음 공정 3건)은 검색이 아니라 **판정 Agent**가 검색해 온 조항을 "해당 없음"으로 판단한 결과다 — 다음 개선 대상은 판정 단계
- **문서 규모가 작아 효과가 작다.** 표준서 9개·조항 41개는 공장 문서를 통째로 읽어도 컨텍스트에 들어간다 (계획서 트레이드오프에 예상한 그대로). RAG의 효과는 표준서가 수백 페이지로 늘어날 때 커진다 — 지금은 그 구조를 갖추고 검색 품질을 검증한 단계
- **분류 오류를 키운다.** case-05(공장명 없는 강판 요청)는 공장을 차체로 잘못 분류해, 공장 필터가 정답 문서(프레스)를 검색에서 아예 제외했다 (검색 Recall 0). 키워드 방식도 같은 공장 문서를 읽어 결과는 같지만, 필터가 강할수록 분류 오류의 영향이 커진다

## 판정 Agent 개선

### 판정 단독 실험 (정답 분류 + RAG 후보, qwen2.5:7b, 평가 10건의 조건부·공정 영향 후보 11개)

전체 평가(15분)를 매번 돌리지 않도록 판정 단계만 떼어 실험했다.

| 방식 | 놓침 | 과잉 | Recall | Precision |
|---|---|---|---|---|
| V0 기존 — 해당하는 ID 목록만 받기 | 6 | 1 | 0.45 | 0.83 |
| **V1 — 후보마다 해당 여부·이유를 빠짐없이 답하기** | 2 | 0 | **0.82** | **1.00** |
| V2 — 후보 하나당 LLM 1회 호출 | (측정 중단) | | | |

V1 채택: LLM 호출은 기존과 같은 1회. V1이 놓친 2건(브레이크 안전 항목)은 안전망이 강제 포함한다.
목록만 고르게 하면 소형 모델이 후보를 건너뛰고, 후보마다 답하게 하면 하나씩 검토한다.
답이 빠진 후보는 포함한다(보수적). 판정 이유는 활동 로그와 LangSmith 이벤트에 남는다.

### 발견한 결함: LLM 호출에 제한이 없었다

V2 실험이 한 호출에서 10분 넘게 멈췄다(같은 호출을 재현했을 때는 5초에 끝나 원인은 확정하지 못함).
원인과 무관하게 서비스가 무한정 멈추면 안 되므로 모든 모델에 최대 생성 길이와 시간 제한을 걸었다.

| 역할 | 최대 생성 | 시간 제한 | 초과 시 |
|---|---|---|---|
| fast (분류·계획·판정) | 1,024토큰 | 60초 | 구조화 출력 실패로 보고 규칙 fallback — 검토 계속 |
| quality (보고서) | 3,072토큰 | 240초 | 502 `agent_failed` |

### 실측 (Ollama, Improved 10건, 실험 `4m-improved-2924dcda`)

| 지표 | 판정 개선 전 (RAG 포함) | 판정 개선 후 |
|---|---|---|
| F1 | 0.943 | **0.958** |
| Recall / Precision | 0.921 / 0.973 | 0.940 / 0.982 |
| Recall · 다음 공정 | 0.00 | **0.67** |
| Recall · 조건부 항목 | 0.67 | 0.67 |
| 변경 등급 정확도 | 1.00 | 1.00 |
| 평균 지연 / 토큰 | 29.8초 / 2,413 | 36.4초 / 2,659 |

해석:
- 다음 공정 영향을 처음으로 찾기 시작했다 (0 → 0.67). 남은 1건(case-05)은 공장 오분류로 공정 흐름 후보 자체가 만들어지지 않은 경우다
- 조건부 항목은 놓친 사례가 바뀌었을 뿐 Recall은 같다 (case-04 외판은 찾고, case-03 용접 설비 교체·case-07 오븐 조건은 놓침). 판정 단독 실험(0.82)보다 낮은 것은 실제 파이프라인에서는 분류·검색 결과가 실험과 조금씩 달라지고, 실모델 판정에 변동이 있기 때문이다
- 비용: 후보마다 이유를 쓰게 해 건당 +6.6초, +246토큰

## 검토 범위 확인 (관련 없는 입력 거르기)

**결함**: 검토 엔드포인트는 진짜 요청이 잡담으로 오분류되지 않도록 라우터를 건너뛰고 항상 검토했다.
그 결과 "오늘 점심 뭐 먹지?"에도 검토 보고서를 만들어 이력에 저장했다 (사용자 테스트에서 발견).

**수정**: 검토 시작 전 범위 확인
1. 원문에 **강한 근거**(변경 대상 단어 — 금형·용접·강판·토크·작업자 등, 설비·라인 ID)가 있으면 LLM 없이 검토
2. 없으면 라우터 LLM이 판단 — 검토 요청이 아니면 검토하지 않음 (`out_of_scope`)
   · '공장', '라인', 공장명 같은 약한 단어만으로는 통과시키지 않는다 ("오늘 공장 식당 메뉴가 뭐예요?"가 통과하던 문제)
3. 범위 밖이면 보고서를 만들지 않고 이력에도 남기지 않는다 — API 422 `not_a_change_request`, 스트림 `OutOfScope` 이벤트, 화면은 안내와 예시 표시

실측 (Ollama): 관련 없는 입력 3건 모두 걸러짐, 도메인 단어가 없는 진짜 요청 2건("도어 가니쉬 납품처 변경", "클리어 코트 업체 변경")은 라우터가 살림. 평가 10건은 모두 강한 근거로 LLM 추가 호출 없이 진행 — 정확도·비용 영향 없음.
