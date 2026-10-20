# 4M 변경 영향 검토 Agent

완성차 공장(프레스 → 차체 → 도장 → 의장)에서 작업자·설비·재료·공법(4M) 변경 요청이 들어오면,
표준서와 현장 데이터를 조회해 **필요한 검증 항목, 변경 등급, 다음 공정 영향**을 정리하는 검토 보조
Agent 서비스다. 최종 판단과 승인은 품질 담당자가 한다. 데이터는 교육용 가상 데이터다([`data/4m/README.md`](data/4m/README.md)).

Capstone Base(`all_total_vue`)의 골격(싱글턴·MCP·SSE·라우팅·게이트·재계획·검증·재시도·병렬·세션·
주입)을 이어받아 상용 수준 구조로 다시 만들었다. 단계별 변경 내역과 실측 결과는 [`doc/ROADMAP.md`](doc/ROADMAP.md).

## 실행

```bash
bash sh/setup_venv.sh            # 최초 1회 — Python 패키지
bash sh/setup_ollama.sh          # 최초 1회 — qwen2.5:7b(fast), qwen3:8b(quality), bge-m3(임베딩). 있으면 건너뜀
cp .env.example .env            # 선택 — LangSmith 키 입력 시 추적·관리자 기능 (없어도 Agent는 동작)

bash sh/run_agent_ollma.sh       # 백엔드 http://127.0.0.1:8100 (API 문서 /docs)
bash sh/build_frontend.sh        # 화면 빌드 → http://127.0.0.1:8100 에서 화면 + API
```

| 다른 실행 방법 | 명령 |
|---|---|
| 화면 개발 모드 (핫 리로드) | `bash sh/run_frontend.sh` → http://localhost:5173 |
| LLM 없이 (결정론 fake) | `LLM_BACKEND=fake .venv/bin/python3 server.py` |
| OpenAI (과금) | `bash sh/run_agent_openai.sh` |
| Before/After 평가 CLI | `set -a; source .env; set +a; LLM_BACKEND=ollama .venv/bin/python3 eval/run_eval.py` |
| 테스트 | `.venv/bin/python3 -m pytest -q` · `cd frontend && npm test` |

## 구조

```
Vue 3 (frontend/)  ── REST /api/v1 · SSE ──▶  FastAPI (app/)
                                                 │
                                   AgentRuntime (프로세스당 1회 생성)
                                                 │
                     LangGraph Supervisor + 전문 Agent (agent/)
          route → classify → plan → gate → [standards ∥ field] → replan → judge → assess → write → validate
                     │                          │                      │
               LangChain 모델            MCP 서버 (mcp_server.py)    LangSmith 추적·피드백·평가
          (ChatOllama/ChatOpenAI/fake)   Tool·Resource·Prompt
```

| 경로 | 내용 |
|---|---|
| `agent/agents/` | 전문 Agent — 분류, 계획+권위 게이트, 표준서·현장 데이터 조사, 조건 판정, 체크리스트·등급, 작성, 검증 |
| `agent/graph.py` | Supervisor 그래프 (병렬 조사, 재조사, 재작성 루프, 기능 스위치) |
| `agent/llm/` | LangChain 모델 계층 (구조화 출력, 스트리밍, 토큰 집계, fake 모델) |
| `agent/mcp_client.py`, `mcp_server.py` | MCP 클라이언트·서버 (시간 제한, 오류 규약, 입력·출력 스키마) |
| `rag/` | 표준서 조항 RAG — bge-m3 임베딩 + Chroma, 공장·변경 유형 필터 (MCP Tool `search_standards`) |
| `app/` | FastAPI — 설정, 런타임, 라우터(health·chat·reviews·admin), 활동 로그, LangSmith 연동, 평가 |
| `frontend/` | Vue 3 + Vite — 새 검토(실시간 활동 로그), 검토 상세·이력, 피드백, 관리자 |
| `data/4m/` | 규칙표, 표준서 9개(조항 41개), 공정 흐름, 설비·라인 상태 |
| `eval/` | 평가 데이터셋 10건, 채점 함수, 평가 CLI |
| `doc/` | [`ROADMAP.md`](doc/ROADMAP.md)(단계별 결과·실측), [`STREAMING.md`](doc/STREAMING.md)(SSE 이벤트 규격), [진행계획](doc/AI_Mini_Project_진행계획_4M_Agent.md) |

## 주요 API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/v1/reviews/stream` | 4M 검토 — 활동 로그 SSE 스트리밍 후 저장 (화면이 쓰는 방식) |
| POST | `/api/v1/reviews` | 4M 검토 — 끝까지 실행 후 한 번에 응답 |
| GET | `/api/v1/reviews`, `/api/v1/reviews/{id}` | 검토 이력 |
| POST | `/api/v1/reviews/{id}/feedback` | 사용자 평가 → LangSmith |
| GET | `/api/v1/health` | 기동 상태, MCP 서버 연결 |
| — | `/api/v1/admin/*` | LangSmith 상태, 실행 기록, 피드백, Before/After 평가 (`ADMIN_TOKEN` 설정 시 인증) |

## 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `LLM_BACKEND` | `fake` (스크립트는 `ollama`/`openai`) | LLM 백엔드 |
| `OLLAMA_FAST_MODEL` / `OLLAMA_QUALITY_MODEL` | `qwen2.5:7b` / `qwen3:8b` | 역할별 모델 |
| `PIPELINE_PROFILE` | improved | `baseline`이면 개선 기능 전부 끔. 개별: `GATE_4M`, `JUDGE_CONDITIONS`, `FLOW_IMPACT`, `VALIDATOR_4M`, `RETRIEVER=keyword\|rag` |
| `EMBEDDING_BACKEND` / `EMBEDDING_MODEL` | LLM_BACKEND가 fake면 fake, 아니면 ollama / `bge-m3` | RAG 임베딩 |
| `MCP_FLAKY_FIRST_CALL` | `0` | Wave 9 재시도 데모용 강제 타임아웃 |
| `APP_DB_PATH` | `session.db` | 대화·검토·피드백·평가 저장 SQLite |
| `ADMIN_TOKEN` | 없음 | 설정하면 관리자 API에 `X-Admin-Token` 필요 |
| `LANGCHAIN_*` | `.env` | LangSmith 키·프로젝트·추적 |
