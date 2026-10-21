# AI Mini-Project 진행 계획 — 완성차 공장 4M 변경 영향 검토 Agent

> SKALA 광주 AI Mini-Project (2026.10) / 과제 2번(신규 프로젝트) 선택
> Base AI Agent(`all_total_vue_student`)의 골격을 재사용하고 도메인만 완성차 공장 4M 변경 영향 검토로 교체한다


---

## 1. 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 과제 유형 | 과제 2번: 신규 프로젝트 개발 (Base 골격 재사용) |
| 주제 | 완성차 공장 4M 변경 영향 검토 Agent |
| 대상 | 국내 완성차 공장의 일반적인 공정 구조를 참고한 **가상의 완성차 공장** — 프레스 → 차체 → 도장 → 의장 |
| 한 줄 설명 | 공장에서 작업자(Man), 설비(Machine), 재료(Material), 공법(Method) 변경 요청이 들어오면 관련 표준서와 현장 데이터를 찾아 필요한 검증 항목을 도출하고, **다음 공정으로 번지는 영향**과 **변경 등급**까지 판단해 검증 누락을 막는 검토 보조 Agent |
| 포지셔닝 | 최종 판단은 품질 담당자가 한다. Agent는 누락을 막는 **검토 보조** 역할이며, 근거가 부족하면 "추가 확인 필요"로 내보낸다 |
| 재사용하는 것 | Supervisor 그래프(route → plan → gate → research → replan → write → validate), 의존성 주입(`SupervisorDeps`), SSE 스트리밍, Vue 채팅 화면(`web_chat.html`), LangSmith 연동, 재시도(`with_retry`), 병렬 실행, SQLite 세션 저장소 |
| 새로 만드는 것 | change_type 판별 노드, 공정 간 영향 검토, 변경 등급 판정, MCP 서버(Tool, Resource, Prompt), 프롬프트, fake LLM 4M 버전, 평가 스크립트, 아래 개선 항목 |
| Base에 없어서 새로 만들어야 하는 것 | 평가 스크립트(`eval/` 없음), 단위 테스트(0개), LangGraph Checkpointer(세션은 SQLite로 대체), 벡터 DB/임베딩 |

---

## 2. 과제 2번과 이 주제를 선택한 이유

### 평가표 관점
- **기술 요소**: Multi-Agent, MCP, LangSmith, 의존성 주입은 Base 골격에 이미 있으므로 도메인을 바꿔도 그대로 유지된다
- **Before/After**: 같은 코드에서 기능 스위치를 끈 Baseline과 켠 Improved를 같은 입력으로 비교하고, 개선 항목별 기여도까지 분리한다
- **코드 설명 가능성**: Capstone 강의에서 장별로 배운 구조를 그대로 쓰므로 발표 때 설명할 수 있다

### 도메인 관점
- 4M 변경관리가 가장 체계적으로 운영되는 산업이 자동차다. PFMEA, 관리계획서, 초기유동관리 같은 공개된 틀이 있어 검증 항목 체계를 지어낼 필요가 없다
- 4개 공장(프레스, 차체, 도장, 의장)마다 바뀌는 대상이 뚜렷이 달라 4M 네 유형을 고르게 채울 수 있다
- 공장이 순서대로 이어져 있어 **변경이 다음 공정으로 번지는 영향**을 보여 줄 수 있다. "엑셀 체크리스트로 충분하지 않은가"라는 질문에 대한 답이 이 부분이다

### 취업 관점
- 자동차 생산기술, 품질 직무와 직접 연결되는 도메인이다
- 장애 대응 Agent를 고친 결과물보다 자소서와 면접에서 쓸 수 있는 이야깃거리가 강하다

---

## 3. 진행 계획 

