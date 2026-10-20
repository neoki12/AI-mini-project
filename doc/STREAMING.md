# 스트리밍 이벤트 규격 (SSE)

검토 진행 과정을 실시간으로 내려보내는 규격이다. 서버 구현은 `app/routers/_agent.py`의
`sse_stream`, 활동 문장은 `app/activity.py`, 프론트 클라이언트는 `frontend/src/api/stream.ts`.

## 엔드포인트

| 메서드 | 경로 | 용도 |
|---|---|---|
| POST | `/api/v1/reviews/stream` | 4M 검토 (항상 검토 경로). 끝나면 이력에 저장하고 `ReviewSaved`를 보낸다 |
| GET | `/api/v1/chat/stream?message=&thread_id=` | 대화형 (라우팅 LLM이 잡담/검토를 고른다). 저장하지 않는다 |

검토 스트림은 GET + `EventSource`가 아니라 POST + `fetch` 스트림으로 읽는다. `EventSource`는
연결이 끊기면 자동으로 재연결해 **같은 검토를 다시 실행**하기 때문이다.

## 프레임

```
data: {"type": "NodeStarted", "node": "classify", "agent": "Classifier", "message": "...", "seq": 4, "ts": 1771045200123}

: keep-alive

data: [DONE]

```

- 모든 이벤트는 `data: {JSON}` 한 줄 + 빈 줄
- `: keep-alive` — 이벤트가 15초 동안 없을 때 보내는 SSE 주석. 클라이언트는 무시한다 (프록시의 유휴 연결 종료 방지)
- `data: [DONE]` — 스트림의 마지막 프레임. 오류가 나도 항상 보낸다

## 공통 필드

| 필드 | 설명 |
|---|---|
| `type` | 이벤트 종류 |
| `seq` | 1부터 증가하는 순번 |
| `ts` | 서버 시각 (epoch ms) — `ReviewSaved`에는 없다 |
| `node` | 이벤트를 낸 그래프 노드 |
| `agent` | 노드의 Agent 이름 (Classifier, Judge, ...) |
| `message` | 사용자에게 보여 줄 한국어 문장 (`AnswerToken`, `FinalAnswer`, `NodeFinished`에는 없다) |

## 이벤트 종류

| type | 언제 | 주요 필드 |
|---|---|---|
| `NodeStarted` | Agent(노드)가 시작할 때 | `node`, `agent`, `message`(지금 하는 일) |
| `NodeFinished` | Agent가 끝날 때 | `node`, `elapsed_ms`, `error` |
| `RouteDecided` | 라우팅 결정 | `route`(chat/review), `forced` |
| `Classified` | 분류 완료 | `shop`, `change_types`, `equipment_ids`, `lines` |
| `PlanCreated` | 조사 계획 | `task_count`, `targets` |
| `GateApplied` | 권위 게이트 | `added`(추가한 필수 조사), `removed` |
| `TaskCompleted` | 문서·설비·라인 조회 1건 | `source`, `target`, `found`, `failed`, `retries`, (`doc_id`, `rev`, `title` 또는 `summary`) |
| `ReplanCheck` | 조사 충분성 점검 | `is_sufficient`, `target`(재조사 대상) |
| `ConditionsJudged` | 조건 판정 | `candidates`, `applicable_items`, `applicable_flows`, `safety_forced` |
| `ImpactAssessed` | 체크리스트·등급 | `item_count`, `grade`, `layers` |
| `AnswerToken` | 보고서·답변 토큰 | `delta`, `attempt`(재작성 회차) |
| `DraftWritten` | 초안 완성 | `attempt`, `length` |
| `Validation` | 검수 | `verdict`, `missing` |
| `FallbackUsed` | LLM 응답 해석 실패 → 규칙 대체 | `agent`, `reason` |
| `Finalize` | 마무리 | `pipeline`, `review_status` |
| `FinalAnswer` | 최종 본문 | `reply`, `prompt` |
| `ReviewSaved` | 검토 저장 (검토 스트림만) | `id`, `review_status` |
| `OutOfScope` | 4M 변경 요청이 아니라 검토하지 않음 (검토 스트림만, 저장 안 함) | `code`(not_a_change_request), `message` |
| `Error` | 실행 실패 | `code`(agent_failed / internal_error), `message`, `request_id` |

## 순서 보장

- 한 노드의 `NodeStarted`는 그 노드의 결과 이벤트·`NodeFinished`보다 먼저 온다
- `standards`와 `field`는 병렬로 실행되므로 두 노드의 이벤트는 서로 섞여 올 수 있다
- `FinalAnswer` → `ReviewSaved` → `[DONE]` 순서로 끝난다. 범위 밖 요청은 `FinalAnswer` → `OutOfScope` → `[DONE]`, 실패하면 `Error` → `[DONE]`

## 연결 끊김

클라이언트가 연결을 끊으면(창 닫기, 중단 버튼) 서버는 그래프 실행을 취소하고 로그에
`stream client_disconnected`를 남긴다. 미완성 검토는 저장하지 않는다. 다시 검토하려면 새로 요청한다.

## 내부 전용

`RunCompleted`(최종 그래프 상태)는 서버 내부에서만 쓰고 클라이언트로 보내지 않는다.
