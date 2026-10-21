# 4M 변경 영향 검토 Agent

> **결과 보고서**: [doc/REPORT.md](doc/REPORT.md)

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
| Before/After 평가 CLI | `set -a; source .env; set +a; LLM_BACKEND=ollama .venv/bin/python3 eval/run_eval.py` (아래 [평가](#평가)) |
| 테스트 | `.venv/bin/python3 -m pytest -q` · `cd frontend && npm test` · `cd frontend && npm run e2e` |
| 부하 테스트 | `LLM_BACKEND=fake MAX_CONCURRENT_REVIEWS=4 .venv/bin/python3 server.py` 후 `.venv/bin/python3 eval/load_test.py` |

## 평가

Baseline(개선 기능 전부 끔)과 Improved(전부 켬)를 같은 입력으로 실행해 검증 항목의 Recall·Precision·F1,
등급·분류 정확도를 비교한다. 결과는 LangSmith 실험과 `eval/results/*.json`에 남는다.

```bash
set -a; source .env; set +a
LLM_BACKEND=ollama .venv/bin/python3 eval/run_eval.py --runs 3                     # 개발 데이터 10건 × 3회
LLM_BACKEND=openai .venv/bin/python3 eval/run_eval.py --runs 3
LLM_BACKEND=openai .venv/bin/python3 eval/run_eval.py --dataset holdout --runs 3   # 홀드아웃 10건
LLM_BACKEND=ollama .venv/bin/python3 eval/run_eval.py --judge                      # + LLM-as-a-Judge (판사 gpt-4o)
.venv/bin/python3 eval/judge_check.py eval/results/judge-ollama-<시각>.json         # 판사 민감도 점검
LLM_BACKEND=fake   .venv/bin/python3 eval/run_eval.py --limit 3                    # LLM 없이 빠른 점검
```

| 데이터 | 백엔드 | Baseline F1 | Improved F1 | 분류 정확도 | 등급 정확도 | 결과 파일 |
|---|---|---|---|---|---|---|
| 개발 10건 × 3회 | Ollama (qwen2.5:7b · qwen3:8b) | 0.268 | **1.000** ± 0 | 1.00 | 1.00 | `ollama-20261021-0950.json` |
| 개발 10건 × 3회 | OpenAI (gpt-4o-mini · gpt-4o) | 0.283 | **0.997** ± 0.002 | 1.00 | 1.00 | `openai-20261021-0916.json` |
| 홀드아웃 10건 × 1회 | Ollama | 0.261 | **0.917** | 0.70 | 0.90 | LangSmith `4m-improved-2c096b7a` |
| 홀드아웃 10건 × 3회 | OpenAI | 0.269 | **0.981** | 0.80 | 0.90 | `holdout-openai-20261021-1134.json` |

- 개발 데이터(`eval/4m_dataset.jsonl`)는 결과를 보며 분류 키워드와 판정 방식을 고쳤기 때문에 점수가 높게 나오기 쉽다.
- 홀드아웃(`eval/4m_holdout.jsonl`)은 개발 중 쓰지 않은 표현 10건이다. 정답은 표준서·규칙표·현장 데이터만으로 정해
  실행 전에 커밋으로 고정했고(`3aed1ad`), 결과를 본 뒤 시스템 코드는 고치지 않았다.
- 홀드아웃에서 가장 큰 약점은 분류(차체 실러를 도장으로, 너트러너 교체의 Machine 누락)이며, 틀린 사례도 "검토 완료"로
  나갔다. 확신 있는 오답을 "추가 확인 필요"로 돌리는 것이 다음 과제다.
- **LLM-as-a-Judge** (`eval/llm_judge.py`): 검토와 다른 모델(gpt-4o)이 보고서의 근거 충실도와 실무 유용성을 1~5점으로
  채점한다. Ollama 개발 데이터에서 Baseline 0.70 / 0.75 → Improved 0.90 / 0.93 (`judge-ollama-20261021-1640.json`).
  판사 검증: 지어낸 조항을 넣으면 0.90 → 0.25로 떨어지고 넣은 문장을 10건 모두 지목했다. 반면 판사가 정답 A등급(브레이크
  안전 체결부)을 틀렸다고 본 오판도 1건 있어, 판사 점수는 규칙 채점을 보완하는 용도로만 쓴다.
- 대가: 지연 Ollama 24.6 → 41.6초, OpenAI 4.3 → 9.0초, 토큰 약 1.5배. 자세한 내역은 [`doc/ROADMAP.md`](doc/ROADMAP.md).

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
| `eval/` | 평가 데이터셋(개발 10건, 홀드아웃 10건)과 생성 스크립트, 채점 함수, LLM-as-a-Judge, 평가 CLI, 부하 테스트, 결과(`results/`) |
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