| 순번 | 영역 | 무엇을 바꾸나 | 추가설명 |
|---|---|---|---|
| 1 | 도메인 전환 | Base Agent의 장애 대응 도메인을 완성차 공장 4M 변경 영향 검토로 교체 | 그래프, LLM 프롬프트 3종(fake/ollama/openai), MCP 서버, 프론트 이벤트 문구(`STEP_LABELS`), 회귀 질문을 4M 도메인으로 재구성. `research_node`의 task 종류 분기를 Tool/Resource 매핑 표 방식으로 일반화 |
| 2 | MCP | 4M 도메인 Tool, Resource, Prompt 설계 | Tool: 설비 상태(`equipment.json`), 라인 가동 상태(`production.json`) 조회 / Resource: `std://shop-standard/{공장}`, `std://inspection-criteria/{공장}` (문서ID, 조항, 개정판 함께 반환) / Prompt: `4m_review(change_type=, shop=)`. Tool 결과가 판단에 실제로 쓰인다(설비 이상 → EXT-EQ-01, 가동 중 변경 → EXT-LOT-01) |
| 3 | 그래프 개선 | change_type과 공장 판별 노드 추가 | plan 앞에 `classify_change` 노드를 둔다. LLM 구조화 출력으로 `shop`, `change_types: list`를 받아 복합 변경을 허용하고, 키워드 기반 코드 보정을 안전망으로 둔다 |
| 4 | RAG | 표준서 검색을 키워드 매핑에서 RAG로 변경 ✅ (결과: doc/ROADMAP.md "RAG") | 표준서 9개를 조항 단위 41개 청크로 나눠 임베딩(Ollama `bge-m3`)하고 Chroma에 저장. `shop`, `change_types`를 메타데이터로 필터링 |
| 5 | 그래프 개선 | change_type별 필수 검증 항목 권위 게이트 | 규칙표(`data/4m/rules/required_items.json`)를 기준으로, LLM이 세운 계획에서 빠진 필수 항목을 코드가 강제로 추가 (Base 게이트는 task 제거만 하므로 추가 로직은 새로 작성) |
| 6 | 그래프 개선 | 공정 간 영향 검토 | `process_flow.json`의 규칙으로 변경 공장의 다음 공장 확인 항목(`DS-*`)을 도출. 예: 프레스 강판 변경 → 차체 용접 조건 재검증, 도장 전처리 확인 |
| 7 | 그래프 개선 | 변경 등급 판정 | QS-CM-001 조항 2 기준으로 A(품질본부 승인)/B(공장 품질팀)/C(공장 자체) 등급을 판정. 안전 체결부(브레이크, 조향, 에어백, 시트벨트, 연료)가 걸리면 A등급. 등급별 초기유동관리 기간도 함께 제시 |
| 8 | 검증 | Validator를 검증 누락 탐지용으로 특화 | 필수 항목 ID 포함 여부는 코드로, 의미 판단은 LLM Judge로 확인. 누락이 있으면 `review_status="추가 확인 필요"`와 `missing_items`를 응답에 담는다. Base의 "3회 실패 시 통과 처리"는 제거하고 같은 상태로 내보낸다 |
| 9 | 검증 | 근거 인용 | 응답의 검증 항목마다 `[ID] 항목명 — 문서ID Rev.X 조항 N` 형식으로 표기하고, Validator가 근거 없는 항목을 탐지 |
| 10 | 평가 | Recall·Precision 평가 스크립트 신규 작성 | 변경 요청 10건으로 Baseline과 Improved를 비교. Recall만 보면 항목을 다 나열해도 만점이므로 **Precision과 F1을 함께** 본다. 보조 지표: 분류 정확도, 등급 정확도, 검색 Recall@k, 근거 인용률, 지연 시간, 토큰, retry 횟수 |
| 11 | 테스트 | 단위 테스트 신규 작성 | pytest + mock `SupervisorDeps` + fake LLM 4M 버전. 데이터 정합성 테스트 10개는 작성 완료(`tests/test_4m_data.py`). 추가로 권위 게이트, 공정 간 영향 도출, 등급 판정, Validator 누락 판정, Recall/Precision 계산 함수 검증 |
| 12 | 측정 기반 | 공정한 측정 환경 정비 | 기능 스위치(`RETRIEVER`, `GATE_4M`, `FLOW_IMPACT`, `VALIDATOR`, `CITATION`) 추가, 데모용 강제 타임아웃(`flaky_first_tool_call`) 끄기, task당 고정 지연(0.35초) 제거, 응답 metadata에 토큰 수 추가 |

### 선택 항목

| 순번 | 영역 | 무엇을 바꾸나 | 추가설명 |
|---|---|---|---|
| 13 | 프론트엔드 | 검증 항목 체크리스트 화면 | `web_chat.html`에 "필수 검증 항목: 충족/누락" 카드, 변경 등급 배지, 다음 공정 영향 목록 추가. `STEP_LABELS`와 SSE 이벤트 타입(`RequiredItemsChecked`) 추가 |
| 14 | 그래프 개선 | Human-in-the-loop 승인 노드 | LangGraph `interrupt()`로 최종 판정 전 품질 담당자 승인. 실제 4M 흐름의 "결과 승인" 단계에 해당. Base에 Checkpointer가 없어 `MemorySaver`/`SqliteSaver` 도입과 프론트 승인 버튼까지 필요 |

### 넣지 않는 것

| 항목 | 이유 |
|---|---|
| 메모리 요약 (PDF 예시 5번) | 4M 검토는 대화가 길어지는 유형이 아니라 효과를 보여 주기 어렵다 |
| Research 서브그래프 분리 (PDF 예시 3번) | 이틀 안에 하면 디버깅 시간이 크게 늘어난다. 발표에서 "다음 개선 사항"으로만 언급 |
| 라우팅, 재계획, 재시도, 병렬 실행 재구현 | Base에 이미 있다. 도메인만 바꿔서 그대로 사용 |
| 4M 전체 흐름(신청 → 등급 → 검증 계획 → 실시 → 승인 → 초기유동 → 종결) | 이번에는 "등급 판정 + 검증 계획 수립"만 다룬다. 나머지는 발표에서 다음 개선 사항으로 언급 |

---

## 4. 도메인 데이터
`all_total_vue_student/data/4m/`에 작성했다. 상세 구조는 `data/4m/README.md` 참고.

| 데이터 | 경로 | 규모 |
|---|---|---|
| 규칙표 | `data/4m/rules/required_items.json` | 공통 필수 항목 13개, 4개 유형 규칙, 등급 정의 |
| 표준서, 검사기준 | `data/4m/standards/*.md` | 공통 규정 1 + 공장별 공정 표준 4 + 검사 기준 4 = 9개, 조항 41개 |
| 공정 흐름 | `data/4m/process_flow.json` | 4개 공장 흐름, 영향 규칙 4개, `DS-*` 항목 5개 |
| 설비 상태 | `data/4m/equipment.json` | 설비 9대 (이상 상태 3대, 그중 1대는 무관한 함정) |
| 라인 가동 상태 | `data/4m/production.json` | 라인 7개 (특근 가동 중 1개) |
| 평가 데이터셋 | `eval/4m_dataset.jsonl` (`eval/build_4m_dataset.py`로 생성) | 10건 |
| 정합성 테스트 | `tests/test_4m_data.py` | 10개, 전부 통과 |

### 정답의 세 층

| 층 | 어디서 나오나 | 누가 찾아내나 | 측정되는 효과 |
|---|---|---|---|
| ① 공통 필수 항목 (`required_items`) | 규칙표 | 권위 게이트 | 게이트 |
| ② 문서 근거 항목 (`extra_items`의 `EXT-PR/BD/PT/AS-*`) | 표준서 조건부 조항 | RAG | RAG |
| ③ 현장 데이터 항목 (`extra_items`의 `EXT-EQ-01`, `EXT-LOT-01`) | 설비·생산 Tool | MCP Tool | MCP |
| 공정 간 영향 (`downstream_items`) | 공정 흐름 규칙 | 영향 검토 노드 | 영향 전파 |

`required_items`는 규칙표에서 자동 계산하고, `extra_items`는 규칙표에 없는 항목만 넣는다(테스트로 강제). 정답을 규칙표에서만 뽑으면 게이트를 켠 쪽이 당연히 만점이 되는 순환 측정이 되기 때문이다.

### 평가 10건

| # | 공장 | 변경 요청 (요약) | 유형 | 등급 | extra / downstream | 함정 |
|---|---|---|---|---|---|---|
| 1 | 의장 | 도어 트림 공정 신입 4명 투입 | Man | C | — | 같은 라인의 무관한 교정 만료 설비 |
| 2 | 도장 | 수작업 실링 담당자 교체 | Man | C | — | 차체 실러와 도장 실링 혼동 |
| 3 | 차체 | 사이드 용접 로봇 2대 교체 | Machine | B | EXT-BD-01 | 정기 파괴 검사로 대체 불가 |
| 4 | 프레스 | 후드 외판 금형 수정 | Machine | B | EXT-PR-01 / DS-BD-02 | case 5와 같은 공장, 다른 유형 |
| 5 | 프레스 | 루프 강판 공급사 변경 | Material | B | — / DS-BD-01, DS-PT-01 | 사양 동일해도 영향 검토 대상 |
| 6 | 의장 | 브레이크 호스 브래킷 협력사 변경 신고 | Material | A | EXT-AS-01, EXT-AS-02 | "브레이크" = 안전 체결부 |
| 7 | 도장 | 상도 오븐 온도 프로파일 변경 | Method | B | EXT-PT-01 | 차체 실러 영향 항목은 해당 없음 |
| 8 | 차체 | 대시 패널 용접 전류 변경 | Method | B | EXT-BD-01, EXT-EQ-01 | Tool로 팁 교체 주기 초과 확인 |
| 9 | 의장 | 시트벨트 앵커 너트러너 교체 + 토크 변경 | Machine, Method | A | EXT-AS-01, EXT-AS-02 | 복합 변경 합집합 |
| 10 | 차체 | 플로어 신규 지그 + 구조용 접착제 변경 | Machine, Material | B | EXT-LOT-01 / DS-PT-02 | 주말이지만 특근 가동 중 |

---

## 5. Before/After 측정 설계

같은 코드에서 기능 스위치로 전환한다. git 커밋을 오가며 측정하지 않는다. Base의 `SUPERVISOR_VERSION=v1`(legacy 선형 파이프라인)과 헷갈리지 않도록 이름은 **Baseline / Improved**로 쓴다.

| 구분 | Baseline (Before) | Improved (After) | 스위치 |
|---|---|---|---|
| 표준서 검색 | 키워드 매핑 | RAG + 메타데이터 필터 | `RETRIEVER=keyword\|rag` |
| 필수 항목 보장 | LLM 계획에 의존 | 권위 게이트로 코드가 강제 | `GATE_4M=off\|on` |
| 공정 간 영향 | 변경 공장만 검토 | 다음 공장 확인 항목 도출 | `FLOW_IMPACT=off\|on` |
| 검증 | 범용 Validator(길이, 번호) | 누락 탐지 + 추가 확인 필요 상태 | `VALIDATOR=basic\|4m` |
| 근거 인용 | 없음 | 문서ID, 조항, 개정판 표기 + 근거 없는 항목 탐지 | `CITATION=off\|on` |

### 실행 조합
- Baseline(전부 off), Improved(전부 on), 그리고 스위치를 하나씩만 켠 조합 5개 → **개선 항목별 기여도 표**
- LLM 출력이 흔들리므로 조합마다 10건 × 3회 실행해 평균과 범위를 보고한다
- 개발과 반복 측정은 Ollama로 하고, 최종 1세트만 OpenAI로 돌린다. 한 비교 세트 안에서 백엔드를 섞지 않는다

### 지표

| 지표 | 계산 | 보여 주는 것 |
|---|---|---|
| Recall (① 공통 필수) | 정답 `required_items` 중 응답에 포함된 비율 | 권위 게이트 효과 |
| Recall (② 문서 근거) | 정답 `EXT-PR/BD/PT/AS-*` 중 포함 비율 | RAG 효과, 게이트의 한계 |
| Recall (③ 현장 데이터) | 정답 `EXT-EQ-01`, `EXT-LOT-01` 중 포함 비율 | MCP Tool 활용 |
| Recall (공정 간 영향) | 정답 `downstream_items` 중 포함 비율 | 영향 전파 효과 |
| **Precision** | 응답에 제시한 항목 중 정답(①+②+③+영향)에 있는 비율 | 불필요한 항목 남발 방지 |
| **F1** | Recall 전체와 Precision의 조화평균 | 종합 비교 지표 |
| change_type 분류 정확도 | 정답 `change_types`와 일치 여부 | 게이트와 RAG 필터의 전제 조건 |
| 변경 등급 정확도 | 정답 `change_grade`와 일치 여부 | 등급 판정 |
| 검색 Recall@k | 정답 `relevant_docs`가 상위 k개 청크에 있는 비율 | RAG 단독 효과 |
| 근거 인용률 | 검증 항목 중 문서ID, 조항, 개정판이 모두 붙은 비율 | 근거 인용 효과 |
| 지연 시간, 토큰, retry 횟수 | `/chat` 응답 `metadata` | 개선의 비용 |

- **측정 도구**: LangSmith Dataset + `evaluate()`. 대상 함수는 `POST /chat`을 호출하고 응답 `metadata`를 그대로 지표로 쓴다
- **채점 방식**: 응답에서 `[ID]` 패턴을 추출해 코드로 채점한다. 이를 위해 write 프롬프트에 "검증 항목마다 `[MAC-01]`처럼 ID를 표기하라"고 지시한다. 의미 판단이 필요한 부분만 LLM Judge를 쓴다
- **주의**: Base는 서버 기동 후 첫 Tool 호출을 일부러 실패시키는 데모 장치가 있다. 끄지 않으면 retry 횟수가 개선과 무관하게 나오므로 12번 항목에서 반드시 끈다

---

## 6. 한계와 트레이드오프 

| 개선 | 새로 생기는 약점 |
|---|---|
| change_type 판별 | 분류가 틀리면 게이트, RAG 필터, 영향 검토, Validator가 모두 엉뚱한 기준을 따른다. 오류가 뒤 단계로 연쇄된다 |
| RAG 도입 | 임베딩 비용과 검색 지연이 늘어난다. 표준서가 개정되면 다시 인덱싱해야 한다. 문서 수가 적으면 키워드 매핑과 차이가 작다 |
| 권위 게이트 | 필수 항목 규칙을 사람이 계속 관리해야 한다. 규칙에 없는 새 유형은 놓친다 ("② 문서 근거 Recall"로 수치 제시) |
| 공정 간 영향 검토 | 영향 규칙을 사람이 정의해야 한다. 규칙에 없는 영향 경로(예: 의장 → 도장 역방향 재작업)는 놓친다. 항목이 늘어 Precision이 떨어질 수 있다 |
| 변경 등급 판정 | 등급은 승인 주체를 정하는 민감한 판단이다. 잘못 낮추면 승인 절차를 건너뛰게 되므로 애매하면 높은 등급으로 내보낸다 |
| 누락 탐지 Validator | LLM Judge 호출만큼 지연과 비용이 늘어난다. Judge 자체의 편향(길이, 자기 선호)이 있다 |
| 근거 인용 | 표준서 조항 구조가 정리되어 있지 않으면 인용 정확도가 떨어진다 |
| Partial Result | 일부 표준서를 못 찾았을 때도 응답하는 것은 품질 맥락에서 위험하다. 응답 맨 위에 경고를 명시하고 "검토 완료"가 아닌 "추가 확인 필요" 상태로 내보낸다 |
| 가짜 데이터, 작은 표본 | 실제 공장 표준서는 수백 페이지이고 표와 그림이 섞여 있다. 직접 만든 9개 문서와 10건 × 3회 측정은 개념 증명(PoC) 수준이다 |

---

## 7. 평가표 매핑

| 평가 항목 | 배점 | 대응하는 계획 |
|---|---|---|
| 기능 구현 완성도 | 30 | 1\~9번이 실제로 동작하는지 회귀 질문과 단위 테스트로 확인 |
| Before/After 실측 비교 | 10 (보너스) | 10, 12번: Baseline과 Improved를 같은 10건 × 3회로 비교하고 항목별 기여도 제시 |
| 기술 요소 반영 | 30 | Multi-Agent(Supervisor 그래프), MCP(2번), RAG(4번), 의존성 주입(`SupervisorDeps`), LangSmith(10번), 모듈화, 단위 테스트(11번) |
| 한계와 트레이드오프 설명 | 20 | 7장 표, 층별 Recall과 Precision 수치 |
| 발표 PPT 작성 및 발표 | 20 | 문제 → 개선/추가 포인트 → Before/After 수치 → 한계와 추가 개선 사항 순서 |

---

## 8. Base 코드 점검 결과

### 확인 완료

- [x] **단위 테스트**: Base에는 0개, pytest 미설치 → 11번에서 신규 작성 (데이터 정합성 10개 작성 완료)
- [x] **의존성 주입**: `SupervisorDeps` + `functools.partial`로 모든 노드에 주입되어 있다(`agent/deps.py`, `agent/graph.py` `build_graph`). mock deps로 테스트하기 좋다. 단, `KNOWN_SYSTEMS`는 import 시점에 읽는 전역 변수라 주입 대상이 아니다
- [x] **Checkpointer**: 없음. `g.compile()`에 checkpointer를 넘기지 않고, 대화 이력은 `SqliteSessionStore`가 담당한다
- [x] **평가 스크립트**: 학생용 Base에는 `eval/`이 없다 → 10번에서 신규 작성
- [x] **프론트엔드**: `web_chat.html` 한 파일(Vue 3 CDN). 별도 컴포넌트나 Transport 계층 없이 `STEP_LABELS`로 이벤트를 표시한다

### 도메인 의존 코드 (1번 도메인 전환 대상)

| 파일 | 바꿀 곳 |
|---|---|
| `agent/graph.py` | `KNOWN_SYSTEMS`와 `auth-service` 폴백, MCP 프롬프트 이름, task 종류(`monitoring`/`runbook`)와 Tool/Resource 이름, `_INCIDENT_TYPE_RULES`, replan 판단 기준, Validator 기준(`"1)"` 포함, 3회 후 강제 통과) |
| `agent/ollama_llm.py`, `agent/openai_llm.py` | 시스템 프롬프트("ICT 운영"), `ROUTE_SCHEMA`, `PLAN_SCHEMA`, write의 사실 정리 형식(`cpu_percent` 등 필드명) |
| `agent/fake_llm.py` | `-service` 정규식과 결정론적 응답 전체 (테스트 기반이므로 4M 버전 필수) |
| `agent/mcp_client.py` | 강제 타임아웃 대상 Tool 이름(`get_monitoring_status`) |
| `agent/supervisor_v1.py` | `auth-service` 하드코딩 |
| `mcp_server.py` | 전체 (`data/4m/` 기반으로 재작성) |
| `web_chat.html` | `STEP_LABELS` 문구("모니터링 지표", "runbook", "장애유형") |
| `doc/regression_test_queries.md` | 회귀 질문 전체 → 4M 회귀 질문 |
| `requirements.txt` | `chromadb`, `pytest` 추가 |

기존 장애 대응 데이터(`data/monitoring.json`, `data/runbooks/`)는 도메인 전환이 끝날 때까지 남겨 둔다.

